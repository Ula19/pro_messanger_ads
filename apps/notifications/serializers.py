from rest_framework import serializers

from .models import Device, Notification


class DeviceRegisterSerializer(serializers.Serializer):
    """Регистрация FCM-токена устройства после логина"""
    token = serializers.CharField(required=True, max_length=500)
    platform = serializers.ChoiceField(required=True, choices=Device.Platform.choices)


class DeviceRemoveSerializer(serializers.Serializer):
    """Отвязка токена при логауте (токен в теле — в FCM-токенах есть двоеточия)"""
    token = serializers.CharField(required=True, max_length=500)


class NotificationSerializer(serializers.ModelSerializer):
    """Уведомление глазами юзера"""
    class Meta:
        model = Notification
        fields = ['id', 'title', 'body', 'type', 'payload', 'is_read', 'created_at']
        read_only_fields = fields
