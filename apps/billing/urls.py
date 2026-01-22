from django.urls import path

from apps.billing.views import BalanceView


urlpatterns = [
    # Управление балансом
    path('balance/', BalanceView.as_view(), name='balance'),
    # path('balance/deposit/', DepositView.as_view(), name='deposit'),
    # path('admin/balance/deposit/', AdminDepositView.as_view(), name='admin_deposit'),
]
