from drf_spectacular.utils import extend_schema
from rest_framework import generics, status, permissions
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError

from api.models import Balance
from .models import ChatAdOrder, ChatAdView
from .serializers import ChatAdOrderSerializer, ChatAdViewSerializer
from decimal import Decimal



class StandardResultsSetPagination(PageNumberPagination):
    """Пагинация для списков"""
    page_size = 5
    page_size_query_param = 'page_size'
    max_page_size = 100


class ChatAdOrderCreateView(generics.CreateAPIView):
    """Создание рекламы в чатах"""
    queryset = ChatAdOrder.objects.all().select_related('user')
    serializer_class = ChatAdOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        budget = serializer.validated_data['budget']
        user = self.request.user

        # Открываем транзакцию: всё или ничего
        with transaction.atomic():
            # 1. Получаем баланс с блокировкой строки (защита от двойного списания)
            balance = Balance.objects.select_for_update().get(user=user)

            # 2. Проверяем средства
            if balance.amount < budget:
                raise ValidationError("Недостаточно средств на балансе")

            # 3. Списываем средства
            balance.withdraw(budget)

            # 4. Создаем заказ
            serializer.save(user=user)


class ChatAdOrderListView(generics.ListAPIView):
    serializer_class = ChatAdOrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        # Возвращаем заказы текущего пользователя
        return ChatAdOrder.objects.filter(user=self.request.user).select_related('user')


class ChatAdOrderDetailView(generics.RetrieveAPIView):
    """
    Получение детальной информации о рекламе в чате.
    GET /api/chat_post/orders/{order_id}/
    """
    serializer_class = ChatAdOrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'order_id'

    def get_queryset(self):
        """
        Возвращаем только заказы текущего пользователя
        """
        return ChatAdOrder.objects.filter(user=self.request.user).select_related('user')


class ChatAdActiveOrderListView(generics.ListAPIView):
    """Получение активных заказов текущего пользователя"""
    serializer_class = ChatAdOrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        # Возвращаем активные заказы текущего пользователя (не отмененные, есть остаток просмотров)
        return ChatAdOrder.objects.filter(
            user=self.request.user,
            is_active=True,
            cancelled=False,
            remaining_views__gt=0
        ).select_related('user')


class ChatAdCancelOrderView(generics.GenericAPIView):
    """Отмена заказа по ID в URL"""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def get(self, request, order_id):
        """
        Отменяет заказ пользователя.
        Получает order_id из параметра пути URL.
        """
        try:
            with transaction.atomic():
                order = ChatAdOrder.objects.select_for_update().get(order_id=order_id, user=request.user)

                validation_error = self._validate_order_for_cancellation(order)
                if validation_error:
                    return Response(
                        {'error': validation_error},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                refund_amount = order.cancel_order()

            return Response(status=status.HTTP_204_NO_CONTENT)

        except ChatAdOrder.DoesNotExist:
            return Response(
                {'error': 'Заказ не найден или у вас нет прав на его отмену.'},
                status=status.HTTP_404_NOT_FOUND
            )

    def _validate_order_for_cancellation(self, order):
        """Проверяет, можно ли отменить заказ."""
        if order.cancelled:
            return 'Заказ уже отменен.'
        if order.completed:
            return 'Нельзя отменить завершенный заказ.'
        return None
