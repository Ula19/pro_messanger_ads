from django.urls import path

from .views import (PendingSearchAdsListView, PendingChatAdsListView, PendingCountView,
                    ModerationDecisionView)


urlpatterns = [
    # Очереди на модерацию (по типам рекламы)
    path('search_ads/pending/', PendingSearchAdsListView.as_view(), name='moderation-search-pending'),
    path('chat_ads/pending/', PendingChatAdsListView.as_view(), name='moderation-chat-pending'),

    # Счётчик для бейджа (фронт поллит)
    path('pending_count/', PendingCountView.as_view(), name='moderation-pending-count'),

    # Решения модератора; order_type — search_ads или chat_ads
    path('<str:order_type>/<uuid:order_id>/approve/', ModerationDecisionView.as_view(),
         {'action': 'approve'}, name='moderation-approve'),
    path('<str:order_type>/<uuid:order_id>/reject/', ModerationDecisionView.as_view(),
         {'action': 'reject'}, name='moderation-reject'),
    path('<str:order_type>/<uuid:order_id>/block/', ModerationDecisionView.as_view(),
         {'action': 'block'}, name='moderation-block'),
]
