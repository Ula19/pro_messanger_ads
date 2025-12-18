from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Channel, Order, Balance, AdView


# @admin.register(CustomUser)
# class CustomUserAdmin(UserAdmin):
#     list_display = ('username', 'email', 'user_id', 'is_staff', 'is_admin', 'date_joined')
#     search_fields = ('username', 'email', 'user_id')
#     readonly_fields = ('user_id', 'date_joined')

@admin.register(CustomUser)
class UserAdmin(admin.ModelAdmin):
    pass

@admin.register(AdView)
class UserAdmin(admin.ModelAdmin):
    pass

@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    pass
    # list_display = ('channel_name', 'channel_id', 'user', 'created_at')
    # list_filter = ('created_at',)
    # search_fields = ('channel_name', 'channel_id')
    # readonly_fields = ('created_at', 'updated_at')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    pass
    # list_display = ('order_name', 'channel_name', 'created_at')
    # search_fields = ('order_name', 'channel_name', 'channel_id')
    # readonly_fields = ('created_at', 'updated_at')


@admin.register(Balance)
class CustomUserAdmin(admin.ModelAdmin):
    pass
