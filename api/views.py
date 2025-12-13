from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import Channel
from .serializers import (
    ChannelSerializer,
    UserSerializer,
    CustomTokenObtainPairSerializer
)


class CustomTokenObtainPairView(TokenObtainPairView):
    """Кастомный view для получения JWT токена"""
    serializer_class = CustomTokenObtainPairSerializer


class CreateChannelView(generics.CreateAPIView):
    """View для создания канала"""
    queryset = Channel.objects.all()
    serializer_class = ChannelSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        """Привязываем канал к текущему пользователю"""
        serializer.save(user=self.request.user)


class UserProfileView(generics.RetrieveAPIView):
    """View для получения профиля пользователя"""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user
