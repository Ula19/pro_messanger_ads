from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.pagination import StandardResultsSetPagination
from .models import ChannelEarning
from .serializers import (
    PublicEarningSerializer, MyEarningSerializer, ClaimRequestSerializer,
    WithdrawRequestSerializer, MessageSerializer,
)


class PublicEarningView(APIView):
    """
    «Крючок»: показать незарегистрированному владельцу, сколько уже накопил его канал.
    GET /api/partner/earnings/?channel_name=...
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=PublicEarningSerializer)
    def get(self, request):
        raw_name = request.query_params.get('channel_name', '')
        norm = ChannelEarning.normalize_name(raw_name)
        if not norm:
            return Response({'error': 'Укажите channel_name'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            earning = ChannelEarning.objects.get(channel_name=norm)
        except ChannelEarning.DoesNotExist:
            # Канал ещё ничего не заработал — отдаём нули, а не 404 (удобнее для витрины).
            return Response({
                'channel_name': norm,
                'total_earned': '0.0000',
                'total_impressions': 0,
                'is_claimed': False,
            }, status=status.HTTP_200_OK)

        return Response(PublicEarningSerializer(earning).data, status=status.HTTP_200_OK)


class ClaimChannelView(APIView):
    """
    Заявить права на канал-площадку. Подтверждает админ вручную (этап разработки).
    POST /api/partner/claim/  body: {"channel_name": "..."}
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ClaimRequestSerializer

    @extend_schema(request=ClaimRequestSerializer, responses=MessageSerializer)
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        norm = ChannelEarning.normalize_name(serializer.validated_data['channel_name'])
        if not norm:
            return Response({'error': 'Некорректное имя канала'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            earning, _ = ChannelEarning.objects.select_for_update().get_or_create(channel_name=norm)

            if earning.claim_status == ChannelEarning.ClaimStatus.CONFIRMED:
                if earning.owner_id == request.user.id:
                    return Response({'message': 'Этот канал уже закреплён за вами'}, status=status.HTTP_200_OK)
                return Response({'error': 'Канал уже закреплён за другим пользователем'},
                                status=status.HTTP_409_CONFLICT)

            if earning.claim_status == ChannelEarning.ClaimStatus.PENDING:
                if earning.pending_owner_id == request.user.id:
                    return Response({'message': 'Заявка уже подана и ожидает подтверждения'},
                                    status=status.HTTP_200_OK)
                return Response({'error': 'По каналу уже есть заявка от другого пользователя'},
                                status=status.HTTP_409_CONFLICT)

            earning.pending_owner = request.user
            earning.claim_status = ChannelEarning.ClaimStatus.PENDING
            earning.save(update_fields=['pending_owner', 'claim_status', 'updated_at'])

        return Response({'message': 'Заявка подана. Ожидайте подтверждения.'}, status=status.HTTP_201_CREATED)


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
    POST /api/partner/withdraw/  body: {"channel_name": "..."}
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = WithdrawRequestSerializer

    @extend_schema(request=WithdrawRequestSerializer, responses=MessageSerializer)
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        norm = ChannelEarning.normalize_name(serializer.validated_data['channel_name'])

        with transaction.atomic():
            try:
                earning = ChannelEarning.objects.select_for_update().get(
                    channel_name=norm, owner=request.user,
                    claim_status=ChannelEarning.ClaimStatus.CONFIRMED,
                )
            except ChannelEarning.DoesNotExist:
                return Response({'error': 'Канал не найден или не закреплён за вами'},
                                status=status.HTTP_404_NOT_FOUND)

            payout = earning.withdraw_to_balance()

        if payout <= 0:
            return Response({'message': 'Нет средств к выводу'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'message': f'Переведено на баланс: {payout}'}, status=status.HTTP_200_OK)
