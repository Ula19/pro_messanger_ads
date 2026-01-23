from drf_spectacular.utils import extend_schema
from rest_framework import generics, status, permissions
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.common.pagination import StandardResultsSetPagination

from apps.billing.models import Balance
from .models import ChatAdOrder, ChatAdMedia
from .serializers import ChatAdMediaSerializer, ChatAdOrderSerializer


class ChatAdMediaUploadView(generics.CreateAPIView):
    """
    Загрузка фото или видео.
    Возвращает UUID файла, который нужно вставить в создание заказа.
    """
    queryset = ChatAdMedia.objects.all()
    serializer_class = ChatAdMediaSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)  # Важно для файлов

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


@extend_schema(responses={
    201: {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
        }
    }
})
class ChatAdOrderCreateView(generics.CreateAPIView):
    """
    Создание заказа и оплата.
    В поле media_id принимаем UUID полученный на прошлом шаге.
    """
    serializer_class = ChatAdOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        user = self.request.user
        budget = serializer.validated_data['budget']

        # Получаем объект медиа из validated_data (валидатор уже вернул объект, а не ID)
        media_obj = serializer.validated_data.pop('media_id', None)

        with transaction.atomic():
            # 1. Списание денег
            balance = Balance.objects.select_for_update().get(user=user)
            if balance.amount < budget:
                raise ValidationError("Недостаточно средств на балансе")
            balance.withdraw(budget)

            # 2. Сохранение заказа
            order = serializer.save(user=user, media_url=media_obj)

            # 3. Помечаем медиа как использованное (чтобы не удалить сборщиком мусора)
            if media_obj:
                media_obj.is_linked = True
                media_obj.save(update_fields=['is_linked'])

    def create(self, request, *args, **kwargs):
        """
        Переопределяем для возврата 201 вместо стандартного 201 с данными
        """
        response = super().create(request, *args, **kwargs)
        return Response({
            'message': 'Канал и заказ успешно созданы',
        }, status=status.HTTP_201_CREATED)


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
    def post(self, request, order_id):
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
