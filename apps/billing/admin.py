from django import forms
from django.contrib import admin, messages
from django.db.models import F
from django.utils import timezone

from apps.billing.models import Balance


class BalanceAdminForm(forms.ModelForm):
    """
    Форма баланса с «замком»: в скрытом поле запоминаем, каким админ видел
    баланс при открытии формы. Пополнение применится, только если баланс
    с тех пор не изменился — это защита от двойного клика по «Сохранить»
    (иначе пополнение задвоится) и от гонки с параллельными возвратами.
    """
    expected_amount = forms.DecimalField(widget=forms.HiddenInput, required=False,
                                         max_digits=15, decimal_places=2)

    class Meta:
        model = Balance
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['expected_amount'].initial = self.instance.amount


@admin.register(Balance)
class BalanceAdmin(admin.ModelAdmin):
    form = BalanceAdminForm
    list_display = ('user', 'amount', 'updated_at')
    list_per_page = 20
    ordering = ('amount',)
    # Баланс руками не правим — только пополнение через add_amount
    readonly_fields = ('amount',)
    search_fields = ('user__username', 'user__user_id',)
    search_help_text = 'USERNAME ni yoki USER ID ni kiritng'

    # Балансы пользователей может трогать только суперадмин
    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_readonly_fields(self, request, obj=None):
        # Владельца существующего баланса не меняем (OneToOne к юзеру)
        if obj:
            return ('amount', 'user')
        return ('amount',)

    def save_model(self, request, obj, form, change):
        """
        Если админ ввёл add_amount — прибавляем к балансу F-выражением прямо
        в базе (не затирая параллельные возвраты/списания), и только при
        совпадении amount с тем, что админ видел в форме (см. BalanceAdminForm).
        """
        add = obj.add_amount or 0
        expected = form.cleaned_data.get('expected_amount')

        if not change:
            # Новая запись баланса (редкий случай) — сначала создаём её
            obj.add_amount = None
            super().save_model(request, obj, form, change)

        if add > 0:
            queryset = Balance.objects.filter(pk=obj.pk)
            if expected is not None:
                # «Замок»: пополняем только если баланс не изменился с момента открытия формы
                queryset = queryset.filter(amount=expected)
            updated = queryset.update(
                amount=F('amount') + add,
                add_amount=None,
                updated_at=timezone.now(),
            )
            if updated:
                self.message_user(request, f'Баланс пополнен на {add}')
            else:
                self.message_user(
                    request,
                    'Баланс изменился с момента открытия формы — пополнение НЕ применено. '
                    'Обновите страницу, проверьте сумму и повторите.',
                    level=messages.WARNING,
                )
        elif change:
            # Пополнения нет — просто сбрасываем add_amount, не переписывая amount
            Balance.objects.filter(pk=obj.pk).update(add_amount=None)
