from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.pagination import StandardResultsSetPagination
from apps.common.schema import ERROR_RESPONSE, MESSAGE_RESPONSE

from .models import Device, Notification
from .serializers import (DeviceRegisterSerializer, DeviceRemoveSerializer,
                          NotificationSerializer)


# ============ Устройства (FCM-токены) ============

class DeviceRegisterView(APIView):
    """
    Регистрация FCM-токена устройства (приложение зовёт после логина
    и при обновлении токена). Идемпотентно: тот же токен не дублируется,
    при релогине на том же устройстве токен переезжает к новому юзеру.
    """
    serializer_class = DeviceRegisterSerializer

    @extend_schema(request=DeviceRegisterSerializer, responses={200: MESSAGE_RESPONSE})
    def post(self, request):
        serializer = DeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        Device.objects.update_or_create(
            token=serializer.validated_data['token'],
            defaults={
                'user': request.user,
                'platform': serializer.validated_data['platform'],
                'is_active': True,  # токен вернулся живым — включаем обратно
            },
        )
        return Response({'message': 'Устройство зарегистрировано'}, status=status.HTTP_200_OK)


class DeviceRemoveView(APIView):
    """Отвязка токена при логауте. Идемпотентно: нет токена — тоже 200"""
    serializer_class = DeviceRemoveSerializer

    @extend_schema(request=DeviceRemoveSerializer, responses={200: MESSAGE_RESPONSE})
    def post(self, request):
        serializer = DeviceRemoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Удаляем только свою запись — чужой токен трогать нельзя
        Device.objects.filter(token=serializer.validated_data['token'],
                              user=request.user).delete()
        return Response({'message': 'Устройство отвязано'}, status=status.HTTP_200_OK)


# ============ Уведомления (экран в приложении) ============

class NotificationListView(generics.ListAPIView):
    """Уведомления юзера, новые первыми"""
    serializer_class = NotificationSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return self.request.user.notifications.all()


class UnreadCountView(APIView):
    """Счётчик непрочитанных для бейджа — фронт поллит, как pending_count"""

    @extend_schema(responses={200: {
        'type': 'object',
        'properties': {'unread': {'type': 'integer'}},
    }})
    def get(self, request):
        unread = request.user.notifications.filter(is_read=False).count()
        return Response({'unread': unread}, status=status.HTTP_200_OK)


class MarkReadView(APIView):
    """Отметить одно уведомление прочитанным"""

    @extend_schema(request=None, responses={200: MESSAGE_RESPONSE, 404: ERROR_RESPONSE})
    def post(self, request, pk):
        # filter+update вместо get: чужое уведомление неотличимо от несуществующего (404)
        updated = Notification.objects.filter(pk=pk, user=request.user).update(is_read=True)
        if not updated:
            return Response({'error': 'Уведомление не найдено'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'message': 'Прочитано'}, status=status.HTTP_200_OK)


class MarkAllReadView(APIView):
    """Отметить все уведомления юзера прочитанными"""

    @extend_schema(request=None, responses={200: MESSAGE_RESPONSE})
    def post(self, request):
        request.user.notifications.filter(is_read=False).update(is_read=True)
        return Response({'message': 'Все уведомления прочитаны'}, status=status.HTTP_200_OK)
