from django.core.management.base import BaseCommand

from apps.announcements.models import Announcement


class Command(BaseCommand):
    help = 'Создаёт тестовый баннер, чтобы dev-клиент сразу увидел его через active/'

    def handle(self, *args, **options):
        # get_or_create по title — команду можно гонять сколько угодно, дублей не будет
        announcement, created = Announcement.objects.get_or_create(
            title='Тестовый баннер',
            defaults={
                'text': 'Если ты это видишь — связка клиента с бэкендом работает',
                'link': 'https://t.me/novagram',
                'dismissible': True,
                'is_active': True,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Тестовый баннер создан: {announcement.id}'))
        else:
            self.stdout.write(f'Тестовый баннер уже есть: {announcement.id}')
