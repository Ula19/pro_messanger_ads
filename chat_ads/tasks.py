from django.utils import timezone
from datetime import timedelta
from .models import ChatAdMedia


def cleanup_orphaned_media():
    # Удаляем файлы, созданные более 24 часов назад И не привязанные к заказу
    deadline = timezone.now() - timedelta(hours=24)
    orphans = ChatAdMedia.objects.filter(created_at__lt=deadline, is_linked=False)

    for media in orphans:
        # Удаляем физический файл с диска/S3
        media.file.delete(save=False)
        # Удаляем запись из БД
        media.delete()
