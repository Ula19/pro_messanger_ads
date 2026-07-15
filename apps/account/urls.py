from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (UserRegistrationView, UserProfileView, UserLoginView, UserTokenVerifyView,
                    AdminUserListView, UserRoleUpdateView)



urlpatterns = [
    # Регистрация и аутентификация
    path('register/', UserRegistrationView.as_view(), name='register'),
    # Кастомный логин: кроме токенов отдаёт user_id, username и role (нужно фронтенду)
    path('login/', UserLoginView.as_view(), name='login'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('verify/', UserTokenVerifyView.as_view(), name='token_verify'),

    # Профиль пользователя
    path('profile/', UserProfileView.as_view(), name='profile'),

    # Управление пользователями (только суперадмин)
    path('users/', AdminUserListView.as_view(), name='users-list'),
    path('users/<uuid:user_id>/role/', UserRoleUpdateView.as_view(), name='user-role'),
]
