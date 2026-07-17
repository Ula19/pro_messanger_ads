from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.billing.models import Balance
from apps.chat_ads.models import ChatAdOrder
from apps.notifications.models import Device, Notification
from apps.notifications.tasks import send_push_notification

User = get_user_model()


def create_chat_order(user, name='Тестовый заказ'):
    """Заказ рекламы в чатах — самый простой способ получить PENDING-заказ"""
    return ChatAdOrder.objects.create(
        user=user, order_name=name, text='текст рекламы',
        link='https://example.com', channels='channel1',
        budget=Decimal('100.00'), spm=Decimal('10.00'),
    )


class DeviceApiTests(TestCase):
    """Регистрация и отвязка FCM-токенов"""

    def setUp(self):
        self.user = User.objects.create_user('advertiser', password='pass12345')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_register_creates_device(self):
        response = self.client.post('/api/notifications/devices/', {
            'token': 'fcm-token-1', 'platform': 'IOS',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Device.objects.filter(user=self.user, token='fcm-token-1').count(), 1)

    def test_register_same_token_is_idempotent(self):
        for _ in range(2):
            self.client.post('/api/notifications/devices/',
                             {'token': 'fcm-token-1', 'platform': 'IOS'}, format='json')
        self.assertEqual(Device.objects.count(), 1)

    def test_token_moves_to_new_user_on_relogin(self):
        """Релогин на том же устройстве: токен переезжает к новому юзеру и оживает"""
        other = User.objects.create_user('other', password='pass12345')
        Device.objects.create(user=other, token='fcm-token-1', platform='IOS', is_active=False)

        self.client.post('/api/notifications/devices/',
                         {'token': 'fcm-token-1', 'platform': 'IOS'}, format='json')

        device = Device.objects.get(token='fcm-token-1')
        self.assertEqual(device.user, self.user)
        self.assertTrue(device.is_active)
        self.assertEqual(Device.objects.count(), 1)

    def test_remove_deletes_only_own_token(self):
        other = User.objects.create_user('other', password='pass12345')
        Device.objects.create(user=other, token='чужой-токен', platform='ANDROID')

        # Чужой токен не удаляется, но ответ всё равно 200 (идемпотентно)
        response = self.client.post('/api/notifications/devices/remove/',
                                    {'token': 'чужой-токен'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Device.objects.count(), 1)

        Device.objects.create(user=self.user, token='мой-токен', platform='IOS')
        self.client.post('/api/notifications/devices/remove/',
                         {'token': 'мой-токен'}, format='json')
        self.assertFalse(Device.objects.filter(token='мой-токен').exists())

    def test_requires_auth(self):
        anon = APIClient()
        self.assertEqual(anon.post('/api/notifications/devices/', {}).status_code, 401)
        self.assertEqual(anon.get('/api/notifications/').status_code, 401)


class NotificationApiTests(TestCase):
    """Список уведомлений, счётчик, отметка прочитанным"""

    def setUp(self):
        self.user = User.objects.create_user('advertiser', password='pass12345')
        self.other = User.objects.create_user('other', password='pass12345')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.own = Notification.objects.create(
            user=self.user, title='Заказ одобрен', body='...',
            type=Notification.Type.ORDER_APPROVED)
        self.foreign = Notification.objects.create(
            user=self.other, title='Чужое', body='...',
            type=Notification.Type.ORDER_APPROVED)

    def test_list_shows_only_own(self):
        response = self.client.get('/api/notifications/')
        self.assertEqual(response.status_code, 200)
        titles = [item['title'] for item in response.data['results']]
        self.assertEqual(titles, ['Заказ одобрен'])

    def test_unread_count(self):
        Notification.objects.create(user=self.user, title='Ещё одно', body='...',
                                    type=Notification.Type.ORDER_REJECTED)
        response = self.client.get('/api/notifications/unread_count/')
        self.assertEqual(response.data['unread'], 2)

    def test_mark_read(self):
        response = self.client.post(f'/api/notifications/{self.own.pk}/read/')
        self.assertEqual(response.status_code, 200)
        self.own.refresh_from_db()
        self.assertTrue(self.own.is_read)

    def test_mark_read_foreign_is_404(self):
        response = self.client.post(f'/api/notifications/{self.foreign.pk}/read/')
        self.assertEqual(response.status_code, 404)
        self.foreign.refresh_from_db()
        self.assertFalse(self.foreign.is_read)

    def test_read_all(self):
        Notification.objects.create(user=self.user, title='Ещё', body='...',
                                    type=Notification.Type.NEW_ORDER)
        self.client.post('/api/notifications/read_all/')
        self.assertFalse(self.user.notifications.filter(is_read=False).exists())
        # Чужие не тронуты
        self.assertTrue(self.other.notifications.filter(is_read=False).exists())


class OrderEventNotificationTests(TestCase):
    """Доменные события: создание заказа и решения модератора рождают уведомления"""

    def setUp(self):
        self.advertiser = User.objects.create_user('advertiser', password='pass12345')
        Balance.objects.create(user=self.advertiser, amount=Decimal('1000.00'))
        self.moderator = User.objects.create_user('moder', password='pass12345',
                                                  role=User.Role.MODERATOR)
        self.superadmin = User.objects.create_superuser('boss', 'boss@test.uz', 'pass12345')

    def test_new_order_notifies_moderators_and_superadmin_only(self):
        create_chat_order(self.advertiser)

        self.assertEqual(self.moderator.notifications.filter(
            type=Notification.Type.NEW_ORDER).count(), 1)
        self.assertEqual(self.superadmin.notifications.filter(
            type=Notification.Type.NEW_ORDER).count(), 1)
        self.assertEqual(self.advertiser.notifications.count(), 0)

        notification = self.moderator.notifications.get()
        self.assertIn('Тестовый заказ', notification.body)
        self.assertEqual(notification.payload['order_type'], 'chat_ads')

    def test_approve_notifies_owner(self):
        order = create_chat_order(self.advertiser)
        order.approve(self.moderator)

        notification = self.advertiser.notifications.get(
            type=Notification.Type.ORDER_APPROVED)
        self.assertIn('одобрен', notification.body)
        self.assertEqual(notification.payload['order_id'], str(order.order_id))

    def test_reject_notifies_owner_with_reason(self):
        order = create_chat_order(self.advertiser)
        order.reject(self.moderator, 'Запрещённая тематика')

        notification = self.advertiser.notifications.get(
            type=Notification.Type.ORDER_REJECTED)
        self.assertIn('Запрещённая тематика', notification.body)

    def test_block_notifies_owner_with_reason(self):
        order = create_chat_order(self.advertiser)
        order.approve(self.moderator)
        order.block(self.superadmin, 'Жалобы юзеров')

        notification = self.advertiser.notifications.get(
            type=Notification.Type.ORDER_BLOCKED)
        self.assertIn('Жалобы юзеров', notification.body)

    def test_moderation_api_creates_notification(self):
        """Через реальный эндпоинт модерации уведомление тоже создаётся"""
        order = create_chat_order(self.advertiser)
        client = APIClient()
        client.force_authenticate(self.moderator)

        response = client.post(f'/api/moderation/chat_ads/{order.order_id}/approve/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.advertiser.notifications.filter(
            type=Notification.Type.ORDER_APPROVED).exists())


class SendPushTaskTests(TestCase):
    """Celery-задача отправки push"""

    def setUp(self):
        self.user = User.objects.create_user('advertiser', password='pass12345')
        self.notification = Notification.objects.create(
            user=self.user, title='Заказ одобрен', body='...',
            type=Notification.Type.ORDER_APPROVED,
            payload={'order_id': 'x', 'order_type': 'chat_ads'})

    def test_missing_notification_is_ok(self):
        self.assertEqual(send_push_notification(999999), 'Уведомление не найдено')

    def test_no_devices_skips_firebase(self):
        result = send_push_notification(self.notification.pk)
        self.assertEqual(result, 'У юзера нет активных устройств')

    @patch('apps.notifications.tasks._get_firebase_app', return_value=None)
    def test_no_firebase_key_skips_send(self, mock_app):
        Device.objects.create(user=self.user, token='fcm-token-1', platform='IOS')
        result = send_push_notification(self.notification.pk)
        self.assertEqual(result, 'Push пропущен: нет ключа Firebase')

    @patch('apps.notifications.tasks._get_firebase_app', return_value=object())
    def test_dead_token_is_deactivated(self, mock_app):
        from firebase_admin import messaging

        device = Device.objects.create(user=self.user, token='мертвый', platform='IOS')

        # Ответ FCM: один токен протух
        dead_result = type('R', (), {'exception': messaging.UnregisteredError('гон'),
                                     'success': False})()
        batch = type('B', (), {'responses': [dead_result], 'success_count': 0})()
        with patch('firebase_admin.messaging.send_each_for_multicast', return_value=batch):
            result = send_push_notification(self.notification.pk)

        self.assertEqual(result, 'Отправлено 0/1')
        device.refresh_from_db()
        self.assertFalse(device.is_active)
