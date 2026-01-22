from decimal import Decimal

from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator



class Balance(models.Model):
    """Модель баланса пользователя"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='balance',
        verbose_name='User'
    )
    amount = models.DecimalField(
        verbose_name='Сумма баланса',
        max_digits=15,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    add_amount = models.DecimalField(
        verbose_name='Пополнить',
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        default=0.00,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Сумма будет ДОБАВЛЕНА к балансу'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Balance'
        verbose_name_plural = 'Balances'

    def __str__(self):
        return f"{self.user.username}: {self.amount}"

    def deposit(self, amount):
        """Пополнение баланса"""
        self.amount += Decimal(amount)
        self.save()

    def withdraw(self, amount):
        """Списание с баланса (с проверкой)"""
        if self.amount >= amount:
            self.amount -= amount
            self.save()
            return True
        return False

    def get_available_amount(self):
        """Получение доступного баланса"""
        return self.amount
