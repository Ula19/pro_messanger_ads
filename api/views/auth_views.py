from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenVerifyView
from django.contrib.auth import get_user_model

from api.serializer.auth_serializer import UserRegistrationSerializer, UserLoginSerializer, UserProfileSerializer



User = get_user_model()



class UserRegistrationView(generics.CreateAPIView):
    """Регистрация нового пользователя"""
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]


@extend_schema(
    responses={
        200: {
            "type": "object",
            "properties": {
                "refresh": {"type": "string"},
                "access": {"type": "string"},
                "user_id": {"type": "string", "format": "uuid"},
                "username": {"type": "string"},
                "is_admin": {"type": "boolean"},
            }
        }
    }
)
class UserLoginView(TokenObtainPairView):
    """Вход пользователя"""
    serializer_class = UserLoginSerializer
    permission_classes = [permissions.AllowAny]


class UserProfileView(generics.RetrieveAPIView):
    """Получение профиля текущего пользователя"""
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


@extend_schema(responses={
    200: {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
        }
    }
})
class UserTokenVerifyView(TokenVerifyView):
    def post(self, request: Request, *args, **kwargs) -> Response:
        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            response.data['status'] = 'success'

        return response
