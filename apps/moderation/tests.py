import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import F
from django.test import TestCase
from rest_framework.test import APIClient

from apps.billing.models import Balance
from apps.common.models import ModerationStatus
from apps.search_ads.models import Order
from apps.chat_ads.models import ChatAdOrder

User = get_user_model()


def create_user(username, role=None, balance=Decimal('100.00')):
    """Хелпер: пользователь с балансом (роль по умолчанию — рекламодатель)"""
    user = User.objects.create_user(username=username, password='pass12345')
    if role:
        user.role = role
        user.save(update_fields=['role'])
    Balance.objects.create(user=user, amount=balance)
    return user


def create_search_order_via_api(client, budget='50.00', spm='5.00', **extra):
    """Хелпер: создаём заказ поисковой рекламы через API (с реальным списанием денег)"""
    payload = {
        'channel_id': f'ch_{uuid.uuid4().hex[:8]}',
        'channel_name': f'Канал {uuid.uuid4().hex[:8]}',
        'order_name': 'Тестовый заказ',
        'tags': ['новости'],
        'spm': spm,
        'budget': budget,
        'max_views_per_user': 1,
    }
    payload.update(extra)
    return client.post('/api/search_ads/order/create/', payload, format='json')


def create_chat_order_via_api(client, budget='50.00', spm='5.00', **extra):
    """Хелпер: создаём заказ рекламы в чатах через API (с реальным списанием денег)"""
    payload = {
        'order_name': 'Тестовый чат-заказ',
        'text': 'Текст рекламы',
        'link': 'https://example.com',
        'channels': 'testchan',
        'spm': spm,
        'budget': budget,
    }
    payload.update(extra)
    return client.post('/api/chat_ads/order/create/', payload, format='json')


