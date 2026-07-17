import logging
import os

from django.conf import settings

from core.celery import app

from .models import Device, Notification

logger = logging.getLogger(__name__)

# Инициализированное приложение firebase-admin (одно на процесс воркера)
_firebase_app = None


def _get_firebase_app():
    """
    Ленивая инициализация firebase-admin по сервисному ключу из .env.
    Ключа нет (ещё не выдали / dev-окружение) — push молча отключён,
    бэкенд и in-app уведомления работают как обычно.
    """
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    cred_path = settings.FIREBASE_CREDENTIALS_FILE
    if not cred_path or not os.path.exists(cred_path):
        logger.info('FIREBASE_CREDENTIALS_FILE не задан или файла нет — push пропущен')
        return None

    import firebase_admin
    from firebase_admin import credentials
    _firebase_app = firebase_admin.initialize_app(credentials.Certificate(cred_path))
    return _firebase_app


@app.task
def send_push_notification(notification_id):
    """Шлёт push по всем активным устройствам получателя уведомления"""
    notification = Notification.objects.select_related('user').filter(pk=notification_id).first()
    if notification is None:
        return 'Уведомление не найдено'

    tokens = list(notification.user.devices.filter(is_active=True)
                  .values_list('token', flat=True))
    if not tokens:
        return 'У юзера нет активных устройств'
    if _get_firebase_app() is None:
        return 'Push пропущен: нет ключа Firebase'

    from firebase_admin import messaging

    # В data FCM пускает только строки
    data = {'type': notification.type,
            **{key: str(value) for key, value in notification.payload.items()}}
    message = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=notification.title, body=notification.body),
        data=data,
    )
    response = messaging.send_each_for_multicast(message)

    # Токены удалённых приложений FCM помечает UnregisteredError — выключаем их
    dead_tokens = [
        tokens[i] for i, result in enumerate(response.responses)
        if result.exception and isinstance(result.exception, messaging.UnregisteredError)
    ]
    if dead_tokens:
        Device.objects.filter(token__in=dead_tokens).update(is_active=False)

    return f'Отправлено {response.success_count}/{len(tokens)}'
