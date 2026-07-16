from django.db.models import Count, F
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.pagination import StandardResultsSetPagination
from apps.common.permissions import HasServerApiKey, IsSuperAdmin
from apps.common.schema import ERROR_RESPONSE, MESSAGE_RESPONSE, SERVER_API_KEY_AUTH

from .models import Announcement, AnnouncementDismissal
from .serializers import (AnnouncementClientSerializer, AnnouncementManageSerializer,
                          ActiveAnnouncementsRequestSerializer, DismissRequestSerializer,
                          ClickRequestSerializer)


# ============ Управление баннерами (только суперадмин) ============

class AnnouncementManageListCreateView(generics.ListCreateAPIView):
    """
    GET — все баннеры со статистикой (клики, закрытия), POST — создать баннер.
    Только суперадмин.
    """
    serializer_class = AnnouncementManageSerializer
    permission_classes = [IsSuperAdmin]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return (Announcement.objects
                .annotate(dismissals_count_agg=Count('dismissals'))
                .select_related('created_by')
                .order_by('-created_at'))

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AnnouncementManageDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH/DELETE конкретного баннера. Только суперадмин.
    Штатный способ снять баннер — PATCH is_active=false (статистика останется).
    DELETE удаляет насовсем вместе с записями о закрытиях — для мусора.
    """
    serializer_class = AnnouncementManageSerializer
    permission_classes = [IsSuperAdmin]
    http_method_names = ['get', 'patch', 'delete']  # PUT не нужен

    def get_queryset(self):
        return (Announcement.objects
                .annotate(dismissals_count_agg=Count('dismissals'))
                .select_related('created_by'))


# ============ Выдача баннеров NovaGram (server-to-server) ============

class ActiveAnnouncementsView(APIView):
    """
    Активные баннеры для юзера (не закрытые им, в окне дат).
    Клиент показывает первый из списка; юзер закрыл — появится следующий.
    """
    serializer_class = ActiveAnnouncementsRequestSerializer
    permission_classes = [HasServerApiKey]  # только запросы с сервера NovaGram (по API-ключу)
    throttle_classes = []  # доверенный сервер (server-to-server), глобальный троттл не нужен

    @extend_schema(request=ActiveAnnouncementsRequestSerializer, auth=SERVER_API_KEY_AUTH,
                   responses=AnnouncementClientSerializer(many=True))
    def post(self, request):
        serializer = ActiveAnnouncementsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        viewer_id = serializer.validated_data['viewer_id'].strip()

        announcements = Announcement.visible_for(viewer_id)
        return Response(AnnouncementClientSerializer(announcements, many=True).data,
                        status=status.HTTP_200_OK)


class DismissAnnouncementView(APIView):
    """
    Юзер закрыл баннер крестиком — больше ему не показываем.
    Идемпотентно: повторное закрытие — тоже 200.
    """
    serializer_class = DismissRequestSerializer
    permission_classes = [HasServerApiKey]
    throttle_classes = []

    @extend_schema(request=DismissRequestSerializer, auth=SERVER_API_KEY_AUTH, responses={
        200: MESSAGE_RESPONSE,
        400: ERROR_RESPONSE,  # баннер незакрываемый (dismissible=false)
        404: ERROR_RESPONSE,  # баннер не найден (мог быть удалён — клиенту просто игнорировать)
    })
    def post(self, request):
        serializer = DismissRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        viewer_id = serializer.validated_data['viewer_id'].strip()

        try:
            announcement = Announcement.objects.get(pk=serializer.validated_data['announcement_id'])
        except Announcement.DoesNotExist:
            return Response({'error': 'Баннер не найден'}, status=status.HTTP_404_NOT_FOUND)

        if not announcement.dismissible:
            return Response({'error': 'Этот баннер нельзя закрыть'}, status=status.HTTP_400_BAD_REQUEST)

        # Закрытие выключенного/просроченного баннера тоже принимаем — клиент мог
        # прислать его с задержкой. get_or_create + unique_together сами разруливают
        # гонку двух одновременных закрытий, лок не нужен
        AnnouncementDismissal.objects.get_or_create(announcement=announcement, viewer_id=viewer_id)
        return Response({'message': 'Баннер закрыт'}, status=status.HTTP_200_OK)


class ClickAnnouncementView(APIView):
    """
    Клик по баннеру — счётчик для статистики своей рекламы.
    Считаем даже по выключенному баннеру: клик мог прийти с задержкой.
    """
    serializer_class = ClickRequestSerializer
    permission_classes = [HasServerApiKey]
    throttle_classes = []

    @extend_schema(request=ClickRequestSerializer, auth=SERVER_API_KEY_AUTH, responses={
        200: MESSAGE_RESPONSE,
        404: ERROR_RESPONSE,  # баннер не найден
    })
    def post(self, request):
        serializer = ClickRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Атомарный UPDATE ... SET clicks = clicks + 1 — без гонок и без лока
        updated = Announcement.objects.filter(
            pk=serializer.validated_data['announcement_id']
        ).update(clicks=F('clicks') + 1)

        if not updated:
            return Response({'error': 'Баннер не найден'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'message': 'Клик засчитан'}, status=status.HTTP_200_OK)
