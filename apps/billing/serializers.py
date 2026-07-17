from decimal import Decimal
from rest_framework import serializers
from django.contrib.auth import get_user_model

from apps.billing.models import Balance

User = get_user_model()


class BalanceSerializer(serializers.ModelSerializer):
    """Сериализатор для баланса"""
    username = serializers.CharField(source='user.username', read_only=True)
    user_id = serializers.CharField(source='user.user_id')

    class Meta:
        model = Balance
        fields = ['username', 'amount', 'user_id']
        read_only_fields = ['user', 'username', 'user_id']


class AdminDepositSerializer(serializers.Serializer):
    """Сериализатор для пополнения баланса суперадмином"""
    user_id = serializers.UUIDField(required=True, help_text='UUID пользователя')
    amount = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        required=True,
        min_value=Decimal('0.01'),
        help_text='Сумма для пополнения'
    )

    def validate(self, data):
        """
        Валидация данных пополнения баланса
        """
        user_id = data['user_id']
        amount = data['amount']

        # Проверяем, что сумма положительная
        if amount <= 0:
            raise serializers.ValidationError({
                "amount": "Сумма должна быть больше 0"
            })

        # Проверяем существование пользователя
        try:
            user = User.objects.get(user_id=user_id)
            data['user'] = user  # Сохраняем объект пользователя для использования во view
        except User.DoesNotExist:
            raise serializers.ValidationError({
                "user_id": f"Пользователь с ID {user_id} не найден"
            })

        # Свой баланс суперадмин тоже может пополнить — он единственный,
        # кто вообще управляет деньгами, запрещать самому себе смысла нет
        return data