class ModerationMoneyTests(TestCase):
    """Деньги: списание при создании, возвраты при reject/block, защита от двойного возврата"""

    def setUp(self):
        self.advertiser = create_user('advertiser')
        self.moderator = create_user('moderator', role=User.Role.MODERATOR)
        self.client_adv = APIClient()
        self.client_adv.force_authenticate(self.advertiser)
        self.client_mod = APIClient()
        self.client_mod.force_authenticate(self.moderator)

    def _balance(self, user):
        return Balance.objects.get(user=user).amount

    def test_create_order_goes_to_pending(self):
        """Новый заказ: деньги списаны, статус PENDING, не активен (даже если клиент прислал is_active)"""
        response = create_search_order_via_api(self.client_adv, is_active=True)
        self.assertEqual(response.status_code, 201)

        order = Order.objects.get()
        self.assertEqual(order.status, ModerationStatus.PENDING)
        self.assertFalse(order.is_active)
        self.assertEqual(self._balance(self.advertiser), Decimal('50.00'))

    def test_chat_order_goes_to_pending(self):
        response = create_chat_order_via_api(self.client_adv, is_active=True)
        self.assertEqual(response.status_code, 201)

        order = ChatAdOrder.objects.get()
        self.assertEqual(order.status, ModerationStatus.PENDING)
        self.assertFalse(order.is_active)
        self.assertEqual(self._balance(self.advertiser), Decimal('50.00'))

    def test_approve_activates_order(self):
        create_search_order_via_api(self.client_adv)
        order = Order.objects.get()

        response = self.client_mod.post(f'/api/moderation/search_ads/{order.order_id}/approve/')
        self.assertEqual(response.status_code, 200)

        order.refresh_from_db()
        self.assertEqual(order.status, ModerationStatus.APPROVED)
        self.assertTrue(order.is_active)
        self.assertEqual(order.moderated_by, self.moderator)
        self.assertIsNotNone(order.moderated_at)
        # Денег approve не трогает
        self.assertEqual(self._balance(self.advertiser), Decimal('50.00'))

    def test_reject_returns_full_budget_including_dust(self):
        """При отклонении возвращается ПОЛНЫЙ бюджет, даже когда формула теряет копейки на усечении"""
        # budget=10, spm=3: total_views = int(10/3*1000) = 3333, по формуле вернулось бы 9.999
        create_search_order_via_api(self.client_adv, budget='10.00', spm='3.00')
        order = Order.objects.get()
        self.assertEqual(order.total_views, 3333)

        response = self.client_mod.post(
            f'/api/moderation/search_ads/{order.order_id}/reject/',
            {'reason': 'Запрещённая тематика'}, format='json',
        )
        self.assertEqual(response.status_code, 200)

        order.refresh_from_db()
        self.assertEqual(order.status, ModerationStatus.REJECTED)
        self.assertFalse(order.is_active)
        self.assertEqual(order.remaining_views, 0)
        self.assertEqual(order.reject_reason, 'Запрещённая тематика')
        # Баланс вернулся ровно к исходному
        self.assertEqual(self._balance(self.advertiser), Decimal('100.00'))

    def test_reject_requires_reason(self):
        create_search_order_via_api(self.client_adv)
        order = Order.objects.get()

        response = self.client_mod.post(f'/api/moderation/search_ads/{order.order_id}/reject/')
        self.assertEqual(response.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.status, ModerationStatus.PENDING)

    def test_block_returns_unspent_remainder(self):
        """Блокировка открученного заказа возвращает остаток по формуле (remaining/1000)*spm"""
        create_chat_order_via_api(self.client_adv, budget='50.00', spm='5.00')
        order = ChatAdOrder.objects.get()  # total_views = 10000
        order.approve(self.moderator)

        # Имитируем 1000 показов (как это делает горячий путь — условным UPDATE)
        ChatAdOrder.objects.filter(pk=order.pk).update(
            remaining_views=F('remaining_views') - 1000,
            shown_views=F('shown_views') + 1000,
        )

        response = self.client_mod.post(
            f'/api/moderation/chat_ads/{order.order_id}/block/',
            {'reason': 'Нарушение правил'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        # Возврат: (9000/1000) * 5 = 45
        self.assertEqual(response.data['refund_amount'], '45.00')

        order.refresh_from_db()
        self.assertEqual(order.status, ModerationStatus.BLOCKED)
        self.assertFalse(order.is_active)
        self.assertEqual(order.remaining_views, 0)
        # 100 - 50 (создание) + 45 (возврат) = 95
        self.assertEqual(self._balance(self.advertiser), Decimal('95.00'))

    def test_block_pending_returns_full_budget(self):
        create_search_order_via_api(self.client_adv, budget='10.00', spm='3.00')
        order = Order.objects.get()

        response = self.client_mod.post(
            f'/api/moderation/search_ads/{order.order_id}/block/',
            {'reason': 'Нарушение'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._balance(self.advertiser), Decimal('100.00'))

    def test_no_double_refund_on_repeated_decision(self):
        """Повторное решение по заказу не возвращает деньги второй раз"""
        create_search_order_via_api(self.client_adv)
        order = Order.objects.get()

        first = self.client_mod.post(
            f'/api/moderation/search_ads/{order.order_id}/reject/',
            {'reason': 'Причина'}, format='json',
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self._balance(self.advertiser), Decimal('100.00'))

        # Повторный reject, block и approve — конфликт, баланс не меняется
        for action in ('reject', 'block'):
            repeat = self.client_mod.post(
                f'/api/moderation/search_ads/{order.order_id}/{action}/',
                {'reason': 'Ещё раз'}, format='json',
            )
            self.assertEqual(repeat.status_code, 409)
        approve = self.client_mod.post(f'/api/moderation/search_ads/{order.order_id}/approve/')
        self.assertEqual(approve.status_code, 409)
        self.assertEqual(self._balance(self.advertiser), Decimal('100.00'))

    def test_cancel_after_reject_gives_no_money(self):
        """Отмена юзером после отклонения не возвращает деньги второй раз"""
        create_search_order_via_api(self.client_adv)
        order = Order.objects.get()
        self.client_mod.post(
            f'/api/moderation/search_ads/{order.order_id}/reject/',
            {'reason': 'Причина'}, format='json',
        )

        response = self.client_adv.post(f'/api/search_ads/order/{order.order_id}/cancel/')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._balance(self.advertiser), Decimal('100.00'))

    def test_reject_after_user_cancel_conflicts(self):
        """Юзер отменил PENDING-заказ (полный возврат) — модератор уже не может отклонить"""
        create_search_order_via_api(self.client_adv, budget='10.00', spm='3.00')
        order = Order.objects.get()

        cancel = self.client_adv.post(f'/api/search_ads/order/{order.order_id}/cancel/')
        self.assertEqual(cancel.status_code, 200)
        # Отмена непоказанного заказа вернула полный бюджет (без потери копеек)
        self.assertEqual(self._balance(self.advertiser), Decimal('100.00'))

        response = self.client_mod.post(
            f'/api/moderation/search_ads/{order.order_id}/reject/',
            {'reason': 'Причина'}, format='json',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._balance(self.advertiser), Decimal('100.00'))

    def test_moderator_cannot_moderate_own_order(self):
        """Модератор не модерирует свою рекламу, суперадмин — может"""
        client_mod_own = APIClient()
        client_mod_own.force_authenticate(self.moderator)
        create_search_order_via_api(client_mod_own)
        order = Order.objects.get()

        response = self.client_mod.post(f'/api/moderation/search_ads/{order.order_id}/approve/')
        self.assertEqual(response.status_code, 403)

        superadmin = User.objects.create_superuser('boss', 'boss@test.uz', 'pass12345')
        client_boss = APIClient()
        client_boss.force_authenticate(superadmin)
        response = client_boss.post(f'/api/moderation/search_ads/{order.order_id}/approve/')
        self.assertEqual(response.status_code, 200)

    def test_unknown_order_type_and_missing_order(self):
        response = self.client_mod.post(f'/api/moderation/unknown/{uuid.uuid4()}/approve/')
        self.assertEqual(response.status_code, 404)
        response = self.client_mod.post(f'/api/moderation/search_ads/{uuid.uuid4()}/approve/')
        self.assertEqual(response.status_code, 404)


class ModerationPermissionTests(TestCase):
    """Матрица прав: кто что может"""

    def setUp(self):
        self.advertiser = create_user('advertiser')
        self.moderator = create_user('moderator', role=User.Role.MODERATOR)
        self.superadmin = User.objects.create_superuser('boss', 'boss@test.uz', 'pass12345')

        self.client_adv = APIClient()
        self.client_adv.force_authenticate(self.advertiser)
        self.client_mod = APIClient()
        self.client_mod.force_authenticate(self.moderator)
        self.client_boss = APIClient()
        self.client_boss.force_authenticate(self.superadmin)

    def test_advertiser_cannot_moderate(self):
        create_search_order_via_api(self.client_adv)
        order = Order.objects.get()

        self.assertEqual(self.client_adv.get('/api/moderation/search_ads/pending/').status_code, 403)
        self.assertEqual(self.client_adv.get('/api/moderation/pending_count/').status_code, 403)
        self.assertEqual(
            self.client_adv.post(f'/api/moderation/search_ads/{order.order_id}/approve/').status_code, 403)

    def test_moderator_sees_pending(self):
        create_search_order_via_api(self.client_adv)
        response = self.client_mod.get('/api/moderation/search_ads/pending/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['username'], 'advertiser')

    def test_cancelled_pending_order_leaves_queue(self):
        """Юзер отменил заказ, не дождавшись проверки — из очереди и счётчика он уходит"""
        create_search_order_via_api(self.client_adv)
        order = Order.objects.get()

        cancel = self.client_adv.post(f'/api/search_ads/order/{order.order_id}/cancel/')
        self.assertEqual(cancel.status_code, 200)

        response = self.client_mod.get('/api/moderation/search_ads/pending/')
        self.assertEqual(response.data['count'], 0)
        response = self.client_mod.get('/api/moderation/pending_count/')
        self.assertEqual(response.data['total'], 0)

    def test_pending_count(self):
        create_search_order_via_api(self.client_adv)
        create_chat_order_via_api(self.client_adv, budget='10.00')
        create_chat_order_via_api(self.client_adv, budget='10.00')

        response = self.client_mod.get('/api/moderation/pending_count/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'search_ads': 1, 'chat_ads': 2, 'total': 3})

        # После одобрения счётчик уменьшается
        order = Order.objects.get()
        self.client_mod.post(f'/api/moderation/search_ads/{order.order_id}/approve/')
        response = self.client_mod.get('/api/moderation/pending_count/')
        self.assertEqual(response.data['total'], 2)

    def test_only_superadmin_deposits(self):
        payload = {'user_id': str(self.advertiser.user_id), 'amount': '25.00'}

        self.assertEqual(
            self.client_adv.post('/api/admin/balance/deposit/', payload, format='json').status_code, 403)
        self.assertEqual(
            self.client_mod.post('/api/admin/balance/deposit/', payload, format='json').status_code, 403)

        response = self.client_boss.post('/api/admin/balance/deposit/', payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Balance.objects.get(user=self.advertiser).amount, Decimal('125.00'))

    def test_only_superadmin_changes_roles(self):
        url = f'/api/auth/users/{self.advertiser.user_id}/role/'
        payload = {'role': 'MODERATOR'}

        self.assertEqual(self.client_adv.post(url, payload, format='json').status_code, 403)
        self.assertEqual(self.client_mod.post(url, payload, format='json').status_code, 403)

        response = self.client_boss.post(url, payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.advertiser.refresh_from_db()
        self.assertEqual(self.advertiser.role, User.Role.MODERATOR)

    def test_only_superadmin_lists_users(self):
        self.assertEqual(self.client_adv.get('/api/auth/users/').status_code, 403)
        self.assertEqual(self.client_mod.get('/api/auth/users/').status_code, 403)

        response = self.client_boss.get('/api/auth/users/', {'search': 'advertiser'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['role'], 'ADVERTISER')

    def test_anonymous_gets_401(self):
        anon = APIClient()
        self.assertEqual(anon.get('/api/moderation/pending_count/').status_code, 401)
        self.assertEqual(anon.post('/api/admin/balance/deposit/').status_code, 401)
