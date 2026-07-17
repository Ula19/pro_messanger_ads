import uuid
from decimal import Decimal

from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator

from apps.common.models import ModerationMixin, ModerationStatus



class Tag(models.Model):
    """Модель тегов"""
    name = models.CharField(max_length=100, unique=True, verbose_name='Имя тега')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Tag'
        verbose_name_plural = 'Tags'
        ordering = ['name']

    def __str__(self):
        return self.name

    @classmethod
    def find_similar_tags(cls, tag_name, threshold=0.3):
        """Поиск похожих тегов по триграммному сходству"""
        from django.contrib.postgres.search import TrigramSimilarity
        return cls.objects.annotate(
            similarity=TrigramSimilarity('name', tag_name)
        ).filter(similarity__gte=threshold).order_by('-similarity')


class Channel(models.Model):
    """Модель канала"""
    channel_id = models.CharField(max_length=255, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='channels')
    channel_name = models.CharField(max_length=255, unique=True)
    tags = models.ManyToManyField(Tag, related_name='channels', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.channel_name} ({self.channel_id})"

    def add_tags(self, tag_names):
        """Добавляет теги к каналу (не заменяя существующие)"""
        for tag_name in tag_names:
            tag, _ = Tag.objects.get_or_create(name=tag_name.lower().strip())
            self.tags.add(tag)


