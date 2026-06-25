from django.urls import path

from .views import PublicEarningView, ClaimChannelView, MyEarningsView, WithdrawEarningView

urlpatterns = [
    path('earnings/', PublicEarningView.as_view(), name='partner-public-earnings'),
    path('claim/', ClaimChannelView.as_view(), name='partner-claim'),
    path('my/', MyEarningsView.as_view(), name='partner-my-earnings'),
    path('withdraw/', WithdrawEarningView.as_view(), name='partner-withdraw'),
]
