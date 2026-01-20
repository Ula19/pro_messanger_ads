from django.contrib import admin

from .models import ChatAdMedia, ChatAdOrder, ChatAdView


@admin.register(ChatAdMedia)
class ChatAdMediaAdmin(admin.ModelAdmin):
    pass


@admin.register(ChatAdOrder)
class ChatAdOrderAdmin(admin.ModelAdmin):
    pass


@admin.register(ChatAdView)
class ChatAdViewAdmin(admin.ModelAdmin):
    pass
