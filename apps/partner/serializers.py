from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import ChannelEarning, EarningTransaction


class PublicEarningSerializer(serializers.ModelSerializer):
    """Публичная витрина-«крючок»: сколько канал уже заработал. Без суммы к выводу."""
    is_claimed = serializers.SerializerMethodField()

    class Meta:
        model = ChannelEarning
        fields = ['channel_id', 'channel_name', 'total_earned', 'total_impressions', 'is_claimed']

    @extend_schema_field(serializers.BooleanField())
    def get_is_claimed(self, obj):
        return obj.claim_status == ChannelEarning.ClaimStatus.CONFIRMED


class MyEarningSerializer(serializers.ModelSerializer):
    """Заработок для подтверждённого владельца."""
    share_rate = serializers.SerializerMethodField()

    class Meta:
        model = ChannelEarning
        fields = [
            'channel_id', 'channel_name', 'available', 'total_earned', 'total_impressions',
            'claim_status', 'share_rate', 'claimed_at',
        ]

    @extend_schema_field(serializers.DecimalField(max_digits=4, decimal_places=3))
    def get_share_rate(self, obj):
        return obj.get_share_rate()


class ClaimRequestSerializer(serializers.Serializer):
    channel_id = serializers.IntegerField(required=True)
    # Необязательная метка-имя для витрины (если клиент его знает).
    channel_name = serializers.CharField(max_length=255, required=False, allow_blank=True)


class WithdrawRequestSerializer(serializers.Serializer):
    channel_id = serializers.IntegerField(required=True)


class EarningTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EarningTransaction
        fields = ['kind', 'amount', 'impressions', 'order', 'created_at', 'updated_at']


class MessageSerializer(serializers.Serializer):
    message = serializers.CharField()
