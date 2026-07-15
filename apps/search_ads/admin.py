from django.contrib import admin
from django.db import transaction

from .models import Channel, Order, AdView, Tag



@admin.register(Tag)
class UserAdmin(admin.ModelAdmin):
    list_display = ('name',)


@admin.register(AdView)
class UserAdmin(admin.ModelAdmin):
    list_display = ('viewer_id', 'order__order_name', 'order__channel_name', 'view_count',)
    search_fields = ('order__order_name', 'order__channel_name', 'viewer_id__iexact')
    ordering = ('-view_count',)
    list_per_page = 30

@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ('channel_id', 'channel_name', 'user__username', )
    search_fields = ('channel_name', 'channel_id', 'user__username')
    readonly_fields = ('created_at', 'updated_at')
    search_help_text = 'CHANNEL_NAME ni, USERNAME ni yoki CHANNEL__ID ni kiritng'
    list_per_page = 20


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_name', 'channel_name', 'user__username', 'spm', 'budget', 'total_views',
                    'shown_views', 'status', 'completed', 'is_active')
    list_filter = ('status', 'is_active', 'cancelled', 'completed')
    ordering = ('-is_active', '-created_at', 'spm')
    search_fields = ('order_name', 'channel_name', 'user__username', 'platform')
    # Статус, флаги жизненного цикла и денежные поля руками в админке не меняем —
    # иначе можно обойти возврат денег (например, реанимировать отменённый заказ,
    # по которому деньги уже вернули). Для решений есть API модерации (или action «Одобрить»)
    readonly_fields = ('status', 'moderated_by', 'moderated_at', 'is_active', 'cancelled',
                       'completed', 'remaining_views', 'shown_views', 'total_views',
                       'budget', 'spm', 'created_at', 'updated_at')
    search_help_text = 'ORDER_NAME ni, CHANNEL_NAME ni yoki USERNAME ni kiritng'
    list_per_page = 30
    actions = ['approve_orders']

    def has_add_permission(self, request):
        # Заказы создаются только через API — там списываются деньги с баланса.
        # Заказ, добавленный из админки, был бы «бесплатным», а его отклонение
        # вернуло бы юзеру бюджет, который никогда не списывался
        return False

    @admin.action(description='Одобрить выбранные заказы (на модерации)')
    def approve_orders(self, request, queryset):
        approved = 0
        with transaction.atomic():
            # Лок на строки, чтобы не разъехаться с параллельной модерацией через API
            for order in queryset.select_for_update():
                # Свой заказ модерировать нельзя (как и в API), суперадмину можно
                if order.user_id == request.user.id and not request.user.is_superuser:
                    continue
                if order.approve(request.user):
                    approved += 1
        self.message_user(request, f'Одобрено заказов: {approved}')



