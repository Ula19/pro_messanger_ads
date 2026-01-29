# chat_ads/serializers.py
from decimal import Decimal

from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from .models import ChatAdOrder, ChatAdView, ChatAdMedia


class ChatAdMediaSerializer(serializers.ModelSerializer):
    """Сериализатор для загрузки медиа"""
    class Meta:
        model = ChatAdMedia
        fields = ['id', 'file', 'media_type', 'created_at', 'is_linked']
        read_only_fields = ['id', 'created_at', 'media_type', 'is_linked']

    def validate_file(self, value):
        """Определяем тип файла и валидируем размер"""
        # Определяем тип по расширению или MIME
        content_type = value.content_type
        if content_type.startswith('image'):
            self.context['media_type'] = ChatAdMedia.MediaType.IMAGE
            if value.size > 2 * 1024 * 1024:  # 5 MB
                raise serializers.ValidationError("Размер изображения не более 5 МБ")
        elif content_type.startswith('video'):
            self.context['media_type'] = ChatAdMedia.MediaType.VIDEO
            if value.size > 10 * 1024 * 1024:  # 50 MB
                raise serializers.ValidationError("Размер видео не более 50 МБ")
        else:
            raise serializers.ValidationError("Неподдерживаемый формат файла")
        return value

    def create(self, validated_data):
        # Добавляем определенный тип медиа
        validated_data['media_type'] = self.context.get('media_type', ChatAdMedia.MediaType.IMAGE)
        return super().create(validated_data)


class ChatAdOrderSerializer(serializers.ModelSerializer):
    """
    Сериализатор создания заказа.
    Принимает media_id (UUID), а не сам файл.
    """
    user_id = serializers.SerializerMethodField()
    refund_amount = serializers.SerializerMethodField()
    media_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    media_url = serializers.SerializerMethodField()

    class Meta:
        model = ChatAdOrder
        fields = [
            'order_id', 'user_id', 'order_name', 'text', 'link', 'channels',
            'media_url', 'spm', 'budget',  'total_views', 'clicks',
            'max_views_per_user', 'shown_views', 'remaining_views',
            'refund_amount', 'completed', 'cancelled', 'is_active', 'created_at',
            'media_id'
        ]
        read_only_fields = [
            'order_id', 'user_id', 'total_views', 'clicks',
            'shown_views', 'refund_amount', 'remaining_views', 'media_url',
            'completed', 'cancelled',  'created_at'
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

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_media_url(self, obj):
        """Возвращает URL прикрепленного медиафайла"""
        if obj.media_url and obj.media_url.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.media_url.file.url)
        return None

    def validate_media_id(self, value):
        """Проверяем, что медиа существует и принадлежит этому юзеру"""
        if not value:
            return None

        try:  # >>>>>>>>>>>>>>>>>>>>>>>>> УДАЛИ КОММЕНТЫ НИЖЕ <<<<<<<<<<<<<<<<<<<
            media = ChatAdMedia.objects.get(id=value, user=self.context['request'].user)
            # if media.is_linked:
            #     raise serializers.ValidationError("Этот файл уже используется в другом заказе.")
            return media
        except ChatAdMedia.DoesNotExist:
            raise serializers.ValidationError("Медиафайл не найден или не принадлежит вам.")

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
        if value == 0:
            raise serializers.ValidationError("Значение не может быть 0")
        return value


class ChatAdViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatAdView
        fields = ['id', 'order', 'viewer_id', 'view_count', 'clicked', 'last_viewed_at']
        read_only_fields = ['id', 'view_count', 'clicked', 'last_viewed_at']


