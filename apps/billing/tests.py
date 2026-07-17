from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from rest_framework.test import APIClient

from apps.billing.models import Balance

User = get_user_model()


class AdminDepositApiTests(TestCase):
    """Пополнение через API: суперадмин может пополнить и чужой, и свой баланс"""

    def setUp(self):
        self.superadmin = User.objects.create_superuser('boss', 'boss@test.uz', 'pass12345')
        self.client = APIClient()
        self.client.force_authenticate(self.superadmin)

    def test_superadmin_deposits_own_balance(self):
        response = self.client.post('/api/admin/balance/deposit/', {
            'user_id': str(self.superadmin.user_id),
            'amount': '150.00',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['balance_info']['new_balance'], '150.00')

        # Баланса у createsuperuser не было — get_or_create его создал
        self.assertEqual(self.superadmin.balance.amount, Decimal('150.00'))

    def test_superadmin_deposits_other_user(self):
        user = User.objects.create_user('advertiser', password='pass12345')
        Balance.objects.create(user=user, amount=Decimal('10.00'))

        response = self.client.post('/api/admin/balance/deposit/', {
            'user_id': str(user.user_id),
            'amount': '90.00',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        user.balance.refresh_from_db()
        self.assertEqual(user.balance.amount, Decimal('100.00'))


class BalanceAdminDepositTests(TestCase):
    """Пополнение через админку: «замок» защищает от двойного клика и гонок"""

    def setUp(self):
        self.superadmin = User.objects.create_superuser('boss', 'boss@test.uz', 'pass12345')
        self.user = User.objects.create_user('advertiser', password='pass12345')
        self.balance = Balance.objects.create(user=self.user, amount=Decimal('0.00'))
        self.client = Client()
        self.client.force_login(self.superadmin)
        self.url = f'/admin/billing/balance/{self.balance.pk}/change/'

    def test_deposit_applies(self):
        response = self.client.post(self.url, {
            'add_amount': '100.00',
            'expected_amount': '0.00',  # каким админ видел баланс в форме
            '_save': 'Сохранить',
        })
        self.assertEqual(response.status_code, 302)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.amount, Decimal('100.00'))
        self.assertIsNone(self.balance.add_amount)

    def test_double_submit_does_not_double_deposit(self):
        """Двойной клик по «Сохранить» (тот же POST дважды) не задваивает пополнение"""
        data = {'add_amount': '100.00', 'expected_amount': '0.00', '_save': 'Сохранить'}
        self.client.post(self.url, data)
        self.client.post(self.url, data)  # повторная отправка той же формы

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.amount, Decimal('100.00'))

    def test_stale_form_does_not_overwrite_concurrent_change(self):
        """Пока форма была открыта, баланс изменился (например, возврат) — пополнение не применяется"""
        # Админ открыл форму при amount=0, а потом заказу вернули деньги
        Balance.objects.filter(pk=self.balance.pk).update(amount=Decimal('37.00'))

        self.client.post(self.url, {
            'add_amount': '100.00',
            'expected_amount': '0.00',  # устаревшее значение из открытой формы
            '_save': 'Сохранить',
        })
        self.balance.refresh_from_db()
        # Пополнение не применилось, параллельное изменение не потеряно
        self.assertEqual(self.balance.amount, Decimal('37.00'))

    def test_sequential_deposits_work(self):
        """Два честных пополнения подряд (каждое со свежей формой) складываются"""
        self.client.post(self.url, {'add_amount': '100.00', 'expected_amount': '0.00', '_save': '1'})
        self.client.post(self.url, {'add_amount': '50.00', 'expected_amount': '100.00', '_save': '1'})

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.amount, Decimal('150.00'))
