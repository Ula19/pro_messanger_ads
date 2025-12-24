from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from api.views.auth_views import UserRegistrationView, UserProfileView, UserLoginView, UserTokenVerifyView
from api.views.balance_views import BalanceView
from api.views.search_views import SearchChannelsView
from api.views.orders_views import OrderListView, ActiveOrderListView, OrderActivationView, OrderDetailView, \
    CancelOrderView, CreateChannelOrderView



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
    # path('balance/deposit/', DepositView.as_view(), name='deposit'),
    # path('admin/balance/deposit/', AdminDepositView.as_view(), name='admin_deposit'),
    # Создание канала и заказа
    path('channel_id-order/create/', CreateChannelOrderView.as_view(), name='create_channel_order'),

    # Отмена заказа
    path('orders/<int:order_id>/cancel/', CancelOrderView.as_view(), name='cancel_order'),

    # Списки заказов
    path('orders/<int:order_id>/', OrderDetailView.as_view(), name='order-detail'),
    path('orders/all/', OrderListView.as_view(), name='all-orders'),
    path('orders/active/', ActiveOrderListView.as_view(), name='active-orders'),
    path('orders/status/', OrderActivationView.as_view(), name='order_activation'),

    # Поиск каналов по тегу
    path('search/', SearchChannelsView.as_view(), name='search-channels'),
]
