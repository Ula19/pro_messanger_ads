from django.utils import timezone
from datetime import timedelta

from core.celery import app
from .models import ChatAdMedia


@app.task
def cleanup_orphaned_media():
    # Удаляем файлы, созданные более 24 часов назад И не привязанные к заказу
    deadline = timezone.now() - timedelta(hours=24)
    orphans = ChatAdMedia.objects.filter(created_at__lt=deadline, is_linked=False)
    # orphans = ChatAdMedia.objects.filter(is_linked=False)

    deleted_count = 0
    for media in orphans:
        try:
            if media.file:
                media.file.delete(save=False)
            media.delete()
            deleted_count += 1
        except Exception as e:
            # Логируем ошибку, но не прерываем выполнение
            print(f"Ошибка при удалении файла {media.id}: {str(e)}")

    result = f"Удалено {deleted_count} неиспользуемых файлов."
    print(result)
    return result
