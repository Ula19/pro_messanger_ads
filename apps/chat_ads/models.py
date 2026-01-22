import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, FileExtensionValidator
from django.db import models


class ChatAdMedia(models.Model):
    """
    Временное (или постоянное) хранилище для медиафайлов.
    Файл загружается сюда ДО создания заказа.
    """

    class MediaType(models.TextChoices):
        IMAGE = 'IMAGE', 'Изображение'
        VIDEO = 'VIDEO', 'Видео'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_ad_media')

    file = models.FileField(
        upload_to='chat_ads/temp/',
        verbose_name='Файл',
        validators=[
            FileExtensionValidator(
                allowed_extensions=['jpg', 'jpeg', 'png', 'mp4', 'mov']
            )
        ]
        )
    media_type = models.CharField(max_length=10, choices=MediaType.choices)

    created_at = models.DateTimeField(auto_now_add=True)

    # Флаг, привязан ли файл к заказу (чтобы потом удалять мусор)
    is_linked = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.media_type} by {self.user.username} ({self.id})"


class ChatAdOrder(models.Model):
    """Модель рекламы для чатов каналов"""
    order_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_ads',
                             verbose_name='Пользователь')

    # Основные данные рекламы
    order_name = models.CharField(verbose_name='Название заказа', max_length=255)
    text = models.TextField(verbose_name='Текст рекламы', help_text='Основной текст рекламного сообщения')
    link = models.CharField(verbose_name='Ссылка рекламы', help_text='URL для перехода по рекламе')

    # Поле для указания каналов (строка с названиями через запятую)
    channels = models.TextField(verbose_name='Каналы для показа',
                                help_text='Названия каналов через запятую (например: "channel1, channel2")')

    # ВМЕСТО старых полей image и video делаем связь с Media
    # null=True, blank=True — если реклама только текстовая
    media_url = models.ForeignKey(
        ChatAdMedia,
        on_delete=models.SET_NULL,  # Если медиа удалят, заказ останется (но без картинки)
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='Медиа-вложение'
    )

    # Параметры заказа
    spm = models.DecimalField(
        verbose_name='SPM',
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Стоимость за 1000 показов'
    )
    budget = models.DecimalField(
        verbose_name='Бюджет',
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )

    # Статистика и управление показами
    total_views = models.PositiveIntegerField(verbose_name='Всего показов', default=0,
                                              help_text='Общее количество купленных показов')
    clicks = models.PositiveIntegerField(verbose_name='Клики', default=0,
                                         help_text='Количество переходов по рекламе')
    shown_views = models.PositiveIntegerField(verbose_name='Показано просмотров', default=0,
                                              help_text='Количество уже показанных просмотров')
    remaining_views = models.PositiveIntegerField(verbose_name='Оставшиеся показы', default=0,
                                                  help_text='Оставшееся количество показов')

    # Ограничения
    max_views_per_user = models.IntegerField(verbose_name='Лимит показов на юзера', default=-1,
                                             help_text='-1 означает без ограничений (показывать всегда)')

    # Статусы
    completed = models.BooleanField(verbose_name='Завершено', default=False,
                                    help_text='Реклама завершена (просмотры израсходованы)')
    cancelled = models.BooleanField(verbose_name='Отменено', default=False,
                                    help_text='Реклама отменена пользователем')
    is_active = models.BooleanField(verbose_name='Активно', default=True,
                                    help_text='Реклама активна и показывается')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Реклама в чате'
        verbose_name_plural = 'Реклама в чатах'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', 'completed']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Ad {self.order_id} by {self.user.username} (Left: {self.remaining_views})"

    def get_channel_list(self):
        """Возвращает список каналов из строкового поля"""
        if not self.channels:
            return []
        # Убираем пробелы и разделяем по запятой
        return [channel.strip() for channel in self.channels.split(',') if channel.strip()]

    def is_channel_in_list(self, channel_name):
        """Проверяет, есть ли канал в списке для показа"""
        channel_list = self.get_channel_list()
        return channel_name in channel_list

    def calculate_views_from_budget(self):
        """Рассчитывает количество показов на основе SPM и бюджета"""
        if self.spm > 0:
            views = (self.budget / self.spm) * 1000
            return int(views)
        return 0

    def save(self, *args, **kwargs):
        """При сохранении заказа рассчитываем количество показов"""
        # ИСПРАВЛЕНИЕ: Используем _state.adding вместо pk is None
        # так как UUID присваивается до сохранения
        is_new = self._state.adding

        # Если это новый заказ, рассчитываем количество показов
        if is_new and self.budget and self.spm:
            self.total_views = self.calculate_views_from_budget()
            self.remaining_views = self.total_views

        super().save(*args, **kwargs)

    def decrement_views(self, amount=1):
        """Уменьшает количество оставшихся показов"""
        if self.remaining_views >= amount and not self.cancelled:
            self.shown_views += amount
            self.remaining_views -= amount

            # Проверяем, не израсходованы ли все показы
            if self.remaining_views == 0:
                self.completed = True
                self.is_active = False

            self.save(update_fields=['shown_views', 'remaining_views', 'completed', 'is_active'])
            return True
        return False

    def increment_clicks(self):
        """Увеличивает счетчик кликов на 1"""
        self.clicks += 1
        self.save(update_fields=['clicks'])

    def cancel_order(self):
        """Отменяет заказ и возвращает средства за оставшиеся показы"""
        if not self.cancelled:
            self.cancelled = True
            self.is_active = False
            self.completed = False

            # Рассчитываем сумму для возврата
            refund_amount = (Decimal(self.remaining_views) / Decimal(1000)) * self.spm

            # Возвращаем средства на баланс пользователя
            balance = self.user.balance
            balance.deposit(refund_amount)

            # Сбрасываем оставшиеся показы
            self.remaining_views = 0

            self.save()
            return refund_amount
        return 0

    def get_refund_amount(self):
        """Рассчитывает сумму возврата при отмене"""
        if self.remaining_views > 0:
            return (Decimal(self.remaining_views) / Decimal(1000)) * self.spm
        return 0


