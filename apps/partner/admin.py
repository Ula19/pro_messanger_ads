from django.contrib import admin, messages

from .models import ChannelEarning, EarningTransaction


@admin.register(ChannelEarning)
class ChannelEarningAdmin(admin.ModelAdmin):
    list_display = (
        'channel_name', 'claim_status', 'owner', 'pending_owner',
        'available', 'total_earned', 'total_impressions', 'share_rate',
    )
    list_filter = ('claim_status',)
    search_fields = ('channel_name', 'owner__username', 'pending_owner__username')
    readonly_fields = ('available', 'total_earned', 'total_impressions', 'claimed_at', 'created_at', 'updated_at')
    actions = ('confirm_claims',)

    @admin.action(description='Подтвердить заявку на канал (привязать заявителя как владельца)')
    def confirm_claims(self, request, queryset):
        confirmed = 0
        for earning in queryset:
            if earning.pending_owner and earning.claim_status == ChannelEarning.ClaimStatus.PENDING:
                earning.confirm_claim()
                confirmed += 1
        if confirmed:
            self.message_user(request, f'Подтверждено заявок: {confirmed}', level=messages.SUCCESS)
        else:
            self.message_user(request, 'Нет заявок в статусе «ожидает подтверждения»', level=messages.WARNING)


@admin.register(EarningTransaction)
class EarningTransactionAdmin(admin.ModelAdmin):
    list_display = ('channel', 'kind', 'amount', 'impressions', 'order', 'updated_at')
    list_filter = ('kind',)
    search_fields = ('channel__channel_name',)
    readonly_fields = ('channel', 'order', 'kind', 'amount', 'impressions', 'created_at', 'updated_at')