class Order(ModerationMixin):
    """Модель рекламы"""

    class Platform(models.TextChoices):
        TELEGRAM = 'TELEGRAM', 'Telegram'
        NOVAGRAM = 'NOVAGRAM', 'Novagram'

    order_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    channel_id = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='orders')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders', verbose_name='User')
    channel_name = models.CharField(verbose_name='Channel Name', max_length=255)
    order_name = models.CharField(verbose_name='Order Name', max_length=255)
    tags = models.ManyToManyField(Tag, related_name='orders', blank=True, verbose_name='Tags')
    platform = models.CharField(verbose_name='Платформа', max_length=20,
                                choices=Platform.choices, default=Platform.TELEGRAM)

    # Параметры заказа
    spm = models.DecimalField(verbose_name='SPM', max_digits=10, decimal_places=2,
                              help_text='Spend per mille (стоимость за 1000 показов)')
    budget = models.DecimalField(verbose_name='Budget', max_digits=15, decimal_places=2,
                                 validators=[MinValueValidator(Decimal('0.01'))])

    # Поля для управления показами
    total_views = models.PositiveIntegerField(verbose_name='Total Views', default=0,
                                              help_text='Общее количество купленных показов')
    clicks = models.PositiveIntegerField(verbose_name='Click channel', default=0,
                                        help_text='Количество переходов на канал по клику')
    shown_views = models.PositiveIntegerField(verbose_name='Shown Views', default=0,
                                              help_text='Количество уже показанных просмотров')
    remaining_views = models.PositiveIntegerField(verbose_name='Remaining Views', default=0,
                                                  help_text='Оставшееся количество показов')
    max_views_per_user = models.PositiveIntegerField(
        verbose_name='Максимальное количество показов одному пользователю',
        default=1,
        help_text='Сколько раз можно показать эту рекламу одному пользователю'
    )

    # Статусы
    completed = models.BooleanField(verbose_name='Completed', default=False,
                                    help_text='True - реклама завершена (просмотры израсходованы)')
    cancelled = models.BooleanField(verbose_name='Cancelled', default=False,
                                    help_text='True - реклама отменена пользователем')
    is_active = models.BooleanField(verbose_name='Is Active', default=False,
                                    help_text='True - реклама активна и показывается. '
                                              'Включается только после одобрения модератором')

    created_at = models.DateTimeField(verbose_name='Created At', auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name='Updated At', auto_now=True)

    class Meta:
        verbose_name = 'Order'
        verbose_name_plural = 'Orders'
        ordering = ['-created_at']

    def __str__(self):
        status = "Active"
        if self.cancelled:
            status = "Cancelled"
        elif self.completed:
            status = "Completed"
        return f"{self.order_name} - {self.channel_name} ({status})"

    def calculate_views_from_budget(self):
        """Рассчитывает количество показов на основе SPM и бюджета"""
        if self.spm > 0:
            # Формула: количество показов = (бюджет / SPM) * 1000
            views = (self.budget / self.spm) * 1000
            return int(views)
        return 0

    def save(self, *args, **kwargs):
        """При сохранении заказа рассчитываем количество показов"""
        is_new = self._state.adding

        # Если это новый заказ, рассчитываем количество показов
        if is_new and self.budget and self.spm:
            self.total_views = self.calculate_views_from_budget()
            self.remaining_views = self.total_views

        # Новый заказ всегда уходит на модерацию и не показывается,
        # какие бы значения ни пришли снаружи. Включить его может только approve().
        if is_new:
            self.status = ModerationStatus.PENDING
            self.is_active = False

        super().save(*args, **kwargs)

        # Новый заказ упал в очередь модерации — сообщаем модераторам
        if is_new:
            from apps.notifications.services import notify_moderators_new_order
            notify_moderators_new_order(self)

        # Добавляем теги после сохранения
        if hasattr(self, '_tag_names'):
            # Добавляем теги к заказу
            for tag_name in self._tag_names:
                tag, _ = Tag.objects.get_or_create(name=tag_name.lower().strip())
                self.tags.add(tag)

            # Добавляем теги к каналу (без дублирования)
            self.channel_id.add_tags(self._tag_names)

            # Удаляем временный атрибут после использования
            delattr(self, '_tag_names')

    def decrement_views(self):
        """Уменьшает количество оставшихся показов на 1"""
        if self.remaining_views > 0 and not self.cancelled:
            self.shown_views += 1
            self.remaining_views -= 1

            # Проверяем, не израсходованы ли все показы
            if self.remaining_views == 0:
                self.completed = True
                self.is_active = False

            self.save()
            return True
        return False

    def cancel_order(self):
        """Отменяет заказ и возвращает средства за оставшиеся показы"""
        # По отклонённому/заблокированному заказу деньги уже вернули при модерации
        if self.status in (ModerationStatus.REJECTED, ModerationStatus.BLOCKED):
            return 0

        if not self.cancelled:
            self.cancelled = True
            self.is_active = False
            self.completed = False

            # Возврат считает общий метод миксина (он же обнуляет remaining_views)
            refund_amount = self._refund_unspent()

            self.save()
            return refund_amount
        return 0

    def increment_clicks(self):
        """Увеличить счетчик кликов на 1"""
        self.clicks += 1
        self.save(update_fields=['clicks'])


class AdView(models.Model):
    """Модель для отслеживания показов рекламы конкретным пользователям"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='ad_views', verbose_name='Заказ')
    viewer_id = models.CharField(verbose_name='ID пользователя (зрителя)', max_length=255,
                                 help_text='ID пользователя, которому показывается реклама')
    view_count = models.PositiveIntegerField(verbose_name='Количество просмотров', default=0,
                                             help_text='Сколько раз этому пользователю уже показали эту рекламу')
    last_viewed_at = models.DateTimeField(verbose_name='Последний просмотр', auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Показ рекламы'
        verbose_name_plural = 'Показы рекламы'
        unique_together = ['order', 'viewer_id']  # Одна запись на заказ и пользователя
        indexes = [
            models.Index(fields=['viewer_id', 'order']),
            models.Index(fields=['last_viewed_at']),
        ]

    def __str__(self):
        return f"{self.viewer_id} - {self.order.order_name} ({self.view_count})"

    def can_view_more(self, max_views):
        """Проверяет, можно ли показать еще рекламу этому пользователю"""
        return self.view_count < max_views

    def increment_view(self):
        """Увеличивает счетчик просмотров"""
        self.view_count += 1
        self.save()
        return True
