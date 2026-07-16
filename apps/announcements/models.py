import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Announcement(models.Model):
    """
    Системный баннер над списком чатов в NovaGram (как «поздравь с др» у Telegram).
    Создаёт только суперадмин: своя реклама («подпишись на канал») или важная
    информация. Показывается всем юзерам в окне дат, пока юзер его не закрыл
    крестиком (если баннер закрываемый).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(verbose_name='Заголовок', max_length=120)
    text = models.CharField(verbose_name='Текст', max_length=255)
    # CharField, а не URLField: URLField зарезал бы deep-links вида tg://
    # (у ChatAdOrder.link по той же причине CharField)
    link = models.CharField(verbose_name='Ссылка', max_length=500, blank=True, default='',
                            help_text='Куда ведёт тап по баннеру (https:// или tg://), можно пусто')
    dismissible = models.BooleanField(verbose_name='Можно закрыть', default=True,
                                      help_text='False — баннер без крестика (важная информация)')
    is_active = models.BooleanField(verbose_name='Включен', default=True)
    starts_at = models.DateTimeField(verbose_name='Показывать с', default=timezone.now)
    ends_at = models.DateTimeField(verbose_name='Показывать до', null=True, blank=True,
                                   help_text='Пусто — показывать, пока не выключат')
    priority = models.IntegerField(verbose_name='Приоритет', default=0,
                                   help_text='Больше — выше в списке, клиент показывает первый')
    clicks = models.PositiveIntegerField(verbose_name='Клики', default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+',
                                   verbose_name='Кто создал')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Баннер'
        verbose_name_plural = 'Баннеры'
        ordering = ['-priority', '-created_at']

    def __str__(self):
        return f"{self.title} ({'вкл' if self.is_active else 'выкл'})"

    def clean(self):
        # Окно дат не должно быть пустым (эта проверка покрывает Django-админку)
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError({'ends_at': 'Конец показа должен быть позже начала'})

    @classmethod
    def visible_for(cls, viewer_id):
        """
        Активные баннеры в окне дат, которые этот юзер ещё не закрыл.
        Клиент показывает первый из списка; закрыл — появится следующий.

        Если у баннера потом сдвинуть окно дат («перезапустить»), закрывшие юзеры
        его всё равно не увидят — записи о закрытии остаются. Чтобы показать
        всем заново, нужно создать новый баннер.
        """
        now = timezone.now()
        return (cls.objects
                .filter(is_active=True, starts_at__lte=now)
                .filter(Q(ends_at__isnull=True) | Q(ends_at__gte=now))
                # exclude по связи — это NOT EXISTS по уникальному индексу (announcement, viewer_id)
                .exclude(dismissals__viewer_id=viewer_id)
                .order_by('-priority', '-created_at'))


class AnnouncementDismissal(models.Model):
    """
    Закрытие баннера юзером (крестик). Храним на бэкенде, а не на клиенте —
    работает после переустановки и на всех устройствах юзера.
    """
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE,
                                     related_name='dismissals', verbose_name='Баннер')
    viewer_id = models.CharField(verbose_name='ID юзера в клиенте', max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Закрытие баннера'
        verbose_name_plural = 'Закрытия баннеров'
        unique_together = ['announcement', 'viewer_id']  # одно закрытие на юзера и баннер

    def __str__(self):
        return f"{self.viewer_id} закрыл {self.announcement_id}"
