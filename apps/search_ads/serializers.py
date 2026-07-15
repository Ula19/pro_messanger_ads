from django.db import transaction
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from apps.billing.models import Balance
from apps.common.models import ModerationStatus
from apps.search_ads.models import Channel, Order, Tag


# ============================================ ORDER CRUD ==========================================================

class CreateChannelOrderSerializer(serializers.Serializer):
    """Сериализатор для создания канала и заказа"""
    # Поля для поиска/создания канала
    channel_id = serializers.CharField(max_length=255, required=True)
    channel_name = serializers.CharField(max_length=255, required=True)
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)

    # Поля для создания заказа
    order_name = serializers.CharField(max_length=255, required=True)
    platform = serializers.ChoiceField(choices=Order.Platform.choices, default=Order.Platform.TELEGRAM)
    spm = serializers.DecimalField(max_digits=10, decimal_places=2, required=True)
    budget = serializers.DecimalField(max_digits=15, decimal_places=2, required=True)
    max_views_per_user = serializers.IntegerField(default=1)
    # is_active от клиента не принимаем: новый заказ всегда уходит на модерацию
    # и включается только после одобрения модератором

    def validate(self, data):
        if data['spm'] <= 0:
            raise serializers.ValidationError({"spm": "SPM должен быть больше 0."})
        if data['budget'] <= 0:
            raise serializers.ValidationError({"budget": "Бюджет должен быть больше 0."})
        if data['max_views_per_user'] <= 0:
            raise serializers.ValidationError({"max_views_per_user": "Лимит показов должен быть больше 0."})
        return data

    def create(self, validated_data):
        user = self.context['request'].user
        tag_names = validated_data.get('tags', [])
        budget = validated_data['budget']

        # Используем транзакцию, чтобы все создалось или ничего
        with transaction.atomic():
            # 1. Блокируем строку баланса (select_for_update), чтобы два параллельных
            # заказа не могли оба пройти проверку и уйти в минус (защита от гонки).
            balance = Balance.objects.select_for_update().get(user=user)

            # 2. Проверяем баланс и списываем средства уже под блокировкой
            if balance.amount < budget:
                raise serializers.ValidationError(
                    {"budget": f"Недостаточно средств. Доступно: {balance.amount}"}
                )
            if not balance.withdraw(budget):
                raise serializers.ValidationError({"budget": "Ошибка списания средств"})

            # 3. Создаем или обновляем канал
            channel, _ = Channel.objects.update_or_create(
                channel_id=validated_data['channel_id'],
                user=user,
                defaults={'channel_name': validated_data['channel_name']}
            )

            # Добавляем теги к каналу
            if tag_names:
                channel.add_tags(tag_names)

            # 4. Создаем заказ (статус PENDING и is_active=False выставит Order.save())
            order = Order.objects.create(
                channel_id=channel,
                user=user,
                channel_name=validated_data['channel_name'],
                order_name=validated_data['order_name'],
                platform=validated_data['platform'],
                spm=validated_data['spm'],
                budget=validated_data['budget'],
                max_views_per_user=validated_data['max_views_per_user'],
            )

            # 5. Явно привязываем теги к заказу (безопаснее, чем через _tag_names)
            if tag_names:
                for tag_name in tag_names:
                    # strip() и lower() для чистоты данных
                    tag, _ = Tag.objects.get_or_create(name=tag_name.strip().lower())
                    order.tags.add(tag)

        # Возвращаем созданный объект order.
        # View не использует этот объект для ответа (там ResponseMessage), поэтому это безопасно.
        return order


