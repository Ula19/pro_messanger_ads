from django.contrib import admin

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
                    'cancelled', 'is_active']
    search_fields = ['order_name', 'channels', 'user__username']
    search_help_text = 'Поиск по order_name, channels и username'
    ordering = ['-is_active', '-created_at', 'spm']
    list_per_page = 30


@admin.register(ChatAdView)
class ChatAdViewAdmin(admin.ModelAdmin):
    list_display = ['viewer_id', 'order__order_name', 'order__channels', 'view_count']
    search_fields = ('order__order_name', 'order__channels', 'viewer_id__iexact')
    search_help_text = "Поиск по order_name, channels и viewer_id"
    ordering = ('-view_count',)
    list_per_page = 30
