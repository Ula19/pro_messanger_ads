from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from api.models import Balance


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
