from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.models import ModerationStatus
from apps.common.pagination import StandardResultsSetPagination
from apps.common.permissions import IsModerator
from apps.search_ads.models import Order
from apps.chat_ads.models import ChatAdOrder

from .serializers import (ModerationSearchOrderSerializer, ModerationChatOrderSerializer,
                          ModerationDecisionSerializer)


# Тип заказа приходит строкой в URL — маппим её на модель
ORDER_MODELS = {
    'search_ads': Order,
    'chat_ads': ChatAdOrder,
}


class PendingSearchAdsListView(generics.ListAPIView):
    """Очередь модерации: заказы поисковой рекламы на проверке (старые первыми)"""
    serializer_class = ModerationSearchOrderSerializer
    permission_classes = [IsModerator]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        # cancelled=False: юзер мог отменить заказ, не дождавшись проверки —
        # такому решение уже не нужно, в очереди ему делать нечего
        return (Order.objects.filter(status=ModerationStatus.PENDING, cancelled=False)
                .select_related('channel_id', 'user')
                .prefetch_related('tags')
                .order_by('created_at'))


class PendingChatAdsListView(generics.ListAPIView):
    """Очередь модерации: заказы рекламы в чатах на проверке (старые первыми)"""
    serializer_class = ModerationChatOrderSerializer
    permission_classes = [IsModerator]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        # cancelled=False: отменённые юзером заказы в очереди не показываем
        return (ChatAdOrder.objects.filter(status=ModerationStatus.PENDING, cancelled=False)
                .select_related('user', 'media_url')
                .order_by('created_at'))


class PendingCountView(APIView):
    """Счётчик заказов на модерации — для бейджа в интерфейсе модератора (фронт поллит)"""
    permission_classes = [IsModerator]

    @extend_schema(responses={
        200: {
            "type": "object",
            "properties": {
                "search_ads": {"type": "integer"},
                "chat_ads": {"type": "integer"},
                "total": {"type": "integer"},
            }
        }
    })
    def get(self, request):
        search_count = Order.objects.filter(status=ModerationStatus.PENDING, cancelled=False).count()
        chat_count = ChatAdOrder.objects.filter(status=ModerationStatus.PENDING, cancelled=False).count()
        return Response({
            'search_ads': search_count,
            'chat_ads': chat_count,
            'total': search_count + chat_count,
        }, status=status.HTTP_200_OK)


class ModerationDecisionView(generics.GenericAPIView):
    """
    Решение модератора по заказу: approve (одобрить), reject (отклонить с полным
    возвратом денег), block (заблокировать за нарушение с возвратом остатка).
    Действие и тип заказа приходят из URL.
    """
    serializer_class = ModerationDecisionSerializer
    permission_classes = [IsModerator]

    @extend_schema(
        request=ModerationDecisionSerializer,
        responses={
            200: {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "order_id": {"type": "string", "format": "uuid"},
                    "status": {"type": "string"},
                    "refund_amount": {"type": "string"},
                }
            }
        }
    )
    def post(self, request, order_type, order_id, action):
        model = ORDER_MODELS.get(order_type)
        if model is None:
            return Response({'error': 'Неизвестный тип заказа'}, status=status.HTTP_404_NOT_FOUND)

        # Валидируем причину (для reject/block она обязательна)
        serializer = ModerationDecisionSerializer(data=request.data, context={'action': action})
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get('reason', '').strip()

        try:
            with transaction.atomic():
                # Лок на строку заказа: два модератора не примут решение одновременно,
                # а возврат денег посчитается от свежего остатка показов
                order = model.objects.select_for_update().get(order_id=order_id)

                # Модератор не может модерировать собственную рекламу (суперадмин может)
                if order.user_id == request.user.id and not request.user.is_superuser:
                    return Response({'error': 'Нельзя модерировать собственный заказ'},
                                    status=status.HTTP_403_FORBIDDEN)

                refund_amount = None
                if action == 'approve':
                    result = order.approve(request.user)
                elif action == 'reject':
                    result = refund_amount = order.reject(request.user, reason)
                else:  # block
                    result = refund_amount = order.block(request.user, reason)
        except model.DoesNotExist:
            return Response({'error': 'Заказ не найден'}, status=status.HTTP_404_NOT_FOUND)

        # False/None — метод модели отказал: заказ уже не в том статусе или отменён
        if result is False or result is None:
            return Response({
                'error': f'Действие недоступно: заказ в статусе «{order.get_status_display()}»'
                         + (' и отменён пользователем' if order.cancelled else '')
            }, status=status.HTTP_409_CONFLICT)

        messages = {
            'approve': 'Заказ одобрен и активирован',
            'reject': 'Заказ отклонён, деньги возвращены пользователю',
            'block': 'Заказ заблокирован, остаток бюджета возвращён пользователю',
        }
        response_data = {
            'message': messages[action],
            'order_id': str(order_id),
            'status': order.status,
        }
        if refund_amount is not None:
            response_data['refund_amount'] = str(refund_amount)

        return Response(response_data, status=status.HTTP_200_OK)
