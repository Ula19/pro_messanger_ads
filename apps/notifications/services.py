import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q

from .models import Notification
from .tasks import send_push_notification

logger = logging.getLogger(__name__)


def notify(user, title, body, notif_type, payload):
    """
    Создаёт in-app уведомление и после коммита транзакции ставит
    Celery-задачу отправки push. In-app запись — главное (не теряется),
    push — best-effort поверх неё.
    """
    notification = Notification.objects.create(
        user=user, title=title, body=body, type=notif_type, payload=payload,
    )
    # on_commit — воркер не должен увидеть уведомление раньше, чем оно закоммичено
    # (мы вызываемся из-под transaction.atomic создания/модерации заказа)
    transaction.on_commit(lambda: _enqueue_push(notification.pk))
    return notification


def _enqueue_push(notification_id):
    # .delay() падает, если брокер недоступен (dev без Redis) — уведомление
    # уже в БД, поэтому просто логируем и не роняем ответ юзеру
    try:
        send_push_notification.delay(notification_id)
    except Exception:
        logger.exception('Не удалось поставить push-задачу для уведомления %s', notification_id)


def notify_moderators_new_order(order):
    """Заказ создан (PENDING) — сообщаем всем модераторам и суперадминам"""
    User = get_user_model()
    ad_type = 'реклама в чатах' if order._meta.app_label == 'chat_ads' else 'реклама в поиске'
    payload = {'order_id': str(order.order_id), 'order_type': order._meta.app_label}

    moderators = User.objects.filter(
        Q(role=User.Role.MODERATOR) | Q(is_superuser=True), is_active=True,
    )
    for moderator in moderators:
        notify(moderator, 'Новый заказ на модерацию',
               f'«{order.order_name}» ({ad_type}) ждёт проверки',
               Notification.Type.NEW_ORDER, payload)


# Тексты уведомлений о решении модератора по статусу заказа
_DECISION_TEXTS = {
    'APPROVED': (Notification.Type.ORDER_APPROVED, 'Заказ одобрен',
                 'Ваш заказ «{name}» одобрен и запущен'),
    'REJECTED': (Notification.Type.ORDER_REJECTED, 'Заказ отклонён',
                 'Ваш заказ «{name}» отклонён. Причина: {reason}. Деньги возвращены на баланс'),
    'BLOCKED': (Notification.Type.ORDER_BLOCKED, 'Заказ заблокирован',
                'Ваш заказ «{name}» заблокирован. Причина: {reason}. '
                'Неизрасходованный остаток возвращён на баланс'),
}


def notify_order_decision(order):
    """Решение модератора принято — сообщаем владельцу заказа"""
    notif_type, title, body_template = _DECISION_TEXTS[order.status]
    body = body_template.format(name=order.order_name, reason=order.reject_reason)
    payload = {'order_id': str(order.order_id), 'order_type': order._meta.app_label}
    notify(order.user, title, body, notif_type, payload)
