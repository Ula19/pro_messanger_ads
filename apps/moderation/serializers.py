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


class ModerationDecisionSerializer(serializers.Serializer):
    """
    Тело решения модератора. Для reject и block причина обязательна —
    пользователь увидит её у своего заказа. Для approve причина не нужна.
    """
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500,
                                   trim_whitespace=True,
                                   help_text='Причина отклонения/блокировки (обязательна для reject и block)')

    def validate(self, attrs):
        action = self.context.get('action')
        if action in ('reject', 'block') and not attrs.get('reason', '').strip():
            raise serializers.ValidationError({'reason': 'Укажите причину отклонения/блокировки'})
        return attrs
