from decimal import Decimal, ROUND_DOWN

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone


class ChannelEarning(models.Model):
    """
    Счёт заработка канала-площадки.

    Одна строка на канал (по нормализованному имени). Заработок копится здесь
    ДО того, как владелец канала зарегистрируется в приложении: ключом служит
    имя канала, а не пользователь. Когда владелец заходит и подтверждает права
    на канал (claim), к строке привязывается `owner`, и он может вывести деньги.
    """

    class ClaimStatus(models.TextChoices):
        UNCLAIMED = 'UNCLAIMED', 'Не заявлен'
        PENDING = 'PENDING', 'Ожидает подтверждения'
        CONFIRMED = 'CONFIRMED', 'Подтверждён'

    # Нормализованное имя канала — ключ начисления.
    channel_name = models.CharField(
        verbose_name='Канал-площадка',
        max_length=255,
        unique=True,
        db_index=True,
    )

    # Владелец. Заполняется только после подтверждения (CONFIRMED).
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='channel_earnings',
        verbose_name='Владелец',
    )
    # Кто запросил права (ждёт подтверждения админом).
    pending_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pending_channel_earnings',
        verbose_name='Заявитель',
    )
    claim_status = models.CharField(
        verbose_name='Статус заявки',
        max_length=10,
        choices=ClaimStatus.choices,
        default=ClaimStatus.UNCLAIMED,
    )
    claimed_at = models.DateTimeField('Подтверждён', null=True, blank=True)

    # Деньги храним с повышенной точностью (4 знака): цена одного показа может
    # быть долями тийина, и округление КАЖДОГО показа до 2 знаков потеряло бы всё.
    # Округляем до копеек/тийинов только при выводе.
    available = models.DecimalField(
        verbose_name='Доступно к выводу',
        max_digits=18,
        decimal_places=4,
        default=Decimal('0'),
    )
    total_earned = models.DecimalField(
        verbose_name='Заработано всего',
        max_digits=18,
        decimal_places=4,
        default=Decimal('0'),
    )
    total_impressions = models.PositiveBigIntegerField(
        verbose_name='Показов оплачено',
        default=0,
    )

    # Доля площадки. NULL → берём глобальную PARTNER_SHARE_RATE из настроек.
    # Это даёт «настраиваемо»: можно поменять глобально или задать каналу свою долю.
    share_rate = models.DecimalField(
        verbose_name='Доля площадки',
        max_digits=4,
        decimal_places=3,
        null=True,
        blank=True,
        help_text='Например 0.5 = 50%. Пусто — берётся значение по умолчанию.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Заработок канала'
        verbose_name_plural = 'Заработок каналов'
        ordering = ['-total_earned']

    def __str__(self):
        return f"{self.channel_name}: {self.available} (всего {self.total_earned})"

    @staticmethod
    def normalize_name(name):
        """Приводим имя канала к единому виду, чтобы начисление и claim совпадали."""
        if not name:
            return ''
        return name.strip().lstrip('@').lower()

    def get_share_rate(self):
        """Доля канала: индивидуальная либо глобальная из настроек."""
        if self.share_rate is not None:
            return self.share_rate
        return Decimal(str(settings.PARTNER_SHARE_RATE))

    @classmethod
    def accrue(cls, channel_name, order, impressions=1):
        """
        Начисляет заработок каналу-площадке за показ(ы) рекламы.

        Вызывать ВНУТРИ transaction.atomic() — в момент показа, после списания
        просмотра. Счётчики наращиваются F-выражениями (защита от гонок),
        отдельная строка-агрегат в EarningTransaction копит разбивку по заказу.

        Сумму НЕ округляем — точность 4 знака сохраняет доли тийина.
        Возвращает начисленную сумму (Decimal) либо None, если имя пустое.
        """
        norm = cls.normalize_name(channel_name)
        if not norm or impressions <= 0:
            return None

        earning, _ = cls.objects.get_or_create(channel_name=norm)

        rate = earning.get_share_rate()
        price_per_impression = order.spm / Decimal(1000)
        amount = price_per_impression * Decimal(rate) * Decimal(impressions)

        # Атомарно наращиваем счётчики счёта.
        cls.objects.filter(pk=earning.pk).update(
            available=models.F('available') + amount,
            total_earned=models.F('total_earned') + amount,
            total_impressions=models.F('total_impressions') + impressions,
        )

        # Лог-агрегат: одна строка на пару (канал, заказ).
        txn, created = EarningTransaction.objects.get_or_create(
            channel=earning,
            order=order,
            kind=EarningTransaction.Kind.ACCRUAL,
            defaults={'amount': amount, 'impressions': impressions},
        )
        if not created:
            EarningTransaction.objects.filter(pk=txn.pk).update(
                amount=models.F('amount') + amount,
                impressions=models.F('impressions') + impressions,
            )

        return amount

    def withdraw_to_balance(self):
        """
        Переводит доступный заработок на рекламный баланс владельца.

        Счёт заработка отдельный, поэтому перевод — явное действие. На баланс
        (точность 2 знака) уходит сумма, округлённая вниз до тийина; дробный
        остаток остаётся на счёте заработка. Вызывать под select_for_update.
        Возвращает переведённую сумму (Decimal).
        """
        if self.claim_status != self.ClaimStatus.CONFIRMED or not self.owner:
            raise ValueError('Канал не подтверждён за пользователем')

        payout = self.available.quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        if payout <= 0:
            return Decimal('0')

        self.available -= payout
        self.save(update_fields=['available', 'updated_at'])

        # Зачисляем на рекламный баланс владельца.
        self.owner.balance.deposit(payout)

        EarningTransaction.objects.create(
            channel=self,
            order=None,
            kind=EarningTransaction.Kind.PAYOUT,
            amount=payout,
            impressions=0,
        )
        return payout

    def confirm_claim(self):
        """Подтверждает права заявителя на канал (используется в админке)."""
        if not self.pending_owner:
            raise ValueError('Нет заявителя для подтверждения')
        self.owner = self.pending_owner
        self.pending_owner = None
        self.claim_status = self.ClaimStatus.CONFIRMED
        self.claimed_at = timezone.now()
        self.save(update_fields=['owner', 'pending_owner', 'claim_status', 'claimed_at', 'updated_at'])


class EarningTransaction(models.Model):
    """
    Журнал операций по заработку (для прозрачности и сверки).

    accrual — начисление за показы (агрегируется по паре канал+заказ).
    payout  — вывод заработка на рекламный баланс.
    """

    class Kind(models.TextChoices):
        ACCRUAL = 'ACCRUAL', 'Начисление'
        PAYOUT = 'PAYOUT', 'Вывод'

    channel = models.ForeignKey(
        ChannelEarning,
        on_delete=models.CASCADE,
        related_name='transactions',
        verbose_name='Канал',
    )
    order = models.ForeignKey(
        'chat_ads.ChatAdOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='earning_transactions',
        verbose_name='Заказ-источник',
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, verbose_name='Тип')
    amount = models.DecimalField(max_digits=18, decimal_places=4, verbose_name='Сумма')
    impressions = models.PositiveBigIntegerField(default=0, verbose_name='Показов')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Операция по заработку'
        verbose_name_plural = 'Операции по заработку'
        ordering = ['-updated_at']
        constraints = [
            # На пару (канал, заказ) держим один агрегат начисления.
            models.UniqueConstraint(
                fields=['channel', 'order', 'kind'],
                name='uniq_accrual_per_channel_order',
            ),
        ]
        indexes = [
            models.Index(fields=['channel', 'kind']),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} ({self.channel.channel_name})"