class OrderDetailSerializer(serializers.ModelSerializer):
    """
    Сериализатор для детальной информации о заказе

    Поля:
    - id: Уникальный идентификатор заказа в системе
    - channel_id: ID связанного канала (ForeignKey -> Channel.id)
    - channel_name: Название канала, в котором размещается реклама
    - order_name: Название рекламного заказа (кампании)
    - tags: Список тегов, связанных с заказом (ManyToMany -> Tag)
    - spm: Spend per mille - стоимость 1000 показов в денежных единицах
    - budget: Общий бюджет заказа, выделенный на рекламу
    - total_views: Общее количество купленных показов
    - shown_views: Количество уже показанных пользователям просмотров
    - remaining_views: Оставшееся количество показов к отображению
    - completed: Флаг завершения заказа (True = все показы израсходованы)
    - cancelled: Флаг отмены заказа (True = заказ отменен пользователем)
    - is_active: Флаг активности заказа (True = реклама показывается)
    - refund_amount: Сумма, которая будет возвращена при отмене заказа
    - max_views_per_user: Максимальное количество показов одному пользователю
    - created_at: Дата и время создания заказа
    - updated_at: Дата и время последнего обновления заказа
    """
    tags = serializers.SerializerMethodField()
    refund_amount = serializers.SerializerMethodField()
    channel_id = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'order_id', 'channel_id', 'channel_name', 'order_name', 'platform', 'tags',
            'spm', 'budget', 'total_views', 'shown_views', 'remaining_views', 'clicks',
            'completed', 'cancelled', 'is_active', 'status', 'reject_reason', 'refund_amount',
            'max_views_per_user', 'created_at', 'updated_at'
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_channel_id(self, obj):
        return str(obj.channel_id.channel_id)

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_tags(self, obj):
        """Преобразует связанные объекты Tag в СПИСОК строковых имен"""
        return [tag.name for tag in obj.tags.all()]

    @extend_schema_field(serializers.DecimalField(max_digits=15, decimal_places=2))
    def get_refund_amount(self, obj):
        """
        Вычисляет сумму возврата при отмене на основе оставшихся просмотров и SPM.
        Использует метод модели get_refund_amount().
        """
        return obj.get_refund_amount()


class OrderActivationSerializer(serializers.Serializer):
    """Сериализатор для активации/деактивации заказа"""
    order_id = serializers.UUIDField(required=True)
    is_active = serializers.BooleanField(required=True)

    def validate(self, data):
        """
        Валидация данных активации заказа
        """
        request = self.context.get('request')
        user = request.user
        order_id = data['order_id']
        is_active = data['is_active']

        try:
            # Проверяем, существует ли заказ
            order = Order.objects.get(order_id=order_id)

            # Проверяем, принадлежит ли заказ текущему пользователю
            if order.user != user:
                raise serializers.ValidationError({
                    "error": "У вас нет прав для изменения этого заказа"
                })

            # Сохраняем order в данных для использования во view
            data['order'] = order

            # Проверяем, можно ли изменять статус
            validation_errors = self._validate_order_status(order, is_active)
            if validation_errors:
                raise serializers.ValidationError(validation_errors)

        except Order.DoesNotExist:
            raise serializers.ValidationError({
                "error": "Заказ с указанным ID не найден"
            })

        return data

    def _validate_order_status(self, order, new_is_active):
        """
        Проверка возможности изменения статуса заказа
        """
        errors = {}

        # Включать/выключать можно только заказ, прошедший модерацию
        if order.status != ModerationStatus.APPROVED:
            errors['error'] = f"Заказ не прошёл модерацию (статус: {order.get_status_display()}) — менять активность нельзя"
            return errors

        # Проверяем, не отменен ли заказ
        if order.cancelled:
            errors['error'] = "Невозможно изменить статус отмененного заказа"
            return errors

        # Проверяем, не завершен ли заказ
        if order.completed:
            errors['error'] = "Невозможно изменить статус завершенного заказа"
            return errors

        # Если пытаемся установить тот же статус
        if order.is_active == new_is_active:
            status_text = "активен" if new_is_active else "неактивен"
            errors['warning'] = f"Заказ уже {status_text}"

        # Если пытаемся активировать заказ без оставшихся просмотров
        if new_is_active and order.remaining_views <= 0:
            errors['error'] = "Невозможно активировать заказ без оставшихся просмотров"

        # Если пытаемся активировать заказ с нулевым бюджетом
        if new_is_active and order.budget <= 0:
            errors['error'] = "Невозможно активировать заказ с нулевым бюджетом"

        return errors


class ResponsesMessageSerializer(serializers.Serializer):
    message = serializers.CharField()


# ============================================ ORDER SEARCH AND CLICK ==================================================

class SearchResultSerializer(serializers.Serializer):
    """Сериализатор для результата поиска"""
    channel_id = serializers.CharField()
    channel_name = serializers.CharField()
    order_id = serializers.UUIDField()
    platform = serializers.CharField()


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
