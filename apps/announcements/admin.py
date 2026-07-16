from django.contrib import admin
from django.db.models import Count

from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'is_active', 'dismissible', 'priority',
                    'starts_at', 'ends_at', 'clicks', 'dismissals_count')
    list_filter = ('is_active', 'dismissible')
    search_fields = ('title', 'text')
    readonly_fields = ('clicks', 'created_by', 'created_at', 'updated_at')
    list_per_page = 30

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(dismissals_count_agg=Count('dismissals'))

    @admin.display(description='Закрытий', ordering='dismissals_count_agg')
    def dismissals_count(self, obj):
        return obj.dismissals_count_agg

    def save_model(self, request, obj, form, change):
        # created_by в readonly — проставляем сами при создании
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    # Баннеры — только суперадмин (модераторы со staff-доступом их даже не видят)
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
