from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from django.contrib.auth import get_user_model

from apps.common.permissions import IsSuperAdmin
from apps.billing.models import Balance
from apps.billing.serializers import BalanceSerializer, AdminDepositSerializer


User = get_user_model()


class BalanceView(generics.RetrieveAPIView):
    """Получение баланса текущего пользователя"""
    serializer_class = BalanceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        user = self.request.user
        balance, created = Balance.objects.get_or_create(user=user)
        return balance


class AdminDepositView(generics.GenericAPIView):
    """
    Пополнение баланса пользователя.
    Доступно только суперадмину — больше никто пополнять балансы не вправе.
    """
    serializer_class = AdminDepositSerializer
    permission_classes = [IsSuperAdmin]

    @extend_schema(request=AdminDepositSerializer, responses={
        200: {
            'type': 'object',
            'properties': {
                'message': {'type': 'string'},
                'user_info': {
                    'type': 'object',
                    'properties': {
                        'user_id': {'type': 'string', 'format': 'uuid'},
                        'username': {'type': 'string'},
                        'email': {'type': 'string'},
                    },
                },
                'balance_info': {
                    'type': 'object',
                    'properties': {
                        'old_balance': {'type': 'string', 'format': 'decimal'},
                        'new_balance': {'type': 'string', 'format': 'decimal'},
                        'added_amount': {'type': 'string', 'format': 'decimal'},
                    },
                },
            },
        },
    })
    def post(self, request):
        """
        Пополняет баланс указанного пользователя.
        Доступно только суперадмину — больше никто пополнять балансы не вправе.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']
        amount = serializer.validated_data['amount']

        # Получаем или создаем баланс пользователя
        balance, created = Balance.objects.get_or_create(user=user)

        # Пополняем баланс
        balance.deposit(amount)

        return Response({
            'message': f'Баланс пользователя {user.username} успешно пополнен на {amount}',
            'user_info': {
                'user_id': str(user.user_id),
                'username': user.username,
                'email': user.email
            },
            'balance_info': {
                # строками — как amount в /api/balance/ (Decimal в JSON иначе стал бы float)
                'old_balance': str(balance.amount - amount),
                'new_balance': str(balance.amount),
                'added_amount': str(amount)
            }
        }, status=status.HTTP_200_OK)
