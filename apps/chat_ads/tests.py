from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.billing.models import Balance
from apps.common.models import ModerationStatus
from apps.chat_ads.models import ChatAdOrder

User = get_user_model()

API_KEY = 'test-server-key'


@override_settings(AD_SERVER_API_KEY=API_KEY)
class ChatAdsModerationTests(TestCase):
    """Горячий путь выдачи рекламы в чатах не отдаёт непромодерированную рекламу"""

    def setUp(self):
        self.advertiser = User.objects.create_user('advertiser', password='pass12345')
        Balance.objects.create(user=self.advertiser, amount=Decimal('100.00'))
        self.moderator = User.objects.create_user('moderator', password='pass12345')
        self.moderator.role = User.Role.MODERATOR
        self.moderator.save(update_fields=['role'])

        self.client_adv = APIClient()
        self.client_adv.force_authenticate(self.advertiser)
        self.server = APIClient()  # клиент NovaGram (server-to-server, по API-ключу)

        response = self.client_adv.post('/api/chat_ads/order/create/', {
            'order_name': 'Чат-заказ',
            'text': 'Текст рекламы',
            'link': 'https://example.com',
            'channels': 'testchan',
            'spm': '5.00',
            'budget': '50.00',
        }, format='json')
        assert response.status_code == 201, response.data
        self.order = ChatAdOrder.objects.get()

    def _search(self, viewer_id='viewer_1'):
        return self.server.post('/api/chat_ads/order/search/',
                                {'channel_name': 'testchan', 'viewer_id': viewer_id},
                                format='json', HTTP_X_API_KEY=API_KEY)

    def test_pending_order_is_not_served(self):
        self.assertEqual(self.order.status, ModerationStatus.PENDING)
        response = self._search()
        self.assertEqual(response.status_code, 404)

    def test_approved_order_is_served(self):
        self.order.approve(self.moderator)

        response = self._search()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.data['order_id']), str(self.order.order_id))

        self.order.refresh_from_db()
        self.assertEqual(self.order.shown_views, 1)

    def test_blocked_order_is_not_served(self):
        self.order.approve(self.moderator)
        self.order.refresh_from_db()
        self.order.block(self.moderator, 'Нарушение')

        response = self._search(viewer_id='viewer_2')
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_activate_pending_order(self):
        response = self.client_adv.post('/api/chat_ads/order/change_status/', {
            'order_id': str(self.order.order_id),
            'is_active': True,
        }, format='json')
        self.assertEqual(response.status_code, 400)

        self.order.refresh_from_db()
        self.assertFalse(self.order.is_active)

    def test_user_sees_status_and_reason(self):
        self.order.reject(self.moderator, 'Запрещённая тематика')

        response = self.client_adv.get(f'/api/chat_ads/order/{self.order.order_id}/detail/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'REJECTED')
        self.assertEqual(response.data['reject_reason'], 'Запрещённая тематика')
