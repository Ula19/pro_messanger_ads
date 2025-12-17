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

from .models import Channel, Order, Tag, Balance
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


from django.db import transaction


class SearchChannelsView(generics.GenericAPIView):
    """Поиск каналов по тегу (двухэтапный: точный + триграммный)"""
    permission_classes = [permissions.AllowAny]
    serializer_class = SearchResultSerializer

    def post(self, request):
        tag = request.data.get('tag', '').strip().lower()

        if not tag:
            return Response(
                {'error': 'Параметр tag обязателен'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # ЭТАП 1: Точный поиск по тегу канала
            channel_with_tag = self._find_channel_by_exact_tag(tag)

            if channel_with_tag:
                # Нашли по точному совпадению - увеличиваем просмотры и возвращаем результат
                return self._process_channel(channel_with_tag, tag, "exact")

            # ЭТАП 2: Триграммный поиск (только если точный не нашел)
            similar_channel = self._find_channel_by_similar_tag(tag)

            if similar_channel:
                # Нашли по триграммному сходству - увеличиваем просмотры и возвращаем результат
                return self._process_channel(similar_channel, tag, "similar")

            # Если оба поиска ничего не нашли
            return Response(
                {'error': 'Канал с таким тегом не найден'},
                status=status.HTTP_404_NOT_FOUND
            )

        except Exception as e:
            return Response(
                {'error': f'Ошибка при поиске: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _process_channel(self, channel, tag, search_type):
        """Обработка найденного канала: увеличение просмотров и возврат результата"""
        try:
            # Находим активный заказ этого канала с максимальным SPM
            active_order = Order.objects.filter(
                channel_id=channel,
                is_active=True,
                cancelled=False,
                remaining_views__gt=0
            ).order_by('-spm').first()

            if not active_order:
                return Response(
                    {'error': f'Нет активной рекламы для канала {channel.channel_name}'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Атомарно увеличиваем счетчик просмотров
            with transaction.atomic():
                # Блокируем запись заказа для избежания гонки
                order = Order.objects.select_for_update().get(pk=active_order.pk)

                if order.remaining_views > 0 and not order.cancelled:
                    # Увеличиваем счетчик просмотров
                    order.decrement_views()  # Этот метод уже уменьшает remaining_views и увеличивает shown_views

                    return Response({
                        'channel_id': channel.channel_id,
                        'channel_name': channel.channel_name,
                        'order_id': order.id,
                    }, status=status.HTTP_200_OK)
                else:
                    # Если лимит исчерпан, деактивируем заказ
                    order.is_active = False
                    order.save()

                    # Пробуем найти другой активный заказ для этого канала
                    other_active_order = Order.objects.filter(
                        channel_id=channel,
                        is_active=True,
                        cancelled=False,
                        remaining_views__gt=0
                    ).order_by('-spm').first()

                    if other_active_order:
                        # Рекурсивно обрабатываем другой заказ
                        return self._process_channel(channel, tag, search_type)

                    return Response(
                        {'error': f'Все заказы для канала {channel.channel_name} исчерпаны'},
                        status=status.HTTP_410_GONE
                    )

        except Exception as e:
            return Response(
                {'error': f'Ошибка при обработке канала: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _find_channel_by_exact_tag(self, tag_name):
        """Поиск канала по точному совпадению тега с максимальным SPM"""
        try:
            # Находим тег по точному совпадению
            tag_obj = Tag.objects.get(name=tag_name)

            # Находим каналы с этим тегом
            channels_with_tag = Channel.objects.filter(tags=tag_obj)

            if not channels_with_tag.exists():
                return None

            # Для каждого канала находим максимальный SPM среди активных заказов
            from django.db.models import Subquery, OuterRef

            # Подзапрос для нахождения максимального SPM среди активных заказов канала
            max_spm_subquery = Order.objects.filter(
                channel_id=OuterRef('pk'),
                is_active=True,
                cancelled=False,
                remaining_views__gt=0
            ).order_by('-spm').values('spm')[:1]

            # Аннотируем каналы максимальным SPM
            channels_annotated = channels_with_tag.annotate(
                max_spm=Subquery(max_spm_subquery)
            ).filter(max_spm__isnull=False).order_by('-max_spm')

            if channels_annotated.exists():
                # Возвращаем канал с максимальным SPM
                return channels_annotated.first()

            return None

        except Tag.DoesNotExist:
            return None

    def _find_channel_by_similar_tag(self, tag_name, threshold=0.3):
        """Поиск канала по триграммному сходству тега"""
        # Находим похожие теги по триграммному сходству
        similar_tags = Tag.find_similar_tags(tag_name, threshold=threshold)

        if not similar_tags.exists():
            return None

        # Берем самый похожий тег
        similar_tag = similar_tags.first()

        # Находим каналы с этим похожим тегом
        channels_with_similar_tag = Channel.objects.filter(tags=similar_tag)

        if not channels_with_similar_tag.exists():
            return None

        # Для каждого канала находим максимальный SPM среди активных заказов
        from django.db.models import Subquery, OuterRef

        # Подзапрос для нахождения максимального SPM
        max_spm_subquery = Order.objects.filter(
            channel_id=OuterRef('pk'),
            is_active=True,
            cancelled=False,
            remaining_views__gt=0
        ).order_by('-spm').values('spm')[:1]

        # Аннотируем каналы максимальным SPM
        channels_annotated = channels_with_similar_tag.annotate(
            max_spm=Subquery(max_spm_subquery)
        ).filter(max_spm__isnull=False).order_by('-max_spm')

        if channels_annotated.exists():
            # Возвращаем канал с максимальным SPM
            return channels_annotated.first()

        return None
