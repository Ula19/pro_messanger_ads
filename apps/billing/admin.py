from django.contrib import admin

from apps.billing.models import Balance


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