class ChatAdOrderActivationSerializer(serializers.Serializer):
    order_id = serializers.UUIDField(required=True)
    is_active = serializers.BooleanField(required=True)

    def validate_order_id(self, value):
        """
        1. Проверяем, существует ли заказ.
        2. Проверяем, принадлежит ли он текущему юзеру.
        Возвращаем САМ ОБЪЕКТ, чтобы не искать его снова.
        """
        user = self.context['request'].user
        try:
            # Сразу ищем по ID и юзеру. Если юзер чужой — выпадет DoesNotExist
            order = ChatAdOrder.objects.get(pk=value, user=user)
        except ChatAdOrder.DoesNotExist:
            raise serializers.ValidationError("Заказ не найден или у вас нет прав на его изменение.")
        return order

    def validate(self, attrs):
        """
        Предварительная валидация бизнес-логики.
        """
        order = attrs['order_id']  # Здесь уже объект модели
        new_is_active = attrs['is_active']

        # 1. Если заказ отменен или завершен — менять статус нельзя
        if order.cancelled:
            raise serializers.ValidationError("Невозможно активировать отмененный заказ.")

        if order.completed:
            raise serializers.ValidationError("Невозможно активировать завершенный заказ.")

        # 2. Если пытаемся ВКЛЮЧИТЬ, проверяем ресурсы
        if new_is_active:
            if order.remaining_views <= 0:
                raise serializers.ValidationError("Нельзя активировать заказ: закончились просмотры.")

            if order.budget <= 0:
                raise serializers.ValidationError("Нельзя активировать заказ с нулевым бюджетом.")

        return attrs

    def save(self):
        """
        Метод сохранения с блокировкой базы данных.
        """
        order_instance = self.validated_data['order_id']
        new_is_active = self.validated_data['is_active']

        # Если статус не меняется, просто выходим
        # if order_instance.is_active == new_is_active:
        #     return order_instance

        if order_instance.is_active == new_is_active:
            status_text = "активен" if new_is_active else "неактивен"
            raise serializers.ValidationError(f"Заказ уже {status_text}")

        # АТОМАРНАЯ ОПЕРАЦИЯ (Защита от двойных списаний/активаций)
        with transaction.atomic():
            # Блокируем строку в БД (select_for_update)
            # Нужно перезапросить объект по ID, чтобы наложить блокировку
            locked_order = ChatAdOrder.objects.select_for_update().get(pk=order_instance.pk)

            # Повторная проверка внутри транзакции (на случай параллельных запросов)
            if new_is_active and locked_order.remaining_views <= 0:
                raise serializers.ValidationError("Ошибка активации: просмотры исчерпаны.")

            # Применяем изменения
            locked_order.is_active = new_is_active

            # Если вдруг активировали, но просмотров 0 (параноидальная проверка)
            if new_is_active and locked_order.remaining_views <= 0:
                locked_order.completed = True
                locked_order.is_active = False

            locked_order.save(update_fields=['is_active', 'completed'])
            return locked_order


class ChatAdResponsesMessageSerializer(serializers.Serializer):
    message = serializers.CharField()


class AdRequestSerializer(serializers.Serializer):
    """Валидация входящего запроса на получение рекламы"""
    channel_name = serializers.CharField(max_length=255, required=True)
    viewer_id = serializers.CharField(max_length=255, required=True)


class ChatAdPublicSerializer(serializers.ModelSerializer):
    """
    Сериализатор для отдачи рекламы клиенту.
    Превращает сложный объект Media в простую ссылку.
    """
    media_url = serializers.SerializerMethodField()
    media_type = serializers.SerializerMethodField()

    class Meta:
        model = ChatAdOrder
        fields = [
            'order_id', 'order_name', 'text', 'link',
            'media_url', 'media_type', 'total_views',
            'clicks', 'shown_views', 'remaining_views'
        ]
        read_only_fields = [
            'clicks', 'shown_views', 'remaining_views', 'total_views',
        ]

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_media_url(self, obj):
        # Если есть привязанный медиа-файл, возвращаем его полный URL
        if obj.media_url and obj.media_url.file:
            return obj.media_url.file.url
        return None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_media_type(self, obj):
        if obj.media_url:
            return obj.media_url.media_type
        return None


class ChatAdClickOrderSerializer(serializers.Serializer):
    order_id = serializers.UUIDField(required=True)
    viewer_id = serializers.CharField(required=True, help_text='ID пользователя который посмотрел канал')

    def validate(self, attrs):
        order_id = attrs.get('order_id')

        try:
            order = ChatAdOrder.objects.only('order_id', 'clicks', 'is_active').get(
                order_id=order_id,
                is_active=True
            )
        except ChatAdOrder.DoesNotExist:
            raise serializers.ValidationError({"order_id": "Активный ордер не найден"})

        # Кладем найденный объект в данные, чтобы view могла его забрать
        attrs['order_object'] = order
        return attrs
