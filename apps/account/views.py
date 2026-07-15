from drf_spectacular.utils import extend_schema
from rest_framework import filters, generics, permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenVerifyView
from django.contrib.auth import get_user_model

from apps.common.pagination import StandardResultsSetPagination
from apps.common.permissions import IsSuperAdmin
from apps.account.serializers import (UserRegistrationSerializer, UserLoginSerializer, UserProfileSerializer,
                                      AdminUserSerializer, UserRoleUpdateSerializer)



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
                "role": {"type": "string"},
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


class AdminUserListView(generics.ListAPIView):
    """
    Список пользователей для суперадмина.
    Поиск по username/email через ?search=, нужен для назначения ролей и пополнения баланса.
    """
    serializer_class = AdminUserSerializer
    permission_classes = [IsSuperAdmin]
    pagination_class = StandardResultsSetPagination
    queryset = User.objects.select_related('balance').order_by('username')
    filter_backends = [filters.SearchFilter]
    search_fields = ['username', 'email']


class UserRoleUpdateView(generics.GenericAPIView):
    """
    Смена роли пользователя (рекламодатель/модератор).
    Доступно только суперадмину.
    """
    serializer_class = UserRoleUpdateSerializer
    permission_classes = [IsSuperAdmin]

    @extend_schema(
        request=UserRoleUpdateSerializer,
        responses={
            200: {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "user_id": {"type": "string", "format": "uuid"},
                    "role": {"type": "string"},
                }
            }
        }
    )
    def post(self, request, user_id):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = User.objects.get(user_id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'Пользователь не найден'}, status=status.HTTP_404_NOT_FOUND)

        user.role = serializer.validated_data['role']
        user.save(update_fields=['role'])

        return Response({
            'message': f'Роль пользователя {user.username} изменена на {user.get_role_display()}',
            'user_id': str(user.user_id),
            'role': user.role,
        }, status=status.HTTP_200_OK)
