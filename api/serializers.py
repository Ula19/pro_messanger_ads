from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Channel, CustomUser


class ChannelSerializer(serializers.ModelSerializer):
    """Сериализатор для модели Channel"""
    user_id = serializers.UUIDField(source='user.user_id', read_only=True)

    class Meta:
        model = Channel
        fields = [
            'channel_id',
            'user_id',
            'name',
            'order_name',
            'tags',
            'spm',
            'budget',
            'is_active',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_channel_id(self, value):
        """Проверка уникальности channel_id"""
        if Channel.objects.filter(channel_id=value).exists():
            raise serializers.ValidationError("Канал с таким идентификатором уже существует.")
        return value

    def validate_spm(self, value):
        """Проверка значения SPM"""
        if value < 0:
            raise serializers.ValidationError("SPM не может быть отрицательным.")
        return value

    def validate_budget(self, value):
        """Проверка значения бюджета"""
        if value < 0:
            raise serializers.ValidationError("Бюджет не может быть отрицательным.")
        return value


class UserSerializer(serializers.ModelSerializer):
    """Сериализатор для пользователя"""

    class Meta:
        model = CustomUser
        fields = ['user_id', 'username', 'email', 'first_name', 'last_name']


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Сериализатор для получения JWT токена"""
    def validate(self, attrs):
        data = super().validate(attrs)
        data['user_id'] = self.user.user_id
        data['username'] = self.user.username
        return data
