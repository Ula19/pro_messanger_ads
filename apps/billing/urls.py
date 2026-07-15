from django.urls import path

from apps.billing.views import BalanceView, AdminDepositView


urlpatterns = [
    # Управление балансом
    path('balance/', BalanceView.as_view(), name='balance'),
    # Пополнение баланса пользователя (только суперадмин)
    path('admin/balance/deposit/', AdminDepositView.as_view(), name='admin_deposit'),
]
