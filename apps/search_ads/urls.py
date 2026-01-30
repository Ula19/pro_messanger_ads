from django.urls import path

from apps.search_ads.views.search_views import SearchChannelsView, ClickView
from apps.search_ads.views.orders_views import OrderListView, ActiveOrderListView, OrderActivationView, OrderDetailView, \
    CancelOrderView, CreateChannelOrderView



urlpatterns = [
    # Списки заказов
    path('order/create/', CreateChannelOrderView.as_view(), name='create_channel_order'),
    path('orders/all/', OrderListView.as_view(), name='all-orders'),
    path('orders/active/', ActiveOrderListView.as_view(), name='active-orders'),
    path('order/change_status/', OrderActivationView.as_view(), name='order_activation'),
    path('order/<uuid:order_id>/detail/', OrderDetailView.as_view(), name='order-detail'),
    path('order/<uuid:order_id>/cancel/', CancelOrderView.as_view(), name='cancel_order'),

    # Поиск каналов по тегу
    path('order/search/', SearchChannelsView.as_view(), name='search-channels'),
    path('order/click/', ClickView.as_view(), name='click'),
]
