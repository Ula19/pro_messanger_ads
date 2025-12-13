import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser


class CustomUser(AbstractUser):
    """Кастомная модель пользователя с UUID"""
    user_id = models.UUIDField(verbose_name='User ID', default=uuid.uuid4, editable=False, unique=True)

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f"{self.username} ({self.user_id})"


class Channel(models.Model):
    """Модель канала"""
    channel_id = models.CharField(verbose_name='Channel ID', max_length=255, unique=True,)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='channels', verbose_name='User')
    name = models.CharField(verbose_name='Channel Name', max_length=255)
    order_name = models.CharField(verbose_name='Order Name', max_length=255)
    tags = models.CharField(verbose_name='Tags', default=list, blank=True, help_text='List of tags')
    spm = models.DecimalField(verbose_name='SPM', max_digits=10, decimal_places=2, help_text='Spend per mille')
    budget = models.DecimalField(verbose_name='Budget', max_digits=15, decimal_places=2)
    is_active = models.BooleanField(verbose_name='Is Active', default=True)
    created_at = models.DateTimeField(verbose_name='Created At', auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name='Updated At', auto_now=True)

    class Meta:
        verbose_name = 'Channel'
        verbose_name_plural = 'Channels'
        ordering = ['-created_at']
        # indexes = [
        #     models.Index(fields=['channel_id']),
        #     models.Index(fields=['user', 'is_active']),
        # ]

    def __str__(self):
        return f"{self.name} ({self.channel_id})"
