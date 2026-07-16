from django.db.models import F
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status, permissions
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.common.models import ModerationStatus
from apps.common.pagination import StandardResultsSetPagination
from apps.common.permissions import HasServerApiKey
from apps.common.schema import ERROR_RESPONSE, MESSAGE_RESPONSE, SERVER_API_KEY_AUTH

from apps.billing.models import Balance
from apps.partner.models import ChannelEarning
from .models import ChatAdOrder, ChatAdMedia, ChatAdView
from .serializers import ChatAdMediaSerializer, ChatAdOrderSerializer, ChatAdOrderActivationSerializer, \
    ChatAdResponsesMessageSerializer, AdRequestSerializer, ChatAdSearchSerializer, ChatAdClickOrderSerializer


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

        response_data = {'message': 'Ордер создан и отправлен на модерацию'}
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
    GET /api/chat_ads/order/{order_id}/detail/
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

    @extend_schema(request=None, responses={
        200: ChatAdResponsesMessageSerializer,
        400: ERROR_RESPONSE,  # уже отменён / завершён / отклонён-заблокирован (деньги вернули)
        404: ERROR_RESPONSE,  # не найден или чужой заказ
    })
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

            response_data = {'message': 'Ордер отменен'}
            response_serializer = ChatAdResponsesMessageSerializer(data=response_data)
            response_serializer.is_valid(raise_exception=True)

            return Response(response_serializer.data, status=status.HTTP_200_OK)

            # return Response(status=status.HTTP_204_NO_CONTENT)

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
        # По отклонённому/заблокированному заказу деньги уже вернули при модерации
        if order.status in (ModerationStatus.REJECTED, ModerationStatus.BLOCKED):
            return 'Заказ отклонён или заблокирован, средства уже возвращены.'
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
    Получение рекламы для чата канала.
    POST /api/chat_ads/order/search/
    Body: {"channel_name": "...", "viewer_id": "...", "channel_id": 123}
    (channel_id — числовой id канала-площадки; без него заработок площадке не начислится).
    Успешный ответ — это засчитанный показ: у заказа атомарно списывается один показ.
    404 — штатный исход «подходящей рекламы нет».
    Доступ — только по заголовку X-API-Key (server-to-server от NovaGram).
    """
    serializer_class = AdRequestSerializer
    permission_classes = [HasServerApiKey]  # только запросы с сервера NovaGram (по API-ключу)
    throttle_classes = []  # доверенный сервер (server-to-server), глобальный троттл 500/min тут не нужен

    @extend_schema(request=AdRequestSerializer, auth=SERVER_API_KEY_AUTH, responses={
        200: ChatAdSearchSerializer,
        404: MESSAGE_RESPONSE,  # «Нет доступной рекламы...» — регулярный ответ, не ошибка
    })
    def post(self, request):
        # 1. Валидация входных данных
        input_serializer = self.serializer_class(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        channel_name = input_serializer.validated_data['channel_name']
        viewer_id = input_serializer.validated_data['viewer_id']
        channel_id = input_serializer.validated_data.get('channel_id')

        # 2. Поиск кандидатов (Грубая фильтрация)
        # Мы ищем все активные заказы, где название канала упоминается в строке channels
        # Сортируем по SPM (сначала самые дорогие)
        candidates = ChatAdOrder.objects.filter(
            channels__icontains=channel_name,  # Может найти "news" внутри "news_sport", проверим точнее ниже
            status=ModerationStatus.APPROVED,  # показываем только прошедшее модерацию
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

                if order.max_views_per_user == 0:
                    continue

            # 3.3 Списание показа — атомарным условным UPDATE, без блокирующего
            # select_for_update. WHERE-условие само отсекает гонку: одновременно
            # пройдёт ровно один запрос, лишние получат 0 обновлённых строк.
            with transaction.atomic():
                updated = ChatAdOrder.objects.filter(
                    pk=order.pk, remaining_views__gt=0,
                    status=ModerationStatus.APPROVED,
                    is_active=True, cancelled=False
                ).update(
                    remaining_views=F('remaining_views') - 1,
                    shown_views=F('shown_views') + 1,
                )
                if not updated:
                    continue  # показы кончились или кто-то успел раньше — к следующему заказу

                # Показы исчерпаны -> помечаем заказ завершённым (точечный дешёвый апдейт).
                ChatAdOrder.objects.filter(pk=order.pk, remaining_views=0).update(
                    completed=True, is_active=False
                )

                # Начисляем заработок каналу-площадке за этот показ. Строка заказа залочена
                # этим UPDATE до commit, поэтому параллельные показы ЭТОГО же заказа
                # сериализуются — счётчик показов юзера ниже безопасен.
                ChannelEarning.accrue(channel_id, order, channel_name=channel_name)

                # История показов на пользователя — только при заданном лимите (иначе -1: не пишем).
                if order.max_views_per_user != -1:
                    view_obj, _ = ChatAdView.objects.get_or_create(
                        order=order, viewer_id=viewer_id
                    )
                    view_obj.increment_view()

                # Отдаём рекламу. В БД показ уже списан; счётчики в объекте правим в памяти.
                order.remaining_views -= 1
                order.shown_views += 1
                # context с request нужен, чтобы media_url был абсолютным
                return Response(ChatAdSearchSerializer(order, context={'request': request}).data,
                                status=status.HTTP_200_OK)

        # Если цикл прошел и ничего не вернул
        return Response(
            {"message": "Нет доступной рекламы для этого канала или пользователя"},
            status=status.HTTP_404_NOT_FOUND
        )


class ChatAdClickView(APIView):
    """
    Увеличивает счетчик кликов у объявления.
    Доступ — только по заголовку X-API-Key (server-to-server от NovaGram).
    400 приходит, если заказ не найден или уже не активен (завершён/выключен).
    """
    permission_classes = [HasServerApiKey]  # только запросы с сервера NovaGram (по API-ключу)
    throttle_classes = []  # доверенный сервер, глобальный троттл тут не нужен
    serializer_class = ChatAdClickOrderSerializer

    @extend_schema(request=ChatAdClickOrderSerializer, auth=SERVER_API_KEY_AUTH, responses={
        200: ChatAdResponsesMessageSerializer,
        400: {
            'type': 'object',
            'properties': {'order_id': {'type': 'array', 'items': {'type': 'string'}}},
        },
    })
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
        response_serializer = ChatAdResponsesMessageSerializer(data=response_data)
        response_serializer.is_valid(raise_exception=True)

        return Response(response_serializer.data, status=status.HTTP_200_OK)
