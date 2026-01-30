from rest_framework import serializers

from apps.search_ads.models import Order


# class SearchResponseSerializer(serializers.Serializer):
#     """Сериализатор для ответа поиска"""
#     message = serializers.CharField()
#     channel = serializers.DictField()
#     remaining_views = serializers.IntegerField()


# НУЖНО В ПРЕДСТАВЛЕНИЕ ЭТО ИСПОЛЬЗОВАТЬ. СЕЙЧАС ОН НЕ ИСПОЛЬЗУЕТСЯ
class SearchResultSerializer(serializers.Serializer):
    """Сериализатор для результата поиска"""
    channel_id = serializers.CharField()
    channel_name = serializers.CharField()
    order_id = serializers.UUIDField()


class SearchRequestSerializer(serializers.Serializer):
    """Сериализатор для запроса поиска"""
    tag = serializers.CharField(required=True)
    viewer_id = serializers.CharField(required=True, help_text='ID пользователя, который ищет канал')


class ClickOrderSerializer(serializers.Serializer):
    order_id = serializers.UUIDField(required=True)
    viewer_id = serializers.CharField(required=True, help_text='ID пользователя который посмотрел канал')

    def validate(self, attrs):
        order_id = attrs.get('order_id')

        try:
            order = Order.objects.only('order_id', 'clicks', 'is_active').get(
                order_id=order_id,
                is_active=True
            )
        except Order.DoesNotExist:
            raise serializers.ValidationError({"order_id": "Активный ордер не найден"})

        # Кладем найденный объект в данные, чтобы view могла его забрать
        attrs['order_object'] = order
        return attrs
