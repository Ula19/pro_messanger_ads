import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.contrib.auth.models import AbstractUser


class CustomUser(AbstractUser):
    """Кастомная модель пользователя с UUID"""
    user_id = models.UUIDField(verbose_name='User ID', default=uuid.uuid4, editable=False, unique=True)
    is_admin = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f"{self.username} ({self.user_id})"


class Balance(models.Model):
    """Модель баланса пользователя"""
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='balance',
        verbose_name='User'
    )
    amount = models.DecimalField(
        verbose_name='Balance Amount',
        max_digits=15,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Balance'
        verbose_name_plural = 'Balances'

    def __str__(self):
        return f"{self.user.username}: {self.amount}"

    def deposit(self, amount):
        """Пополнение баланса"""
        self.amount += Decimal(amount)
        self.save()

    def withdraw(self, amount):
        """Списание с баланса (с проверкой)"""
        if self.amount >= amount:
            self.amount -= amount
            self.save()
            return True
        return False

    def get_available_amount(self):
        """Получение доступного баланса"""
        return self.amount


class Tag(models.Model):
    """Модель тегов"""
    name = models.CharField(max_length=100, unique=True, verbose_name='Tag Name')
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
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='channels')
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


class Order(models.Model):
    """Модель рекламы"""
    channel_id = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='orders')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='orders', verbose_name='User')
    channel_name = models.CharField(verbose_name='Channel Name', max_length=255)
    order_name = models.CharField(verbose_name='Order Name', max_length=255)
    tags = models.ManyToManyField(Tag, related_name='orders', blank=True, verbose_name='Tags')

    # Параметры заказа
    spm = models.DecimalField(verbose_name='SPM', max_digits=10, decimal_places=2,
                              help_text='Spend per mille (стоимость за 1000 показов)')
    budget = models.DecimalField(verbose_name='Budget', max_digits=15, decimal_places=2,
                                 validators=[MinValueValidator(Decimal('0.01'))])

    # Поля для управления показами
    total_views = models.PositiveIntegerField(verbose_name='Total Views', default=0,
                                              help_text='Общее количество купленных показов')
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
    is_active = models.BooleanField(verbose_name='Is Active', default=True,
                                    help_text='True - реклама активна и показывается')

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
        is_new = self.pk is None

        # Если это новый заказ, рассчитываем количество показов
        if is_new and self.budget and self.spm:
            self.total_views = self.calculate_views_from_budget()
            self.remaining_views = self.total_views

        super().save(*args, **kwargs)

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

    def decrement_views(self, viewer_id=None):
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
        if not self.cancelled and self.is_active:
            self.cancelled = True
            self.is_active = False
            self.completed = False

            # Рассчитываем сумму для возврата
            # Формула: (оставшиеся показы / 1000) * SPM
            refund_amount = (Decimal(self.remaining_views) / Decimal(1000)) * self.spm

            # Возвращаем средства на баланс пользователя
            balance = self.user.balance
            balance.deposit(refund_amount)

            # Сбрасываем оставшиеся показы
            self.remaining_views = 0

            self.save()
            return refund_amount
        return 0

    def get_refund_amount(self):
        """Рассчитывает сумму возврата при отмене"""
        if self.remaining_views > 0:
            return (Decimal(self.remaining_views) / Decimal(1000)) * self.spm
        return 0


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


    # user_budget
    # Реализовать функцию cancel. Может прийти запрос, чтобы завершить рекламу до закачивания количества просмотров.
    # И в этот момент
    # мы должны вернуть пользователю его деньги. В Первым Post запросе, нам будет приходит остаток денег пользователя
    # и мы должны реализовать функцию для подсчета количества просмотра канала. Формулу нужно уточнить, вроде нужно
    # spm поделить на бюджет. И когда пользователь решает завершить рекламу, он отправляет запрос с id ордера и мы у
    # этого ордера меняем его булево значение на фолс. И остаток денег рассчитываем по формуле и добавляем обратно в
    # его баланс. Поле count мы должны сами определить по формуле. и еще создать отдельное поле которое будет
    # увеличиваться при каждом просмотре и когда он достигает уровня count, он должен отключать рекламу то-есть
    # переключить его булл статусы

    # DONE ^^^^^^ ну почты


    # Нужно добавить функцию записывающую историю расхода денег пользователя, куда он потратил деньги, на какие рекламы
    # сколько потратил, если отменил (cancel) рекламу то сколько денег на баланс вернулось, и тому подобное

    # Добавить два вида поиска. Первый поиск проверяем на наличие тега в канале. Второй поиск, если первый не нашел
    # ничего, значить есть вероятность, что юзер написал тег с ошибкой, поэтому сделаем поиск по триграмному сходству

    # DONE ^^^^^^^^

    # Нужно добавить функцию Где при оформление ордера, пользователь сможет выбрать сколько раз одному пользователю
    # показать данный канал при поиске. Проще говоря, когда в приложение юзер вводит тег канала которого ищет, и при
    # нахождение подходящего канала чтобы ему вывелось тот канал который нашел в бд. И при повторном запросе этим же
    # пользователем этого же тега мы должны показать ему то количество раз этот канал сколько раз указал при заказе
    # ордера.
