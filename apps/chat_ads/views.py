from drf_spectacular.utils import extend_schema
from rest_framework import generics, status, permissions
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.common.pagination import StandardResultsSetPagination

from apps.billing.models import Balance
from .models import ChatAdOrder, ChatAdMedia, ChatAdView
from .serializers import ChatAdMediaSerializer, ChatAdOrderSerializer, ChatAdOrderActivationSerializer, \
    ChatAdResponsesMessageSerializer, AdRequestSerializer, ChatAdPublicSerializer


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


@extend_schema(request=ChatAdOrderSerializer, responses=ChatAdResponsesMessageSerializer)
class ChatAdOrderCreateView(generics.CreateAPIView):
    """
    Создание заказа и оплата.
    В поле media_id принимаем UUID медиафайла
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

        response_data = {'message': 'Канал и заказ успешно созданы'}
        response_serializer = ChatAdResponsesMessageSerializer(data=response_data)
        response_serializer.is_valid(raise_exception=True)

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


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

    @extend_schema(request=None, responses={204: None})
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


class OrderActivationView(generics.GenericAPIView):
    """
    Активация/деактивация заказа по ID
    Получает order_id и is_active в теле POST запроса
    """
    serializer_class = ChatAdOrderActivationSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=ChatAdOrderActivationSerializer, responses=ChatAdResponsesMessageSerializer)
    def post(self, request, *args, **kwargs):
        # Передаем request в контекст, чтобы сериализатор видел request.user
        serializer = self.get_serializer(data=request.data)

        # Запуск валидации (если ошибка, вернет 400 Bad Request)
        serializer.is_valid(raise_exception=True)

        # Запуск сохранения (транзакции)
        updated_order = serializer.save()

        response_data = {'message': f'Статус заказа успешно обновлен.'}

        response_serializer = ChatAdResponsesMessageSerializer(data=response_data)
        response_serializer.is_valid(raise_exception=True)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class GetChatAdView(APIView):
    """
    Эндпоинт для получения рекламы в чате.
    POST /api/ads/get/
    Body: {"channel_name": "news_channel", "viewer_id": "user_123"}
    """
    serializer_class = AdRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=AdRequestSerializer, responses=ChatAdPublicSerializer)
    def post(self, request):
        # 1. Валидация входных данных
        input_serializer = self.serializer_class(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        channel_name = input_serializer.validated_data['channel_name']
        viewer_id = input_serializer.validated_data['viewer_id']

        # 2. Поиск кандидатов (Грубая фильтрация)
        # Мы ищем все активные заказы, где название канала упоминается в строке channels
        # Сортируем по SPM (сначала самые дорогие)
        candidates = ChatAdOrder.objects.filter(
            channels__icontains=channel_name,  # Может найти "news" внутри "news_sport", проверим точнее ниже
            is_active=True,
            completed=False,
            cancelled=False,
            remaining_views__gt=0
        ).order_by('-spm')

        # 3. Перебор кандидатов (Ротация)
        for order in candidates:
            # 3.1 Точная проверка канала (так как в БД строка через запятую)
            if not order.is_channel_in_list(channel_name):
                continue

            # 3.2 Проверка лимитов на пользователя (Frequency Capping)
            if order.max_views_per_user != -1:
                # Если лимит есть, проверяем, сколько раз юзер уже видел эту рекламу
                # Используем .only('view_count') для оптимизации запроса
                view_entry = ChatAdView.objects.filter(
                    order=order,
                    viewer_id=viewer_id
                ).only('view_count').first()

                if view_entry and view_entry.view_count >= order.max_views_per_user:
                    # Юзер уже насмотрел лимит -> пропускаем этот заказ, идем к следующему (дешевле)
                    continue

            # 3.3 Попытка списания просмотра (Concurrency safe)
            # Если мы дошли сюда, значит реклама подходит. Нужно заблокировать строку и списать просмотр.
            with transaction.atomic():
                # Блокируем заказ для записи (защита от race condition)
                try:
                    locked_order = ChatAdOrder.objects.select_for_update(nowait=False).get(pk=order.pk)
                except ChatAdOrder.DoesNotExist:
                    continue  # Если заказ удалили за миллисекунду

                # Проверяем оставшиеся просмотры еще раз (вдруг списали в параллельном потоке)
                if locked_order.remaining_views <= 0 or not locked_order.is_active:
                    continue

                # --- ЛОГИКА ЗАПИСИ ПРОСМОТРА ---

                # 1. Списываем глобальный просмотр (бюджет)
                locked_order.decrement_views()

                # 2. Логика сохранения истории просмотра (Требование пользователя)
                if locked_order.max_views_per_user != -1:
                    # Если лимит не -1, мы ОБЯЗАНЫ сохранять/обновлять счетчик юзера
                    view_obj, created = ChatAdView.objects.get_or_create(
                        order=locked_order,
                        viewer_id=viewer_id
                    )
                    view_obj.increment_view()

                # Если -1, мы просто списали remaining_views и ничего не пишем в ChatAdView.
                # Это экономит место в БД, как и требовалось.

                # 4. Возвращаем рекламу
                response_serializer = ChatAdPublicSerializer(locked_order)
                return Response(response_serializer.data, status=status.HTTP_200_OK)

        # Если цикл прошел и ничего не вернул
        return Response(
            {"message": "Нет доступной рекламы для этого канала или пользователя"},
            status=status.HTTP_404_NOT_FOUND
        )
