# chat_ads/serializers.py
from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from .models import ChatAdOrder, ChatAdView


class ChatAdOrderSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    refund_amount = serializers.SerializerMethodField()

    class Meta:
        model = ChatAdOrder
        fields = [
            'order_id', 'user_id', 'order_name', 'text', 'link', 'channels',
            'image', 'video', 'spm', 'budget', 'total_views', 'clicks',
            'shown_views', 'remaining_views', 'max_views_per_user', 'refund_amount',
            'completed', 'cancelled', 'is_active', 'created_at'
        ]
        read_only_fields = [
            'order_id', 'user_id', 'total_views', 'clicks', 'shown_views', 'refund_amount',
            'remaining_views', 'completed',  'cancelled', 'is_active', 'created_at'
        ]

    @extend_schema_field(serializers.CharField())
    def get_user_id(self, obj):
        return obj.user.user_id

    @extend_schema_field(serializers.DecimalField(max_digits=15, decimal_places=2))
    def get_refund_amount(self, obj):
        """
        Вычисляет сумму возврата при отмене на основе оставшихся просмотров и SPM.
        Использует метод модели get_refund_amount().
        """
        return obj.get_refund_amount()

    @extend_schema_field(serializers.DecimalField(max_digits=10, decimal_places=2))
    def validate_budget(self, value):
        """Валидация бюджета"""
        if value <= Decimal('0'):
            raise serializers.ValidationError("Бюджет должен быть больше 0")
        return value

    @extend_schema_field(serializers.DecimalField(max_digits=10, decimal_places=2))
    def validate_spm(self, value):
        """Валидация SPM"""
        if value <= Decimal('0'):
            raise serializers.ValidationError("SPM должен быть больше 0")
        return value

    @extend_schema_field(serializers.CharField())
    def validate_channels(self, value):
        """Валидация списка каналов"""
        if not value or not value.strip():
            raise serializers.ValidationError("Необходимо указать каналы")

        channels_list = [ch.strip() for ch in value.split(',') if ch.strip()]
        if not channels_list:
            raise serializers.ValidationError("Необходимо указать хотя бы один канал")

        return value

    @extend_schema_field(serializers.IntegerField())
    def validate_max_views_per_user(self, value):
        """Валидация лимита показов"""
        if value < -1:
            raise serializers.ValidationError("Значение не может быть меньше -1")
        return value


class ChatAdViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatAdView
        fields = ['id', 'order', 'viewer_id', 'view_count', 'clicked', 'last_viewed_at']
        read_only_fields = ['id', 'view_count', 'clicked', 'last_viewed_at']
