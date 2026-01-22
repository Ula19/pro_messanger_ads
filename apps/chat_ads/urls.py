from django.urls import path

from .views import ChatAdOrderCreateView, ChatAdOrderListView, ChatAdOrderDetailView, ChatAdActiveOrderListView, \
    ChatAdCancelOrderView, ChatAdMediaUploadView


urlpatterns = [
    path('order/add_media/', ChatAdMediaUploadView.as_view()),
    path('order/create/', ChatAdOrderCreateView.as_view()),
    path('orders/all/', ChatAdOrderListView.as_view()),
    path('order/<uuid:order_id>/detail/', ChatAdOrderDetailView.as_view()),
    path('orders/active/', ChatAdActiveOrderListView.as_view()),
    path('order/<uuid:order_id>/cancel/', ChatAdCancelOrderView.as_view(), name='cancel_order'),
]
