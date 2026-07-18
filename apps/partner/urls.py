from django.urls import path

from .views import (PublicEarningView, ClaimChannelView, MyEarningsView,
                    WithdrawEarningView, AdminEarningsListView)

urlpatterns = [
    path('earnings/', PublicEarningView.as_view(), name='partner-public-earnings'),
    path('admin/earnings/', AdminEarningsListView.as_view(), name='partner-admin-earnings'),
    path('claim/', ClaimChannelView.as_view(), name='partner-claim'),
    path('my/', MyEarningsView.as_view(), name='partner-my-earnings'),
    path('withdraw/', WithdrawEarningView.as_view(), name='partner-withdraw'),
]
