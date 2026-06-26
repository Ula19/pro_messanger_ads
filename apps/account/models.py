import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    """Кастомная модель пользователя с UUID"""
    user_id = models.UUIDField(verbose_name='User ID', default=uuid.uuid4, editable=False, unique=True)
    is_admin = models.BooleanField(default=False)
    # Числовой id пользователя в Telegram. Клиент (NovaGram) знает его, так как
    # залогинен под этим пользователем; используется для привязки/claim каналов.
    telegram_id = models.BigIntegerField(
        verbose_name='Telegram ID', null=True, blank=True, unique=True,
        help_text='Числовой id пользователя в Telegram'
    )

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f"{self.username} ({self.user_id})"
