import json

from django.http import Http404
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
    UserProfileSerializer, OrderSerializer,
    OrderListSerializer, BalanceSerializer, CancelOrderSerializer,
    DepositSerializer, SearchResultSerializer, OrderActivationSerializer,
    OrderDetailSerializer, SearchRequestSerializer
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
        }, status=status.HTTP_201_CREATED)


class CancelOrderView(generics.GenericAPIView):
    """Отмена заказа по ID в URL"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, order_id):
        """
        Отменяет заказ пользователя.
        Получает order_id из параметра пути URL.
        """
        try:
            # Все операции с базой данных, включая выборку с блокировкой и обновление,
            # должны быть внутри ОДНОЙ транзакции.
            with transaction.atomic():
                # 1. Находим заказ и проверяем права доступа
                # select_for_update() блокирует строку заказа для других транзакций,
                # что гарантирует целостность при конкурентном доступе.
                order = Order.objects.select_for_update().get(id=order_id, user=request.user)

                # 2. Валидация состояния заказа перед отменой
                validation_error = self._validate_order_for_cancellation(order)
                if validation_error:
                    # Если валидация не прошла, транзакция откатится сама
                    return Response(
                        {'error': validation_error},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # 3. Выполняем отмену. Метод cancel_order() вызывает order.save()
                refund_amount = order.cancel_order()

            # 4. Возвращаем успешный ответ ВНЕ транзакции
            return Response({
                'message': 'Заказ успешно отменен.',
                'refund_amount': refund_amount,
                'new_balance': request.user.balance.amount,
                'order_status': {
                    'id': order.id,
                    'order_name': order.order_name,
                    'cancelled': order.cancelled,
                    'is_active': order.is_active,
                    'remaining_views': order.remaining_views
                }
            }, status=status.HTTP_200_OK)

        except Order.DoesNotExist:
            # Этот блок находится вне транзакции, так как исключение выбрасывается при запросе
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


class StandardResultsSetPagination(PageNumberPagination):
    """Пагинация для списков"""
    page_size = 5
    page_size_query_param = 'page_size'
    max_page_size = 100


class OrderListView(generics.ListAPIView):
    """Получение всех заказов текущего пользователя"""
    # serializer_class = OrderListSerializer  # Пусть пока постоит. Сейчас OrderListSerializer делает тоже самое
    # что и OrderDetailSerializer
    serializer_class = OrderDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        # Возвращаем заказы текущего пользователя
        return Order.objects.filter(
            user=self.request.user
        ).select_related('channel_id').prefetch_related('tags', 'channel_id__tags')


class OrderDetailView(generics.RetrieveAPIView):
    """
    Получение детальной информации о заказе.
    GET /api/orders/{order_id}/
    """
    serializer_class = OrderDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Возвращаем только заказы текущего пользователя
        с оптимизацией запросов для тегов
        """
        return Order.objects.filter(
            user=self.request.user
        ).select_related('channel_id').prefetch_related('tags')

    def get_object(self):
        """
        Получаем объект заказа с проверкой прав доступа
        """
        queryset = self.get_queryset()

        try:
            order_id = self.kwargs['order_id']
            obj = queryset.get(id=order_id)
            return obj
        except Order.DoesNotExist:
            # Возвращаем 404 с понятным сообщением
            raise Http404("Заказ не найден или у вас нет прав на его просмотр")

    def retrieve(self, request, *args, **kwargs):
        """
        Переопределяем для кастомизации ответа при ошибке
        """
        try:
            return super().retrieve(request, *args, **kwargs)
        except Http404 as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_404_NOT_FOUND
            )


class OrderActivationView(generics.GenericAPIView):
    """
    Активация/деактивация заказа по ID
    Получает order_id и is_active в теле POST запроса
    """
    serializer_class = OrderActivationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """
        Обработка POST запроса для активации/деактивации заказа
        """
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        # Получаем данные из сериализатора
        order = serializer.validated_data['order']
        is_active = serializer.validated_data['is_active']

        # Если есть warning (например, статус уже такой же), возвращаем его
        if 'warning' in serializer.validated_data:
            return Response({
                'message': serializer.validated_data['warning'],
                'order_id': order.id,
                'current_status': order.is_active,
                'requested_status': is_active
            }, status=status.HTTP_200_OK)

        # Используем атомарную транзакцию для безопасности
        with transaction.atomic():
            # Блокируем заказ для предотвращения race conditions
            locked_order = Order.objects.select_for_update().get(id=order.id)

            # Сохраняем старый статус
            old_status = locked_order.is_active

            # Обновляем статус
            locked_order.is_active = is_active

            # Дополнительная логика при активации
            if is_active:
                # Проверяем, не израсходованы ли все просмотры
                if locked_order.remaining_views <= 0:
                    return Response({
                        'error': 'Невозможно активировать заказ: все просмотры израсходованы'
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Если заказ был деактивирован, но не завершен и не отменен
                # Убедимся, что completed установлен правильно
                if locked_order.remaining_views == 0 and not locked_order.completed:
                    locked_order.completed = True
                    locked_order.is_active = False

            # При деактивации просто меняем статус
            # Заказ уже проверен на отмену и завершение в сериализаторе

            locked_order.save()

        # Формируем ответ
        response_data = {
            'message': f'Статус заказа успешно изменен с {old_status} на {is_active}',
            'order': {
                'id': order.id,
                'channel_name': order.channel_name,
                'order_name': order.order_name,
                'is_active': order.is_active,
                'remaining_views': order.remaining_views,
                'completed': order.completed,
                'cancelled': order.cancelled,
            }
        }

        return Response(response_data, status=status.HTTP_200_OK)


class ActiveOrderListView(generics.ListAPIView):
    """Получение активных заказов текущего пользователя"""
    # serializer_class = OrderListSerializer # Пусть пока постоит. Сейчас OrderListSerializer делает тоже самое
    # что и OrderDetailSerializer
    serializer_class = OrderDetailSerializer
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


class SearchChannelsView(generics.GenericAPIView):
    """Поиск каналов по тегу с учетом лимита показов на пользователя"""
    # Указываем сериализатор для документации Swagger (если используется)
    serializer_class = SearchRequestSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # 1. Валидация входных данных с помощью SearchRequestSerializer
        request_serializer = SearchRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(
                {'error': 'Неверные входные данные', 'details': request_serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        tag = request_serializer.validated_data['tag'].strip().lower()
        viewer_id = request_serializer.validated_data['viewer_id'].strip()

        # 2. Пробуем найти подходящий заказ для показа
        result = self._find_suitable_order(tag, viewer_id)

        if result:
            # 3. Сериализуем результат с помощью SearchResultSerializer
            result_serializer = SearchResultSerializer(data=result)
            result_serializer.is_valid(raise_exception=True)  # Гарантируем корректность данных
            return Response(result_serializer.data, status=status.HTTP_200_OK)
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
                # Подготавливаем данные для SearchResultSerializer
                # Приводим order.id к строке, так как в сериализаторе это CharField
                return {
                    'channel_id': order.channel_id.channel_id,
                    'channel_name': order.channel_id.channel_name,
                    'order_id': order.id,
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
