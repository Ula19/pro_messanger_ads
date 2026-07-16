from django.db import transaction
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.pagination import StandardResultsSetPagination
from apps.common.schema import ERROR_RESPONSE, MESSAGE_RESPONSE
from .models import ChannelEarning
from .serializers import (
    PublicEarningSerializer, MyEarningSerializer, ClaimRequestSerializer,
    WithdrawRequestSerializer, MessageSerializer,
)


class PublicEarningView(APIView):
    """
    «Крючок»: показать незарегистрированному владельцу, сколько уже накопил его канал.
    GET /api/partner/earnings/?channel_id=...
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter(name='channel_id', type=int, required=True,
                                     description='Числовой id канала-площадки в Telegram')],
        responses={
            200: PublicEarningSerializer,
            400: ERROR_RESPONSE,  # channel_id не передан или не число
        },
    )
    def get(self, request):
        raw_id = request.query_params.get('channel_id', '')
        try:
            channel_id = int(raw_id)
        except (TypeError, ValueError):
            return Response({'error': 'Укажите числовой channel_id'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            earning = ChannelEarning.objects.get(channel_id=channel_id)
        except ChannelEarning.DoesNotExist:
            # Канал ещё ничего не заработал — отдаём нули, а не 404 (удобнее для витрины).
            return Response({
                'channel_id': channel_id,
                'channel_name': '',
                'total_earned': '0.0000',
                'total_impressions': 0,
                'is_claimed': False,
            }, status=status.HTTP_200_OK)

        return Response(PublicEarningSerializer(earning).data, status=status.HTTP_200_OK)


class ClaimChannelView(APIView):
    """
    Заявить права на канал-площадку. Доверяем клиенту (он подтвердил владение
    на стороне Telegram) — закрепляем сразу.
    POST /api/partner/claim/  body: {"channel_id": 123, "channel_name": "..."}
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ClaimRequestSerializer

    @extend_schema(request=ClaimRequestSerializer, responses={
        201: MessageSerializer,   # канал успешно закреплён
        200: MessageSerializer,   # канал уже был закреплён за вами
        409: ERROR_RESPONSE,      # канал закреплён за другим пользователем
    })
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel_id = serializer.validated_data['channel_id']
        norm_name = ChannelEarning.normalize_name(serializer.validated_data.get('channel_name'))

        with transaction.atomic():
            earning, _ = ChannelEarning.objects.select_for_update().get_or_create(channel_id=channel_id)

            if earning.claim_status == ChannelEarning.ClaimStatus.CONFIRMED:
                if earning.owner_id == request.user.id:
                    return Response({'message': 'Этот канал уже закреплён за вами'}, status=status.HTTP_200_OK)
                return Response({'error': 'Канал уже закреплён за другим пользователем'},
                                status=status.HTTP_409_CONFLICT)

            if norm_name and norm_name != earning.channel_name:
                earning.channel_name = norm_name
            earning.claim_by(request.user)

        return Response({'message': 'Канал закреплён за вами'}, status=status.HTTP_201_CREATED)


class MyEarningsView(generics.ListAPIView):
    """Список каналов и заработка текущего пользователя (подтверждённые за ним)."""
    serializer_class = MyEarningSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return ChannelEarning.objects.filter(owner=self.request.user)


class WithdrawEarningView(APIView):
    """
    Перевести доступный заработок канала на рекламный баланс.
    POST /api/partner/withdraw/  body: {"channel_id": 123}
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = WithdrawRequestSerializer

    @extend_schema(request=WithdrawRequestSerializer, responses={
        200: MessageSerializer,   # переведено на баланс
        400: MESSAGE_RESPONSE,    # нет средств к выводу
        404: ERROR_RESPONSE,      # канал не найден или не закреплён за вами
    })
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel_id = serializer.validated_data['channel_id']

        with transaction.atomic():
            try:
                earning = ChannelEarning.objects.select_for_update().get(
                    channel_id=channel_id, owner=request.user,
                    claim_status=ChannelEarning.ClaimStatus.CONFIRMED,
                )
            except ChannelEarning.DoesNotExist:
                return Response({'error': 'Канал не найден или не закреплён за вами'},
                                status=status.HTTP_404_NOT_FOUND)

            payout = earning.withdraw_to_balance()

        if payout <= 0:
            return Response({'message': 'Нет средств к выводу'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'message': f'Переведено на баланс: {payout}'}, status=status.HTTP_200_OK)
