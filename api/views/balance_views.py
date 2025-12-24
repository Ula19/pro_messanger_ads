from rest_framework import generics, permissions, status
from rest_framework.response import Response
from django.contrib.auth import get_user_model

from api.models import Balance

from api.serializer.balance_serializer import BalanceSerializer, DepositSerializer, AdminDepositSerializer


User = get_user_model()


class BalanceView(generics.RetrieveAPIView):
    """Получение баланса текущего пользователя"""
    serializer_class = BalanceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        user = self.request.user
        balance, created = Balance.objects.get_or_create(user=user)
        return balance


class DepositView(generics.GenericAPIView):
    """Пополнение баланса"""
    serializer_class = DepositSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        amount = serializer.validated_data['amount']
        user = request.user

        # Получаем или создаем баланс
        balance, created = Balance.objects.get_or_create(user=user)

        # Пополняем баланс
        balance.deposit(amount)

        return Response({
            'message': f'Баланс успешно пополнен на {amount}',
            'new_balance': balance.amount
        }, status=status.HTTP_200_OK)


class AdminDepositView(generics.GenericAPIView):
    """
    Пополнение баланса пользователя администратором.
    Только пользователи с is_admin=True могут использовать этот эндпоинт.
    """
    serializer_class = AdminDepositSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """
        Пополняет баланс указанного пользователя
        """
        # Проверяем, является ли текущий пользователь администратором
        if not request.user.is_admin:
            return Response(
                {'error': 'У вас нет прав для выполнения этой операции'},
                status=status.HTTP_403_FORBIDDEN
            )

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
                'old_balance': balance.amount - amount,
                'new_balance': balance.amount,
                'added_amount': amount
            }
        }, status=status.HTTP_200_OK)
