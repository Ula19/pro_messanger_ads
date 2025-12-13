from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from .views import (
    CreateChannelView,
    UserProfileView,
    CustomTokenObtainPairView
)

urlpatterns = [
    path('profile/', UserProfileView.as_view(), name='user_profile'),
    path('channels/create/', CreateChannelView.as_view(), name='create_channel'),

    path('auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/verify/', TokenVerifyView.as_view(), name='token_verify'),
]
