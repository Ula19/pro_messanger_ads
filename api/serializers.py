from decimal import Decimal

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.views import TokenVerifyView

from .models import Channel, Order, Tag, Balance

User = get_user_model()


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Сериализатор для регистрации пользователя"""
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ('username', 'password', 'password2', 'email', 'is_admin')
        read_only_fields = ['is_admin']

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Пароли не совпадают"})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        is_admin = validated_data.pop('is_admin', False)

        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
            is_admin=is_admin
        )

        # Создаем баланс для нового пользователя
        Balance.objects.create(user=user, amount=0.00)

        return user


class UserLoginSerializer(TokenObtainPairSerializer):
    """Сериализатор для входа пользователя"""
    def validate(self, attrs):
        data = super().validate(attrs)
        data['user_id'] = self.user.user_id
        data['username'] = self.user.username
        data['is_admin'] = self.user.is_admin
        return data


class UserProfileSerializer(serializers.ModelSerializer):
    """Сериализатор для профиля пользователя"""
    class Meta:
        model = User
        fields = ['user_id', 'username', 'email', 'first_name', 'last_name', 'date_joined', 'is_admin']


class BalanceSerializer(serializers.ModelSerializer):
    """Сериализатор для баланса"""
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = Balance
        fields = ['username', 'amount',]
        read_only_fields = ['user', 'username']


class TagSerializer(serializers.ModelSerializer):
    """Сериализатор для модели Tag"""
    class Meta:
        model = Tag
        fields = ['id', 'name', 'created_at']


class ChannelSerializer(serializers.ModelSerializer):
    """Сериализатор для модели Channel"""
    tags = TagSerializer(many=True, read_only=True)
    tag_names = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
        default=list
    )

    class Meta:
        model = Channel
        fields = ['channel_id', 'channel_name', 'tags', 'tag_names', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at', 'channel_id', 'tags']

    def create(self, validated_data):
        tag_names = validated_data.pop('tag_names', [])
        channel = Channel.objects.create(**validated_data)
        if tag_names:
            channel.add_tags(tag_names)
        return channel


class OrderSerializer(serializers.ModelSerializer):
    """Сериализатор для модели Order"""
    tags = TagSerializer(many=True, read_only=True)
    tag_names = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
        default=list
    )

    class Meta:
        model = Order
        fields = [
            'id', 'channel_id', 'channel_name', 'order_name', 'tags', 'tag_names',
            'spm', 'budget', 'total_views', 'shown_views', 'remaining_views',
            'completed', 'cancelled', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'created_at', 'updated_at', 'tags', 'total_views',
            'shown_views', 'remaining_views', 'completed'
        ]

    def validate(self, data):
        # Проверяем, что у пользователя достаточно средств
        user = self.context['request'].user
        budget = data.get('budget', 0)

        if budget > 0:
            try:
                balance = user.balance
                if balance.amount < budget:
                    raise serializers.ValidationError(
                        {"budget": f"Недостаточно средств. Доступно: {balance.amount}"}
                    )
            except Balance.DoesNotExist:
                raise serializers.ValidationError({"balance": "Баланс не найден"})

        return data

    def create(self, validated_data):
        user = self.context['request'].user
        tag_names = validated_data.pop('tag_names', [])
        budget = validated_data.get('budget', 0)

        # Списываем средства с баланса
        if budget > 0:
            balance = user.balance
            if not balance.withdraw(budget):
                raise serializers.ValidationError(
                    {"budget": f"Недостаточно средств. Доступно: {balance.amount}"}
                )

        # Создаем заказ
        order = Order(**validated_data)
        order.user = user

        # Сохраняем теги во временный атрибут
        order._tag_names = tag_names
        order.save()

        return order

    def update(self, instance, validated_data):
        tag_names = validated_data.pop('tag_names', None)
        instance = super().update(instance, validated_data)

        if tag_names is not None:
            # Обновляем теги заказа
            instance.tags.clear()
            for tag_name in tag_names:
                tag, _ = Tag.objects.get_or_create(name=tag_name.lower().strip())
                instance.tags.add(tag)

        return instance


class OrderListSerializer(serializers.ModelSerializer):
    """Сериализатор для списка заказов"""
    tags = serializers.SerializerMethodField()
    channel_tags = serializers.SerializerMethodField()
    refund_amount = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'channel_id', 'channel_name', 'order_name',
            'tags', 'channel_tags', 'spm', 'budget',
            'total_views', 'shown_views', 'remaining_views',
            'completed', 'cancelled', 'is_active', 'refund_amount',
            'created_at'
        ]

    def get_tags(self, obj):
        """Получаем только имена тегов заказа"""
        return [tag.name for tag in obj.tags.all()]

    def get_channel_tags(self, obj):
        """Получаем только имена тегов канала"""
        return [tag.name for tag in obj.channel_id.tags.all()]

    def get_refund_amount(self, obj):
        """Получаем сумму возврата при отмене"""
        return obj.get_refund_amount()


class ChannelOrderSerializer(serializers.Serializer):
    """Сериализатор для создания канала и заказа"""
    # Поля канала
    channel_id = serializers.CharField(max_length=255, required=True)
    channel_name = serializers.CharField(max_length=255, required=True)
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)

    # Поля заказа
    order_name = serializers.CharField(max_length=255, required=True)
    spm = serializers.DecimalField(max_digits=10, decimal_places=2, required=True)
    budget = serializers.DecimalField(max_digits=15, decimal_places=2, required=True)

    def validate(self, data):
        if data['spm'] <= 0:
            raise serializers.ValidationError({"spm": "SPM должен быть больше 0."})

        if data['budget'] <= 0:
            raise serializers.ValidationError({"budget": "Бюджет должен быть больше 0."})

        return data

    def create(self, validated_data):
        user = self.context['request'].user
        tag_names = validated_data.get('tags', [])
        budget = validated_data['budget']

        # Проверяем баланс
        balance = user.balance
        if balance.amount < budget:
            raise serializers.ValidationError(
                {"budget": f"Недостаточно средств. Доступно: {balance.amount}"}
            )

        # Списываем средства
        if not balance.withdraw(budget):
            raise serializers.ValidationError(
                {"budget": "Ошибка списания средств"}
            )

        # Создаем или обновляем канал
        channel, created = Channel.objects.update_or_create(
            channel_id=validated_data['channel_id'],
            user=user,
            defaults={
                'channel_name': validated_data['channel_name'],
            }
        )

        # Добавляем теги к каналу (если есть новые)
        if tag_names:
            channel.add_tags(tag_names)

        # Создаем заказ с временным атрибутом для тегов
        order = Order(
            channel_id=channel,
            user=user,
            channel_name=validated_data['channel_name'],
            order_name=validated_data['order_name'],
            spm=validated_data['spm'],
            budget=validated_data['budget'],
        )

        # Сохраняем теги во временный атрибут
        order._tag_names = tag_names
        order.save()

        return {
            'channel': ChannelSerializer(channel).data,
            'order': OrderSerializer(order).data
        }


class CancelOrderSerializer(serializers.Serializer):
    """Сериализатор для отмены заказа"""
    cancel = serializers.BooleanField(required=True)

    def validate(self, data):
        if not data.get('cancel'):
            raise serializers.ValidationError({"cancel": "Для отмены заказа укажите cancel=true"})
        return data


class ChannelStatsSerializer(serializers.Serializer):
    """Сериализатор для статистики канала"""
    channel_name = serializers.CharField()
    total_orders = serializers.IntegerField()
    active_orders = serializers.IntegerField()
    total_views_purchased = serializers.IntegerField()
    total_budget_spent = serializers.DecimalField(max_digits=15, decimal_places=2)
    tags = serializers.ListField(child=serializers.CharField())
    orders = OrderSerializer(many=True)


class SearchResponseSerializer(serializers.Serializer):
    """Сериализатор для ответа поиска"""
    message = serializers.CharField()
    channel = serializers.DictField()
    remaining_views = serializers.IntegerField()


class DepositSerializer(serializers.Serializer):
    """Сериализатор для пополнения баланса"""
    amount = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        required=True,
        min_value=Decimal('0.01')
    )

    def validate(self, data):
        if data['amount'] <= 0:
            raise serializers.ValidationError({"amount": "Сумма должна быть больше 0"})
        return data
