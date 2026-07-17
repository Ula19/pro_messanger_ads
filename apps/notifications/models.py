from django.conf import settings
from django.db import models


class Device(models.Model):
    """
    FCM-токен устройства пользователя (приложение NovaGram Business).
    Приложение регистрирует токен после логина, по нему уходят push-уведомления.
    """
    class Platform(models.TextChoices):
        IOS = 'IOS', 'iOS'
        ANDROID = 'ANDROID', 'Android'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='devices', verbose_name='Пользователь')
    # unique — один и тот же токен не может числиться за двумя юзерами:
    # при релогине на том же устройстве запись просто переезжает к новому юзеру
    token = models.CharField(verbose_name='FCM-токен', max_length=500, unique=True)
    platform = models.CharField(verbose_name='Платформа', max_length=10, choices=Platform.choices)
    is_active = models.BooleanField(verbose_name='Активен', default=True,
                                    help_text='False — FCM сказал, что токен протух (приложение удалено)')
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Устройство'
        verbose_name_plural = 'Устройства'

    def __str__(self):
        return f"{self.user} ({self.platform}, {'вкл' if self.is_active else 'выкл'})"


class Notification(models.Model):
    """
    In-app уведомление (экран «Уведомления» в NovaGram Business).
    Создаётся всегда, даже если push отключён или не дошёл — юзер увидит в приложении.
    """
    class Type(models.TextChoices):
        NEW_ORDER = 'NEW_ORDER', 'Новый заказ на модерацию'
        ORDER_APPROVED = 'ORDER_APPROVED', 'Заказ одобрен'
        ORDER_REJECTED = 'ORDER_REJECTED', 'Заказ отклонён'
        ORDER_BLOCKED = 'ORDER_BLOCKED', 'Заказ заблокирован'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='notifications', verbose_name='Кому')
    title = models.CharField(verbose_name='Заголовок', max_length=255)
    body = models.CharField(verbose_name='Текст', max_length=1000)
    type = models.CharField(verbose_name='Тип', max_length=20, choices=Type.choices)
    # {'order_id': ..., 'order_type': 'search_ads'|'chat_ads'} — клиент по тапу открывает нужный экран
    payload = models.JSONField(verbose_name='Данные для клиента', default=dict, blank=True)
    is_read = models.BooleanField(verbose_name='Прочитано', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Уведомление'
        verbose_name_plural = 'Уведомления'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),  # список уведомлений юзера
            models.Index(fields=['user', 'is_read']),      # счётчик непрочитанных
        ]

    def __str__(self):
        return f"{self.user}: {self.title}"
