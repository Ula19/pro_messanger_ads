from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenObtainPairView

from .views import UserRegistrationView, UserProfileView, UserLoginView, UserTokenVerifyView



urlpatterns = [
    # Регистрация и аутентификация
    path('register/', UserRegistrationView.as_view(), name='register'),
    path('login/', TokenObtainPairView.as_view(), name='login'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('verify/', UserTokenVerifyView.as_view(), name='token_verify'),

    # Профиль пользователя
    path('profile/', UserProfileView.as_view(), name='profile'),
]
