from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Channel, Order, Balance, AdView, Tag


@admin.register(CustomUser)
class UserAdmin(UserAdmin):
    list_display = ('username', 'user_id', 'is_admin')
    search_fields = ('username', 'user_id')
    list_per_page = 20
    search_help_text = 'USERNAME ni yoki USER ID ni kiritng'


@admin.register(Balance)
class BalanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'add_amount')
    list_editable = ('add_amount',)
    list_per_page = 20
    ordering = ('amount',)
    # readonly_fields = ('user',)
    search_fields = ('user__username', 'user__user_id',)
    search_help_text = 'USERNAME ni yoki USER ID ni kiritng'

    def save_model(self, request, obj, form, change):
        """
        Если админ ввёл add_amount — прибавляем к балансу
        """
        if obj.add_amount and obj.add_amount > 0:
            obj.amount += obj.add_amount

        # ОБЯЗАТЕЛЬНО обнуляем, иначе будет повторное пополнение
        obj.add_amount = None

        super().save_model(request, obj, form, change)


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
                    'shown_views', 'completed', 'is_active')
    ordering = ('-is_active', '-created_at', 'spm')
    search_fields = ('order_name', 'channel_name', 'user__username')
    readonly_fields = ('created_at', 'updated_at')
    search_help_text = 'ORDER_NAME ni, CHANNEL_NAME ni yoki USERNAME ni kiritng'
    list_per_page = 30



