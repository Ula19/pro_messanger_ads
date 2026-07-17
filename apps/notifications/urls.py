from django.urls import path

from .views import (DeviceRegisterView, DeviceRemoveView, NotificationListView,
                    UnreadCountView, MarkReadView, MarkAllReadView)


urlpatterns = [
    # Устройства (FCM-токены)
    path('devices/', DeviceRegisterView.as_view(), name='device-register'),
    path('devices/remove/', DeviceRemoveView.as_view(), name='device-remove'),

    # Уведомления
    path('', NotificationListView.as_view(), name='notification-list'),
    path('unread_count/', UnreadCountView.as_view(), name='notification-unread-count'),
    path('<int:pk>/read/', MarkReadView.as_view(), name='notification-read'),
    path('read_all/', MarkAllReadView.as_view(), name='notification-read-all'),
]
