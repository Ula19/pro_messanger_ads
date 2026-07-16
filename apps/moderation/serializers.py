from rest_framework import serializers

from apps.search_ads.serializers import OrderDetailSerializer
from apps.chat_ads.serializers import ChatAdOrderSerializer


class ModerationSearchOrderSerializer(OrderDetailSerializer):
    """Заказ поисковой рекламы глазами модератора: как у пользователя + имя владельца"""
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta(OrderDetailSerializer.Meta):
        fields = OrderDetailSerializer.Meta.fields + ['username']


class ModerationChatOrderSerializer(ChatAdOrderSerializer):
    """Заказ рекламы в чатах глазами модератора: как у пользователя + имя владельца"""
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta(ChatAdOrderSerializer.Meta):
        fields = ChatAdOrderSerializer.Meta.fields + ['username']


class ModerationReasonSerializer(serializers.Serializer):
    """
    Тело reject/block: причина обязательна — пользователь увидит её у своего заказа.
    Для approve тело запроса не нужно вовсе.
    """
    reason = serializers.CharField(required=True, allow_blank=False, max_length=500,
                                   trim_whitespace=True,
                                   help_text='Причина отклонения/блокировки — её увидит пользователь')
