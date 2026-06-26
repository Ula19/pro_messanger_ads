from django.contrib import admin, messages

from .models import ChannelEarning, EarningTransaction


@admin.register(ChannelEarning)
class ChannelEarningAdmin(admin.ModelAdmin):
    list_display = (
        'channel_id', 'channel_name', 'claim_status', 'owner',
        'available', 'total_earned', 'total_impressions', 'share_rate',
    )
    list_filter = ('claim_status',)
    search_fields = ('channel_id', 'channel_name', 'owner__username')
    readonly_fields = ('available', 'total_earned', 'total_impressions', 'claimed_at', 'created_at', 'updated_at')
    actions = ('release_claims',)

    @admin.action(description='Снять закрепление канала (сделать свободным)')
    def release_claims(self, request, queryset):
        updated = queryset.update(
            owner=None,
            claim_status=ChannelEarning.ClaimStatus.UNCLAIMED,
            claimed_at=None,
        )
        self.message_user(request, f'Освобождено каналов: {updated}', level=messages.SUCCESS)


@admin.register(EarningTransaction)
class EarningTransactionAdmin(admin.ModelAdmin):
    list_display = ('channel', 'kind', 'amount', 'impressions', 'order', 'updated_at')
    list_filter = ('kind',)
    search_fields = ('channel__channel_id', 'channel__channel_name')
    readonly_fields = ('channel', 'order', 'kind', 'amount', 'impressions', 'created_at', 'updated_at')
