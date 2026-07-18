from decimal import Decimal, ROUND_DOWN

from django.conf import settings
from django.db import models
from django.utils import timezone


class ModerationStatus(models.TextChoices):
    """Статусы модерации рекламного заказа"""
    PENDING = 'PENDING', 'На модерации'
    APPROVED = 'APPROVED', 'Одобрен'
    REJECTED = 'REJECTED', 'Отклонён'          # не прошёл проверку, деньги возвращены полностью
    BLOCKED = 'BLOCKED', 'Заблокирован'        # остановлен за нарушение, возвращён остаток


class ModerationMixin(models.Model):
    """
    Общие поля и логика модерации для заказов рекламы (Order и ChatAdOrder).

    ВАЖНО: approve/reject/block меняют статус и возвращают деньги, поэтому
    вызывать их можно ТОЛЬКО на объекте, полученном через select_for_update()
    внутри transaction.atomic(). Иначе два параллельных запроса могут вернуть
    деньги дважды.
    """
    status = models.CharField(
        verbose_name='Статус модерации',
        max_length=10,
        choices=ModerationStatus.choices,
        default=ModerationStatus.PENDING,
        db_index=True,
    )
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',  # обратная связь от модератора к заказам не нужна
        verbose_name='Кто модерировал',
    )
    moderated_at = models.DateTimeField(verbose_name='Когда модерировали', null=True, blank=True)
    reject_reason = models.CharField(
        verbose_name='Причина отклонения/блокировки',
        max_length=500,
        blank=True,
        default='',
    )

    class Meta:
        abstract = True

    def _refund_unspent(self):
        """
        Возвращает пользователю деньги за неизрасходованные показы и обнуляет остаток.

        Если не было ни одного показа — возвращаем бюджет целиком: из-за int()-усечения
        в total_views возврат по формуле был бы чуть меньше бюджета (терялись бы копейки).
        """
        if self.shown_views == 0:
            refund_amount = self.budget
        else:
            refund_amount = (Decimal(self.remaining_views) / Decimal(1000)) * self.spm
            # Баланс хранится с точностью 2 знака — округляем вниз до копеек,
            # как и выплаты партнёрам (иначе база округлила бы сама и непредсказуемо)
            refund_amount = refund_amount.quantize(Decimal('0.01'), rounding=ROUND_DOWN)

        if refund_amount > 0:
            self.user.balance.deposit(refund_amount)

        self.remaining_views = 0
        return refund_amount

    def get_refund_amount(self):
        """
        Сумма, которую вернём при отмене/блокировке (для отображения пользователю).
        Считает так же, как реальный возврат в _refund_unspent().
        """
        # По отменённому/отклонённому/заблокированному возвращать уже нечего
        if self.cancelled or self.status in (ModerationStatus.REJECTED, ModerationStatus.BLOCKED):
            return Decimal('0')
        if self.shown_views == 0:
            return self.budget
        if self.remaining_views > 0:
            refund_amount = (Decimal(self.remaining_views) / Decimal(1000)) * self.spm
            return refund_amount.quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        return Decimal('0')

    def set_initial_moderation_status(self):
        """
        Статус нового заказа. Вызывается из save() моделей при создании.
        Суперадмин модерирует сам себя — его заказ сразу APPROVED и активен;
        заказы остальных уходят в очередь модерации (PENDING, выключен).
        """
        if self.user.is_superuser:
            self.status = ModerationStatus.APPROVED
            self.is_active = True
            self.moderated_by = self.user
            self.moderated_at = timezone.now()
        else:
            self.status = ModerationStatus.PENDING
            self.is_active = False

    def approve(self, moderator):
        """
        Одобряет заказ — включает показы. Разрешено только из статуса PENDING.
        Это единственный путь, которым заказ впервые становится активным.
        Возвращает True/False (успех/нельзя).
        """
        if self.status != ModerationStatus.PENDING or self.cancelled:
            return False
        self.status = ModerationStatus.APPROVED
        self.is_active = True
        self.moderated_by = moderator
        self.moderated_at = timezone.now()
        self.save()
        self._notify_owner()
        return True

    def reject(self, moderator, reason):
        """
        Отклоняет заказ с полным возвратом денег. Разрешено только из PENDING.
        Возвращает сумму возврата или None (нельзя отклонить).
        """
        if self.status != ModerationStatus.PENDING or self.cancelled:
            return None
        refund_amount = self._refund_unspent()
        self.status = ModerationStatus.REJECTED
        self.is_active = False
        self.reject_reason = reason
        self.moderated_by = moderator
        self.moderated_at = timezone.now()
        self.save()
        self._notify_owner()
        return refund_amount

    def block(self, moderator, reason):
        """
        Блокирует заказ за нарушение (навсегда) и возвращает неизрасходованный остаток.
        Разрешено из PENDING и APPROVED (в том числе для уже завершённого заказа —
        тогда возврат будет 0, но факт нарушения зафиксируется).
        Возвращает сумму возврата или None (нельзя заблокировать).
        """
        if self.status not in (ModerationStatus.PENDING, ModerationStatus.APPROVED) or self.cancelled:
            return None
        refund_amount = self._refund_unspent()
        self.status = ModerationStatus.BLOCKED
        self.is_active = False
        self.reject_reason = reason
        self.moderated_by = moderator
        self.moderated_at = timezone.now()
        self.save()
        self._notify_owner()
        return refund_amount

    def _notify_owner(self):
        """Уведомляет владельца заказа о решении модератора (in-app + push)"""
        # Импорт внутри метода — иначе циклический импорт common <-> notifications
        from apps.notifications.services import notify_order_decision
        notify_order_decision(self)
