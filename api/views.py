import json
from rest_framework.decorators import api_view, permission_classes
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenVerifyView
from django.db import transaction
from django.db.models import Q, Max, Subquery, OuterRef
from django.contrib.auth import get_user_model
from django.contrib.postgres.search import TrigramSimilarity

from .models import Channel, Order, Tag, Balance, AdView
from .serializers import (
    UserRegistrationSerializer, UserLoginSerializer, ChannelOrderSerializer,
    UserProfileSerializer, OrderSerializer, ChannelStatsSerializer,
    SearchResponseSerializer, OrderListSerializer, BalanceSerializer,
    CancelOrderSerializer, DepositSerializer, SearchResultSerializer
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
    page_size = 5
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


class SearchChannelsView(generics.GenericAPIView):
    """Поиск каналов по тегу с учетом лимита показов на пользователя"""
    serializer_class = SearchResultSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        tag = request.data.get('tag', '').strip().lower()
        viewer_id = request.data.get('viewer_id', '').strip()

        if not tag or not viewer_id:
            return Response(
                {'error': 'Не указаны обязательные параметры: tag и viewer_id'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Пробуем найти подходящий заказ для показа
        result = self._find_suitable_order(tag, viewer_id)

        if result:
            return Response(result, status=status.HTTP_200_OK)
        else:
            return Response(
                {'error': 'Нет доступной рекламы по данному тегу для вашего пользователя'},
                status=status.HTTP_404_NOT_FOUND
            )

    def _find_suitable_order(self, tag_name, viewer_id):
        """Поиск подходящего заказа для показа"""
        # Сначала ищем точное совпадение тега
        try:
            tag_obj = Tag.objects.get(name=tag_name)
            orders = self._get_sorted_orders_by_tag(tag_obj)
            return self._process_orders(orders, viewer_id, "exact")
        except Tag.DoesNotExist:
            pass

        # Если точного тега нет, ищем похожие теги
        similar_tags = Tag.find_similar_tags(tag_name, threshold=0.3)

        for similar_tag in similar_tags:
            orders = self._get_sorted_orders_by_tag(similar_tag)
            result = self._process_orders(orders, viewer_id, "similar")
            if result:
                return result

        return None

    def _get_sorted_orders_by_tag(self, tag_obj):
        """Получает активные заказы с тегом, отсортированные по SPM"""
        return Order.objects.filter(
            tags=tag_obj,
            is_active=True,
            cancelled=False,
            remaining_views__gt=0
        ).select_related('channel_id').order_by('-spm')

    def _process_orders(self, orders, viewer_id, search_type):
        """Обрабатывает список заказов, находит подходящий для показа"""
        for order in orders:
            # Пытаемся показать рекламу
            success = self._try_show_ad_to_user(order, viewer_id)

            if success:
                # Получаем обновленные данные о просмотрах пользователя
                ad_view = AdView.objects.get(order=order, viewer_id=viewer_id)

                return {
                    'channel_id': order.channel_id.channel_id,
                    'channel_name': order.channel_id.channel_name,
                    'order_id': order.id,
                    'spm': order.spm
                }

        return None

    def _try_show_ad_to_user(self, order, viewer_id):
        """Пытается показать рекламу пользователю"""
        try:
            with transaction.atomic():
                # Блокируем заказ для безопасного обновления
                order_lock = Order.objects.select_for_update().get(pk=order.pk)

                # Проверяем, можно ли показывать заказ
                if (order_lock.remaining_views <= 0 or
                        order_lock.cancelled or
                        not order_lock.is_active):
                    return False

                # Получаем или создаем запись о просмотрах пользователя
                ad_view, created = AdView.objects.get_or_create(
                    order=order_lock,
                    viewer_id=viewer_id,
                    defaults={'view_count': 0}
                )

                # Проверяем лимит показов для пользователя
                if ad_view.view_count >= order_lock.max_views_per_user:
                    return False  # Лимит исчерпан

                # Обновляем счетчики заказа
                order_lock.shown_views += 1
                order_lock.remaining_views -= 1

                if order_lock.remaining_views == 0:
                    order_lock.completed = True
                    order_lock.is_active = False

                order_lock.save()

                # Обновляем счетчик просмотров пользователя
                ad_view.view_count += 1
                ad_view.save()

                return True

        except Exception as e:
            print(f"Ошибка при показе рекламы: {e}")
            return False
