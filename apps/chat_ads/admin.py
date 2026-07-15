from django.contrib import admin
from django.db import transaction

from .models import ChatAdMedia, ChatAdOrder, ChatAdView


@admin.register(ChatAdMedia)
class ChatAdMediaAdmin(admin.ModelAdmin):
    list_display = ['media_type', 'user__username', 'file', 'is_linked']
    search_fields = ['user__username', 'media_type']
    search_help_text = 'Поиск по username и media_type'
    list_per_page = 30


@admin.register(ChatAdOrder)
class ChatAdOrderAdmin(admin.ModelAdmin):
    list_display = ['order_name', 'user__username', 'channels', 'spm', 'budget', 'total_views', 'shown_views',
                    'status', 'cancelled', 'is_active']
    list_filter = ['status', 'is_active', 'cancelled', 'completed']
    search_fields = ['order_name', 'channels', 'user__username']
    search_help_text = 'Поиск по order_name, channels и username'
    ordering = ['-is_active', '-created_at', 'spm']
    # Статус, флаги жизненного цикла и денежные поля руками в админке не меняем —
    # иначе можно обойти возврат денег (например, реанимировать отменённый заказ,
    # по которому деньги уже вернули). Для решений есть API модерации (или action «Одобрить»)
    readonly_fields = ['status', 'moderated_by', 'moderated_at', 'is_active', 'cancelled',
                       'completed', 'remaining_views', 'shown_views', 'total_views',
                       'budget', 'spm', 'created_at', 'updated_at']
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


@admin.register(ChatAdView)
class ChatAdViewAdmin(admin.ModelAdmin):
    list_display = ['viewer_id', 'order__order_name', 'order__channels', 'view_count']
    search_fields = ('order__order_name', 'order__channels', 'viewer_id__iexact')
    search_help_text = "Поиск по order_name, channels и viewer_id"
    ordering = ('-view_count',)
    list_per_page = 30
