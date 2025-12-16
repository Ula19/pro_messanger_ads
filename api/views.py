import json
from django.db.models import Q, Max
from rest_framework.decorators import api_view, permission_classes
from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenVerifyView
from django.contrib.auth import get_user_model

from .models import Channel, Order, Tag, Balance
from .serializers import (
    UserRegistrationSerializer, UserLoginSerializer, ChannelOrderSerializer,
    UserProfileSerializer, OrderSerializer, ChannelStatsSerializer,
    SearchResponseSerializer, OrderListSerializer, BalanceSerializer,
    CancelOrderSerializer, DepositSerializer
)

User = get_user_model()


class UserRegistrationView(generics.CreateAPIView):
    """Регистрация нового пользователя"""
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]


class UserLoginView(TokenObtainPairView):
    """Вход пользователя"""
    serializer_class = UserLoginSerializer
    permission_classes = [permissions.AllowAny]


class UserProfileView(generics.RetrieveAPIView):
    """Получение профиля текущего пользователя"""
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class UserTokenVerifyView(TokenVerifyView):
    def post(self, request: Request, *args, **kwargs) -> Response:
        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            response.data['status'] = 'success'

        return response


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


class CreateChannelOrderView(generics.CreateAPIView):
    """Создание канала и заказа в одном запросе"""
    serializer_class = ChannelOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Добавляем пользователя в контекст
        serializer.context['request'] = request
        result = serializer.save()

        return Response({
            'message': 'Канал и заказ успешно созданы',
            'channel': result['channel'],
            'order': result['order']
        }, status=status.HTTP_201_CREATED)


class SearchChannelsView(generics.GenericAPIView):
    """Поиск каналов по тегу и показ рекламы"""
    permission_classes = [permissions.AllowAny]
    serializer_class = SearchResponseSerializer

    def get(self, request):
        tag = request.query_params.get('tag', '').strip().lower()

        if not tag:
            return Response(
                {'error': 'Параметр tag обязателен'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Получаем тег из базы
            tag_obj = Tag.objects.get(name=tag)

            # Находим активные заказы с указанным тегом (не отмененные)
            active_orders = Order.objects.filter(
                is_active=True,
                cancelled=False,
                remaining_views__gt=0,
                tags=tag_obj
            ).select_related('channel_id').prefetch_related('tags')

            if not active_orders.exists():
                return Response(
                    {'message': 'Нет активной рекламы для данного тега'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Находим заказ с максимальным SPM
            best_order = active_orders.order_by('-spm').first()

            # Атомарно уменьшаем счетчик показов
            with transaction.atomic():
                order = Order.objects.select_for_update().get(pk=best_order.pk)

                if order.remaining_views > 0 and not order.cancelled:
                    order.decrement_views()

                    # Подготавливаем данные для ответа
                    channel_data = {
                        'channel_id': order.channel_id.channel_id,
                        'channel_name': order.channel_id.channel_name,
                        'tags': [tag.name for tag in order.channel_id.tags.all()],
                        'order_name': order.order_name,
                        'spm': float(order.spm),
                        'remaining_views': order.remaining_views,
                        'shown_views': order.shown_views,
                        'is_active': order.is_active,
                        'cancelled': order.cancelled
                    }

                    # Создаем данные для сериализатора
                    response_data = {
                        'message': 'Реклама показана успешно',
                        'channel': channel_data,
                        'remaining_views': order.remaining_views
                    }

                    serializer = self.get_serializer(response_data)
                    return Response(serializer.data)
                else:
                    order.is_active = False
                    order.save()
                    return Response(
                        {'message': 'Лимит показов исчерпан или реклама отменена'},
                        status=status.HTTP_410_GONE
                    )

        except Tag.DoesNotExist:
            return Response(
                {'message': 'Тег не найден'},
                status=status.HTTP_404_NOT_FOUND
            )


class CancelOrderView(generics.GenericAPIView):
    """Отмена заказа и возврат средств"""
    serializer_class = CancelOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, order_id):
        try:
            # Получаем заказ пользователя
            order = Order.objects.get(id=order_id, user=request.user)

            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            # Отменяем заказ и получаем сумму возврата
            refund_amount = order.cancel_order()

            return Response({
                'message': 'Заказ успешно отменен',
                'refund_amount': refund_amount,
                'new_balance': request.user.balance.amount,
                'order_status': {
                    'cancelled': order.cancelled,
                    'is_active': order.is_active,
                    'remaining_views': order.remaining_views
                }
            }, status=status.HTTP_200_OK)

        except Order.DoesNotExist:
            return Response(
                {'error': 'Заказ не найден или у вас нет прав на его отмену'},
                status=status.HTTP_404_NOT_FOUND
            )


class ChannelStatsView(generics.RetrieveAPIView):
    """Получение статистики по каналу"""
    serializer_class = ChannelStatsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, channel_id):
        try:
            channel = Channel.objects.prefetch_related('tags').get(
                channel_id=channel_id,
                user=request.user
            )

            orders = Order.objects.filter(
                channel_id=channel
            ).prefetch_related('tags')

            total_views = sum(order.total_views for order in orders)
            active_orders = orders.filter(is_active=True, cancelled=False, remaining_views__gt=0).count()
            total_spent = sum(float(order.budget) for order in orders)

            channel_tags = [tag.name for tag in channel.tags.all()]

            data = {
                'channel_name': channel.channel_name,
                'total_orders': orders.count(),
                'active_orders': active_orders,
                'total_views_purchased': total_views,
                'total_budget_spent': total_spent,
                'tags': channel_tags,
                'orders': orders
            }

            serializer = self.get_serializer(data)
            return Response(serializer.data)

        except Channel.DoesNotExist:
            return Response(
                {'error': 'Канал не найден'},
                status=status.HTTP_404_NOT_FOUND
            )


class StandardResultsSetPagination(PageNumberPagination):
    """Пагинация для списков"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class OrderListView(generics.ListAPIView):
    """Получение всех заказов текущего пользователя"""
    serializer_class = OrderListSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        # Возвращаем заказы текущего пользователя
        return Order.objects.filter(
            user=self.request.user
        ).select_related('channel_id').prefetch_related('tags', 'channel_id__tags')


class ActiveOrderListView(generics.ListAPIView):
    """Получение активных заказов текущего пользователя"""
    serializer_class = OrderListSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        # Возвращаем активные заказы текущего пользователя (не отмененные, есть остаток просмотров)
        return Order.objects.filter(
            user=self.request.user,
            is_active=True,
            cancelled=False,
            remaining_views__gt=0
        ).select_related('channel_id').prefetch_related('tags', 'channel_id__tags')


class ChannelOrderListView(generics.ListAPIView):
    """Получение заказов по конкретному каналу"""
    serializer_class = OrderListSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        channel_id = self.kwargs['channel_id']

        # Проверяем, что канал принадлежит пользователю
        try:
            channel = Channel.objects.get(
                channel_id=channel_id,
                user=self.request.user
            )
        except Channel.DoesNotExist:
            return Order.objects.none()

        # Возвращаем заказы этого канала
        return Order.objects.filter(
            channel_id=channel
        ).select_related('channel_id').prefetch_related('tags', 'channel_id__tags')
