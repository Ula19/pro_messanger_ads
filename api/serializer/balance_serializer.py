from decimal import Decimal
from rest_framework import serializers
from django.contrib.auth import get_user_model

from api.models import Balance

User = get_user_model()


class BalanceSerializer(serializers.ModelSerializer):
    """Сериализатор для баланса"""
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = Balance
        fields = ['username', 'amount',]
        read_only_fields = ['user', 'username']


class DepositSerializer(serializers.Serializer):
    """Сериализатор для пополнения баланса"""
    amount = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        required=True,
        min_value=Decimal('0.01')
    )

    def validate(self, data):
        if data['amount'] <= 0:
            raise serializers.ValidationError({"amount": "Сумма должна быть больше 0"})
        return data


class AdminDepositSerializer(serializers.Serializer):
    """Сериализатор для пополнения баланса администратором"""
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

        # Проверяем, что пользователь не пополняет свой баланс
        # (если нужно разрешить пополнение своего баланса админом, удалите эту проверку)
        request = self.context.get('request')
        if request and request.user.user_id == user_id:
            raise serializers.ValidationError({
                "user_id": "Администратор не может пополнять свой собственный баланс через этот эндпоинт"
            })

        return data
