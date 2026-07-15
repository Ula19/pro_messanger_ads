from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.account.models import CustomUser


@admin.register(CustomUser)
class UserAdmin(UserAdmin):
    list_display = ('username', 'user_id', 'telegram_id', 'role')
    list_filter = ('role', 'is_superuser', 'is_active')
    search_fields = ('username', 'user_id', 'telegram_id')
    list_per_page = 20
    search_help_text = 'USERNAME ni yoki USER ID ni kiritng'

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'telegram_id')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'role', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    # Поля при создании пользователя
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'role', 'is_staff', 'is_active'),
        }),
    )
