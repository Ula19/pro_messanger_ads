import os
from celery import Celery
from celery.schedules import crontab

# Указываем Django, где искать настройки
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

app = Celery('core', broker_connection_retry=False, broker_connection_retry_on_startup=True)

app.config_from_object('django.conf:settings')

# Автоматически находим tasks.py во всех приложениях
app.autodiscover_tasks()
app.conf.beat_schedule = {
    'remove-unused-media-files_every_day_at_12_00_AM': {
        'task': 'apps.chat_ads.tasks.cleanup_orphaned_media',
        'schedule': crontab(minute=0, hour=0),
        # 'schedule': crontab(),
    },
}
