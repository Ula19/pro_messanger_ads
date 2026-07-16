from django.urls import path

from .views import (AnnouncementManageListCreateView, AnnouncementManageDetailView,
                    ActiveAnnouncementsView, DismissAnnouncementView, ClickAnnouncementView)


urlpatterns = [
    # Управление баннерами (только суперадмин)
    path('manage/', AnnouncementManageListCreateView.as_view(), name='announcement-manage-list'),
    path('manage/<uuid:pk>/', AnnouncementManageDetailView.as_view(), name='announcement-manage-detail'),

    # Выдача баннеров серверу NovaGram (по API-ключу)
    path('active/', ActiveAnnouncementsView.as_view(), name='announcement-active'),
    path('dismiss/', DismissAnnouncementView.as_view(), name='announcement-dismiss'),
    path('click/', ClickAnnouncementView.as_view(), name='announcement-click'),
]
