import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    """Кастомная модель пользователя с UUID"""
    user_id = models.UUIDField(verbose_name='User ID', default=uuid.uuid4, editable=False, unique=True)
    is_admin = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f"{self.username} ({self.user_id})"
