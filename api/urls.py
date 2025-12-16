from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from .views import UserProfileView, UserLoginView, UserRegistrationView, CreateChannelOrderView, SearchChannelsView, \
    ChannelStatsView, OrderListView, ActiveOrderListView, ChannelOrderListView, BalanceView, DepositView, \
    CancelOrderView, UserTokenVerifyView

urlpatterns = [
    # Регистрация и аутентификация
    path('auth/register/', UserRegistrationView.as_view(), name='register'),
    path('auth/login/', UserLoginView.as_view(), name='login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/verify/', UserTokenVerifyView.as_view(), name='token_verify'),

    # Профиль пользователя
    path('auth/profile/', UserProfileView.as_view(), name='profile'),

    # Управление балансом
    path('balance/', BalanceView.as_view(), name='balance'),
    path('balance/deposit/', DepositView.as_view(), name='deposit'),

    # Создание канала и заказа
    path('channel_id-order/create/', CreateChannelOrderView.as_view(), name='create_channel_order'),

    # Отмена заказа
    path('orders/<int:order_id>/cancel/', CancelOrderView.as_view(), name='cancel_order'),

    # Поиск и показ рекламы
    path('search/', SearchChannelsView.as_view(), name='search-channels'),

    # Статистика канала
    path('stats/<str:channel_id>/', ChannelStatsView.as_view(), name='channel-stats'),

    # Списки заказов
    path('orders/all/', OrderListView.as_view(), name='all-orders'),
    path('orders/active/', ActiveOrderListView.as_view(), name='active-orders'),
    path('orders/channel/<str:channel_id>/', ChannelOrderListView.as_view(), name='channel-orders'),
]
