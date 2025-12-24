from rest_framework import serializers


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
    order_id = serializers.CharField()


class SearchRequestSerializer(serializers.Serializer):
    """Сериализатор для запроса поиска"""
    tag = serializers.CharField(required=True)
    viewer_id = serializers.CharField(required=True, help_text='ID пользователя, который ищет канал')
