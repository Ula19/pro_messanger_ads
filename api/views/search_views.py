from rest_framework import generics, permissions, status
from rest_framework.response import Response
from django.db import transaction
from rest_framework.views import APIView

from api.models import Order, Tag, AdView

from api.serializer.search_serializer import SearchRequestSerializer, SearchResultSerializer, ClickOrderSerializer



class SearchChannelsView(generics.GenericAPIView):
    """Поиск каналов по тегу с учетом лимита показов на пользователя"""
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
        """Получает активные заказы с тегом, отсортированные по SPM"""
        return Order.objects.filter(
            tags=tag_obj,
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


class ClickView(APIView):
    serializer_class = ClickOrderSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        order_id = serializer.validated_data['order_id']

        try:
            order = Order.objects.get(id=order_id)
            order.increment_clicks()
            return Response(
                status=status.HTTP_204_NO_CONTENT
            )
        except Order.DoesNotExist:
            return Response(
                {'error': 'Ордер не найден'},
                status=status.HTTP_404_NOT_FOUND
            )
