from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Announcement


class AnnouncementClientSerializer(serializers.ModelSerializer):
    """Баннер глазами NovaGram-клиента: только то, что нужно для отрисовки"""
    class Meta:
        model = Announcement
        # ends_at отдаём, чтобы клиент сам погасил баннер по истечении окна
        fields = ['id', 'title', 'text', 'link', 'dismissible', 'ends_at']
        read_only_fields = fields


class AnnouncementManageSerializer(serializers.ModelSerializer):
    """Баннер глазами суперадмина: все поля + статистика"""
    dismissals_count = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        fields = ['id', 'title', 'text', 'link', 'dismissible', 'is_active',
                  'starts_at', 'ends_at', 'priority', 'clicks', 'dismissals_count',
                  'created_by', 'created_at', 'updated_at']
        read_only_fields = ['id', 'clicks', 'dismissals_count', 'created_by',
                            'created_at', 'updated_at']

    @extend_schema_field(serializers.IntegerField())
    def get_dismissals_count(self, obj):
        # Аннотация из queryset вью; у только что созданного баннера её нет — закрытий 0
        return getattr(obj, 'dismissals_count_agg', 0)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_created_by(self, obj):
        # Создателя могли удалить (FK SET_NULL) — тогда отдаём null
        return obj.created_by.username if obj.created_by else None

    def update(self, instance, validated_data):
        # Сохраняем ТОЛЬКО изменённые поля: полный save() затёр бы конкурентные
        # клики (click-эндпоинт крутит счётчик атомарным F('clicks') + 1)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save(update_fields=list(validated_data.keys()) + ['updated_at'])
        return instance

    def validate(self, attrs):
        # PATCH может прислать только одну из дат — вторую берём из instance
        starts_at = attrs.get('starts_at', getattr(self.instance, 'starts_at', None)) or timezone.now()
        ends_at = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))
        if ends_at and ends_at <= starts_at:
            raise serializers.ValidationError({'ends_at': 'Конец показа должен быть позже начала'})
        return attrs


class ActiveAnnouncementsRequestSerializer(serializers.Serializer):
    """Запрос активных баннеров для юзера"""
    viewer_id = serializers.CharField(required=True, max_length=255)


class DismissRequestSerializer(serializers.Serializer):
    """Юзер закрыл баннер крестиком"""
    announcement_id = serializers.UUIDField(required=True)
    viewer_id = serializers.CharField(required=True, max_length=255)


class ClickRequestSerializer(serializers.Serializer):
    """Клик по баннеру (для статистики)"""
    announcement_id = serializers.UUIDField(required=True)
