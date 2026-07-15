from django.db.models import F
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from django.http import Http404
from django.db import transaction
from rest_framework.views import APIView

from apps.common.models import ModerationStatus
from apps.common.pagination import StandardResultsSetPagination
from apps.common.permissions import HasServerApiKey

from .models import Order, Tag, AdView
from .serializers import (CreateChannelOrderSerializer, ResponsesMessageSerializer, OrderDetailSerializer,
                                         OrderActivationSerializer, SearchRequestSerializer, SearchResultSerializer,
                                         ClickOrderSerializer)


class CreateChannelOrderView(generics.CreateAPIView):
    """Создание канала и заказа в одном запросе"""
    serializer_class = CreateChannelOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=CreateChannelOrderSerializer, responses=ResponsesMessageSerializer)
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Добавляем пользователя в контекст
        serializer.context['request'] = request
        result = serializer.save()

        response_data = {'message': 'Канал и заказ успешно созданы'}
        response_serializer = ResponsesMessageSerializer(data=response_data)
        response_serializer.is_valid(raise_exception=True)

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class CancelOrderView(generics.GenericAPIView):
    """Отмена заказа по ID"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ResponsesMessageSerializer

    @extend_schema(request=None, responses=ResponsesMessageSerializer)
    def post(self, request, order_id):
        try:
            with transaction.atomic():
                # select_for_update блокирует строку до конца транзакции
                order = Order.objects.select_for_update().get(order_id=order_id, user=request.user)

                if order.cancelled:
                    return Response({'error': 'Заказ уже отменен.'}, status=400)
                if order.completed:
                    return Response({'error': 'Нельзя отменить завершенный заказ.'}, status=400)
                # По отклонённому/заблокированному заказу деньги уже вернули при модерации
                if order.status in (ModerationStatus.REJECTED, ModerationStatus.BLOCKED):
                    return Response({'error': 'Заказ отклонён или заблокирован, средства уже возвращены.'}, status=400)

                order.cancel_order() # Метод модели

            return Response({'message': 'Ордер отменен'}, status=status.HTTP_200_OK)

        except Order.DoesNotExist:
            return Response(
                {'error': 'Заказ не найден или у вас нет прав.'},
                status=status.HTTP_404_NOT_FOUND
            )


class OrderListView(generics.ListAPIView):
    """Получение всех заказов текущего пользователя"""
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
    GET /api/orders/{order_id}/detail/
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
            obj = queryset.get(order_id=order_id)
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

    @extend_schema(request=OrderActivationSerializer, responses=ResponsesMessageSerializer)
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
                'order_id': order.order_id,
                'current_status': order.is_active,
                'requested_status': is_active
            }, status=status.HTTP_200_OK)

        # Используем атомарную транзакцию для безопасности
        with transaction.atomic():
            # Блокируем заказ для предотвращения race conditions
            locked_order = Order.objects.select_for_update().get(order_id=order.order_id)

            # Повторная проверка под локом: пока запрос шёл, модератор мог
            # заблокировать заказ — не даём юзеру реанимировать его
            if locked_order.status != ModerationStatus.APPROVED or locked_order.cancelled or locked_order.completed:
                return Response({
                    'error': 'Заказ нельзя включить/выключить: он не одобрен, отменён или завершён'
                }, status=status.HTTP_400_BAD_REQUEST)

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

        response_data = {'message': f'Статус заказа успешно изменен с "{old_status}" на "{is_active}"'}
        response_serializer = ResponsesMessageSerializer(data=response_data)
        response_serializer.is_valid(raise_exception=True)

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class ActiveOrderListView(generics.ListAPIView):
    """Получение активных заказов текущего пользователя"""
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



# =========

class SearchChannelsView(generics.GenericAPIView):
    """Поиск каналов по тегу с учетом лимита показов на пользователя"""
    serializer_class = SearchRequestSerializer
    permission_classes = [HasServerApiKey]  # только запросы с сервера NovaGram (по API-ключу)
    throttle_classes = []  # доверенный сервер (server-to-server), глобальный троттл 500/min тут не нужен

    @extend_schema(request=SearchRequestSerializer, responses=SearchResultSerializer)
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
            result_serializer.is_valid(raise_exception=True)
            return Response(result_serializer.data, status=status.HTTP_200_OK)
        else:
            return Response(
                {'error': 'Нет доступной рекламы по данному тегу для вашего пользователя'},
                status=status.HTTP_404_NOT_FOUND
            )

    def _find_suitable_order(self, tag_name, viewer_id):
        """Поиск подходящего заказа для показа по точному совпадению тега"""
        try:
            # Ищем точное совпадение тега
            tag_obj = Tag.objects.get(name=tag_name)
            orders = self._get_sorted_orders_by_tag(tag_obj)
            return self._process_orders(orders, viewer_id)
        except Tag.DoesNotExist:
            # Если тег не найден - сразу возвращаем None
            return None

    def _get_sorted_orders_by_tag(self, tag_obj):
        """Получает активные одобренные заказы с тегом, отсортированные по SPM"""
        return Order.objects.filter(
            tags=tag_obj,
            status=ModerationStatus.APPROVED,  # показываем только прошедшее модерацию
            is_active=True,
            cancelled=False,
            remaining_views__gt=0
        ).select_related('channel_id').order_by('-spm')

    def _process_orders(self, orders, viewer_id):
        """Обрабатывает список заказов, находит подходящий для показа"""
        for order in orders:
            # Пытаемся показать рекламу
            success = self._try_show_ad_to_user(order, viewer_id)

            if success:
                # Подготавливаем данные для SearchResultSerializer
                return {
                    'channel_id': order.channel_id.channel_id,
                    'channel_name': order.channel_id.channel_name,
                    'order_id': order.order_id,
                    'platform': order.platform
                }

        return None

    def _try_show_ad_to_user(self, order, viewer_id):
        """
        Пытается показать рекламу пользователю (атомарно, без блокировки всего заказа).

        Лок берём только на строку показа пары «заказ+зритель» (низкая конкуренция) —
        этого хватает, чтобы лимит показов на пользователя не гонялся. Бюджет заказа
        списываем условным UPDATE: WHERE отсекает гонку, лок на строку заказа держится
        доли мс, поэтому популярная реклама не выстраивает всех в очередь.
        """
        try:
            with transaction.atomic():
                ad_view, _ = AdView.objects.get_or_create(
                    order=order, viewer_id=viewer_id, defaults={'view_count': 0}
                )
                ad_view = AdView.objects.select_for_update().get(pk=ad_view.pk)

                # Лимит показов на пользователя — не тратим бюджет, если он уже исчерпан.
                if ad_view.view_count >= order.max_views_per_user:
                    return False

                # Атомарно списываем один показ из бюджета (условие в WHERE — защита от гонки).
                updated = Order.objects.filter(
                    order_id=order.order_id, remaining_views__gt=0,
                    status=ModerationStatus.APPROVED,
                    is_active=True, cancelled=False
                ).update(
                    remaining_views=F('remaining_views') - 1,
                    shown_views=F('shown_views') + 1,
                )
                if not updated:
                    return False  # бюджет кончился или заказ выключили/отменили

                # Показы исчерпаны -> помечаем заказ завершённым (точечный дешёвый апдейт).
                Order.objects.filter(order_id=order.order_id, remaining_views=0).update(
                    completed=True, is_active=False
                )

                # Фиксируем показ этому пользователю.
                ad_view.view_count += 1
                ad_view.save(update_fields=['view_count', 'last_viewed_at'])
                return True

        except Exception as e:
            print(f"Ошибка при показе рекламы: {e}")
            return False


class ClickView(APIView):
    """
    Увеличивает счетчик кликов у объявления.
    """
    permission_classes = [HasServerApiKey]  # только запросы с сервера NovaGram (по API-ключу)
    throttle_classes = []  # доверенный сервер, глобальный троттл тут не нужен
    serializer_class = ClickOrderSerializer

    @extend_schema(request=ClickOrderSerializer, responses=ResponsesMessageSerializer)
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 1. Забираем уже найденный объект из сериализатора
        order = serializer.validated_data['order_object']

        # 2. Атомарное обновление (защита от гонки данных)
        # Мы НЕ пишем order.clicks += 1, мы даем инструкцию базе данных
        order.clicks = F('clicks') + 1

        # 3. Сохраняем ТОЛЬКО поле clicks, не трогая остальные
        order.updated_at = timezone.now()
        order.save(update_fields=['clicks', 'updated_at'])

        response_data = {'message': 'Пользователь перешел по рекламе. (Кликнул по рекламе)'}
        response_serializer = ResponsesMessageSerializer(data=response_data)
        response_serializer.is_valid(raise_exception=True)

        return Response(response_serializer.data, status=status.HTTP_200_OK)
