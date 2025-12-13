from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Channel


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'user_id', 'is_staff')
    search_fields = ('username', 'email', 'user_id')
    readonly_fields = ('user_id',)


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ('name', 'channel_id', 'user', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'channel_id', 'order_name')
    readonly_fields = ('created_at', 'updated_at')
