from django.contrib import admin

from .models import Device, Notification


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['user', 'platform', 'is_active', 'created_at', 'last_used']
    list_filter = ['platform', 'is_active']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['token', 'created_at', 'last_used']

    def has_add_permission(self, request):
        # Токены регистрирует только само приложение через API
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'type', 'title', 'is_read', 'created_at']
    list_filter = ['type', 'is_read']
    search_fields = ['user__username', 'title', 'body']
    readonly_fields = ['user', 'title', 'body', 'type', 'payload', 'is_read', 'created_at']

    def has_add_permission(self, request):
        # Уведомления создаёт только код (services.notify)
        return False
