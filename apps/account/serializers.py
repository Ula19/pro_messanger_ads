from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from drf_spectacular.utils import extend_schema_field
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from apps.billing.models import Balance


User = get_user_model()


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Сериализатор для регистрации пользователя"""
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        # Роль здесь не принимаем: каждый новый пользователь — рекламодатель (дефолт модели),
        # модератора назначает только суперадмин
        fields = ('username', 'password', 'password2', 'email')

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Пароли не совпадают"})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')

        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
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
        data['role'] = self.user.role
        return data


class UserProfileSerializer(serializers.ModelSerializer):
    """Сериализатор для профиля пользователя"""
    class Meta:
        model = User
        fields = ['user_id', 'username', 'email', 'first_name', 'last_name', 'date_joined', 'role']


class AdminUserSerializer(serializers.ModelSerializer):
    """Пользователь глазами суперадмина (список для назначения ролей и пополнения)"""
    balance = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['user_id', 'username', 'email', 'role', 'telegram_id', 'balance', 'date_joined']

    @extend_schema_field(serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True))
    def get_balance(self, obj):
        # У суперадмина, созданного через createsuperuser, баланса может не быть.
        # Строкой — как amount в /api/balance/ (Decimal в JSON иначе стал бы float)
        balance = getattr(obj, 'balance', None)
        return str(balance.amount) if balance else None


class UserRoleUpdateSerializer(serializers.Serializer):
    """Сериализатор для смены роли пользователя суперадмином"""
    role = serializers.ChoiceField(choices=User.Role.choices)
