import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    """Кастомная модель пользователя с UUID"""

    class Role(models.TextChoices):
        ADVERTISER = 'ADVERTISER', 'Рекламодатель'  # обычный пользователь, покупает рекламу
        MODERATOR = 'MODERATOR', 'Модератор'        # проверяет рекламу, одобряет/отклоняет

    user_id = models.UUIDField(verbose_name='User ID', default=uuid.uuid4, editable=False, unique=True)
    role = models.CharField(
        verbose_name='Роль', max_length=20,
        choices=Role.choices, default=Role.ADVERTISER,
        help_text='Роль назначает суперадмин. Каждый новый пользователь — рекламодатель',
    )
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

    @property
    def is_moderator(self):
        """Может ли пользователь модерировать рекламу (модератор или суперадмин)"""
        return self.is_superuser or self.role == self.Role.MODERATOR

    @property
    def api_role(self):
        """Роль для ответов API: суперадмин отдаётся как ADMIN, чтобы фронт его узнал"""
        return 'ADMIN' if self.is_superuser else self.role
