from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.partner.models import ChannelEarning

User = get_user_model()


class AdminEarningsListTests(TestCase):
    """Список заработков каналов для админ-панели"""

    def setUp(self):
        self.superadmin = User.objects.create_superuser('boss', 'boss@test.uz', 'pass12345')
        owner = User.objects.create_user('owner', password='pass12345')
        ChannelEarning.objects.create(
            channel_id=111, channel_name='Крутой канал', owner=owner,
            claim_status=ChannelEarning.ClaimStatus.CONFIRMED,
            available=Decimal('10.5000'), total_earned=Decimal('99.0000'),
        )
        ChannelEarning.objects.create(
            channel_id=222, channel_name='Безымянный',
            total_earned=Decimal('5.0000'),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.superadmin)

    def test_closed_for_anon_and_regular_user(self):
        anon = APIClient()
        self.assertEqual(anon.get('/api/partner/admin/earnings/').status_code, 401)

        regular = APIClient()
        regular.force_authenticate(User.objects.create_user('user', password='pass12345'))
        self.assertEqual(regular.get('/api/partner/admin/earnings/').status_code, 403)

    def test_list_sorted_by_earned(self):
        response = self.client.get('/api/partner/admin/earnings/')
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual([item['channel_id'] for item in results], [111, 222])
        self.assertEqual(results[0]['owner'], 'owner')
        self.assertIsNone(results[1]['owner'])

    def test_search_by_name_and_id(self):
        by_name = self.client.get('/api/partner/admin/earnings/?search=крутой')
        self.assertEqual([i['channel_id'] for i in by_name.data['results']], [111])

        by_id = self.client.get('/api/partner/admin/earnings/?search=222')
        self.assertEqual([i['channel_id'] for i in by_id.data['results']], [222])
