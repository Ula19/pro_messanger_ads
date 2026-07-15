from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.billing.models import Balance

User = get_user_model()


class RegistrationAndRoleTests(TestCase):
    """Регистрация: каждый новый пользователь — рекламодатель, роль снаружи не задать"""

    def test_registration_creates_advertiser_with_balance(self):
        client = APIClient()
        response = client.post('/api/auth/register/', {
            'username': 'newuser',
            'password': 'Str0ngPass!23',
            'password2': 'Str0ngPass!23',
            'email': 'new@test.uz',
            # Пытаемся протащить роль — она должна быть проигнорирована
            'role': 'MODERATOR',
        }, format='json')
        self.assertEqual(response.status_code, 201)

        user = User.objects.get(username='newuser')
        self.assertEqual(user.role, User.Role.ADVERTISER)
        self.assertTrue(Balance.objects.filter(user=user).exists())

    def test_login_returns_role(self):
        User.objects.create_user('someuser', password='Str0ngPass!23')

        client = APIClient()
        response = client.post('/api/auth/login/', {
            'username': 'someuser',
            'password': 'Str0ngPass!23',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)
        self.assertEqual(response.data['role'], 'ADVERTISER')

    def test_profile_returns_role(self):
        user = User.objects.create_user('someuser', password='pass12345')
        client = APIClient()
        client.force_authenticate(user)

        response = client.get('/api/auth/profile/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['role'], 'ADVERTISER')
        self.assertNotIn('is_admin', response.data)

    def test_superadmin_assigns_moderator(self):
        superadmin = User.objects.create_superuser('boss', 'boss@test.uz', 'pass12345')
        user = User.objects.create_user('future_mod', password='pass12345')

        client = APIClient()
        client.force_authenticate(superadmin)
        response = client.post(f'/api/auth/users/{user.user_id}/role/',
                               {'role': 'MODERATOR'}, format='json')
        self.assertEqual(response.status_code, 200)

        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.MODERATOR)
        self.assertTrue(user.is_moderator)

    def test_role_change_rejects_bad_role(self):
        superadmin = User.objects.create_superuser('boss', 'boss@test.uz', 'pass12345')
        user = User.objects.create_user('someuser', password='pass12345')

        client = APIClient()
        client.force_authenticate(superadmin)
        response = client.post(f'/api/auth/users/{user.user_id}/role/',
                               {'role': 'SUPERMAN'}, format='json')
        self.assertEqual(response.status_code, 400)