class ChatAdView(models.Model):
    """Модель для отслеживания показов рекламы в чатах конкретным пользователям"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        ChatAdOrder,
        on_delete=models.CASCADE,
        related_name='views',
        verbose_name='Рекламный заказ'
    )
    viewer_id = models.CharField(
        verbose_name='ID пользователя',
        max_length=255,
        db_index=True,
        help_text='ID пользователя, которому показывается реклама'
    )
    view_count = models.PositiveIntegerField(
        verbose_name='Количество просмотров',
        default=0,
        help_text='Сколько раз пользователю показали эту рекламу'
    )
    clicked = models.BooleanField(
        verbose_name='Кликнул',
        default=False,
        help_text='Пользователь кликнул по рекламе'
    )
    last_viewed_at = models.DateTimeField(
        verbose_name='Последний просмотр',
        auto_now=True
    )
    first_viewed_at = models.DateTimeField(
        verbose_name='Первый просмотр',
        auto_now_add=True
    )

    class Meta:
        verbose_name = 'Показ рекламы в чате'
        verbose_name_plural = 'Показы рекламы в чатах'
        unique_together = ['order', 'viewer_id']
        indexes = [
            models.Index(fields=['viewer_id', 'order']),
            models.Index(fields=['last_viewed_at']),
            models.Index(fields=['first_viewed_at']),
        ]

    def __str__(self):
        return f"{self.viewer_id} - заказ {self.order.order_id.hex[:8]} ({self.view_count})"

    def can_view_more(self):
        """Проверяет, можно ли показать еще рекламу этому пользователю"""
        if self.order.max_views_per_user == -1:  # 0 означает неограниченно
            return True
        return self.view_count < self.order.max_views_per_user

    def increment_view(self):
        """Увеличивает счетчик просмотров"""
        self.view_count += 1
        self.save(update_fields=['view_count', 'last_viewed_at'])
        return True

    def mark_as_clicked(self):
        """Отмечает, что пользователь кликнул по рекламе"""
        if not self.clicked:
            self.clicked = True
            self.save(update_fields=['clicked'])
            # Увеличиваем счетчик кликов в заказе
            self.order.increment_clicks()
        return True
