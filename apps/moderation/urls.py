from django.urls import path

from .views import (PendingSearchAdsListView, PendingChatAdsListView, PendingCountView,
                    ApproveOrderView, RejectOrderView, BlockOrderView,
                    AllSearchAdsListView, AllChatAdsListView)


urlpatterns = [
    # Очереди на модерацию (по типам рекламы)
    path('search_ads/pending/', PendingSearchAdsListView.as_view(), name='moderation-search-pending'),
    path('chat_ads/pending/', PendingChatAdsListView.as_view(), name='moderation-chat-pending'),

    # Все заказы всех юзеров для админ-панели (только суперадмин)
    path('search_ads/all/', AllSearchAdsListView.as_view(), name='moderation-search-all'),
    path('chat_ads/all/', AllChatAdsListView.as_view(), name='moderation-chat-all'),

    # Счётчик для бейджа (фронт поллит)
    path('pending_count/', PendingCountView.as_view(), name='moderation-pending-count'),

    # Решения модератора; order_type — search_ads или chat_ads
    path('<str:order_type>/<uuid:order_id>/approve/', ApproveOrderView.as_view(), name='moderation-approve'),
    path('<str:order_type>/<uuid:order_id>/reject/', RejectOrderView.as_view(), name='moderation-reject'),
    path('<str:order_type>/<uuid:order_id>/block/', BlockOrderView.as_view(), name='moderation-block'),
]
