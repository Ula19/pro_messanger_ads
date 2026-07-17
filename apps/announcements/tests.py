from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Announcement, AnnouncementDismissal

User = get_user_model()

API_KEY = 'test-server-key'


def create_banner(**extra):
    """Хелпер: баннер с разумными дефолтами"""
    fields = {'title': 'Наш канал', 'text': 'Подпишись на новости', 'link': 'tg://resolve?domain=test'}
    fields.update(extra)
    return Announcement.objects.create(**fields)


class AnnouncementManageTests(TestCase):
    """CRUD баннеров: только суперадмин"""

    def setUp(self):
        self.superadmin = User.objects.create_superuser('boss', 'boss@test.uz', 'pass12345')
        self.advertiser = User.objects.create_user('advertiser', password='pass12345')
        self.moderator = User.objects.create_user('moderator', password='pass12345')
        self.moderator.role = User.Role.MODERATOR
        self.moderator.save(update_fields=['role'])

        self.client_boss = APIClient()
        self.client_boss.force_authenticate(self.superadmin)

    def test_only_superadmin_manages(self):
        for user in (self.advertiser, self.moderator):
            client = APIClient()
            client.force_authenticate(user)
            self.assertEqual(client.get('/api/banner_ads/manage/').status_code, 403)
            self.assertEqual(client.post('/api/banner_ads/manage/', {}).status_code, 403)

        anon = APIClient()
        self.assertEqual(anon.get('/api/banner_ads/manage/').status_code, 401)

    def test_create_banner(self):
        response = self.client_boss.post('/api/banner_ads/manage/', {
            'title': 'Важно',
            'text': 'Обновите приложение',
            'link': 'https://example.com',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['dismissible'])
        self.assertTrue(response.data['is_active'])
        self.assertEqual(response.data['created_by'], 'boss')
        self.assertEqual(response.data['dismissals_count'], 0)

    def test_ends_before_starts_rejected(self):
        now = timezone.now()
        response = self.client_boss.post('/api/banner_ads/manage/', {
            'title': 'Баннер', 'text': 'Текст',
            'starts_at': now.isoformat(),
            'ends_at': (now - timedelta(days=1)).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_patch_single_date_validated_against_instance(self):
        """PATCH только ends_at сверяется со старым starts_at"""
        banner = create_banner(starts_at=timezone.now())
        response = self.client_boss.patch(f'/api/banner_ads/manage/{banner.id}/', {
            'ends_at': (timezone.now() - timedelta(days=1)).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_manage_list_shows_stats(self):
        banner = create_banner()
        AnnouncementDismissal.objects.create(announcement=banner, viewer_id='v1')
        AnnouncementDismissal.objects.create(announcement=banner, viewer_id='v2')

        response = self.client_boss.get('/api/banner_ads/manage/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'][0]['dismissals_count'], 2)

    def test_created_by_null_stays_in_patch_response(self):
        """Создателя удалили — и GET, и PATCH отдают created_by: null (ключ не пропадает)"""
        banner = create_banner(created_by=User.objects.create_superuser('old', 'o@t.uz', 'pass12345'))
        User.objects.get(username='old').delete()  # FK SET_NULL

        get_resp = self.client_boss.get(f'/api/banner_ads/manage/{banner.id}/')
        self.assertIn('created_by', get_resp.data)
        self.assertIsNone(get_resp.data['created_by'])

        patch_resp = self.client_boss.patch(f'/api/banner_ads/manage/{banner.id}/',
                                            {'priority': 1}, format='json')
        self.assertEqual(patch_resp.status_code, 200)
        self.assertIn('created_by', patch_resp.data)
        self.assertIsNone(patch_resp.data['created_by'])

    def test_deactivate_and_delete(self):
        banner = create_banner()
        response = self.client_boss.patch(f'/api/banner_ads/manage/{banner.id}/',
                                          {'is_active': False}, format='json')
        self.assertEqual(response.status_code, 200)
        banner.refresh_from_db()
        self.assertFalse(banner.is_active)

        response = self.client_boss.delete(f'/api/banner_ads/manage/{banner.id}/')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Announcement.objects.exists())


@override_settings(AD_SERVER_API_KEY=API_KEY)
class AnnouncementClientTests(TestCase):
    """Выдача баннеров NovaGram: окно дат, закрытия, клики"""

    def setUp(self):
        self.server = APIClient()

    def _active(self, viewer_id='v1'):
        return self.server.post('/api/banner_ads/active/', {'viewer_id': viewer_id},
                                format='json', HTTP_X_API_KEY=API_KEY)

    def _dismiss(self, banner_id, viewer_id='v1'):
        return self.server.post('/api/banner_ads/dismiss/',
                                {'announcement_id': str(banner_id), 'viewer_id': viewer_id},
                                format='json', HTTP_X_API_KEY=API_KEY)

    def test_api_key_required(self):
        banner = create_banner()
        for url, body in (
            ('/api/banner_ads/active/', {'viewer_id': 'v1'}),
            ('/api/banner_ads/dismiss/', {'announcement_id': str(banner.id), 'viewer_id': 'v1'}),
            ('/api/banner_ads/click/', {'announcement_id': str(banner.id)}),
        ):
            no_key = self.server.post(url, body, format='json')
            self.assertIn(no_key.status_code, (401, 403))
            wrong_key = self.server.post(url, body, format='json', HTTP_X_API_KEY='wrong')
            self.assertIn(wrong_key.status_code, (401, 403))

    def test_date_window(self):
        now = timezone.now()
        create_banner(title='Будущий', starts_at=now + timedelta(days=1))
        create_banner(title='Просроченный', starts_at=now - timedelta(days=2),
                      ends_at=now - timedelta(days=1))
        create_banner(title='Выключенный', is_active=False)
        create_banner(title='Бессрочный')  # ends_at=NULL — показывается

        response = self._active()
        self.assertEqual(response.status_code, 200)
        titles = [b['title'] for b in response.data]
        self.assertEqual(titles, ['Бессрочный'])

    def test_dismiss_hides_only_for_that_viewer(self):
        banner = create_banner()

        response = self._dismiss(banner.id, viewer_id='v1')
        self.assertEqual(response.status_code, 200)

        self.assertEqual(len(self._active('v1').data), 0)   # v1 закрыл — не видит
        self.assertEqual(len(self._active('v2').data), 1)   # v2 видит

    def test_dismiss_idempotent(self):
        banner = create_banner()
        self.assertEqual(self._dismiss(banner.id).status_code, 200)
        self.assertEqual(self._dismiss(banner.id).status_code, 200)
        self.assertEqual(AnnouncementDismissal.objects.count(), 1)

    def test_dismiss_missing_banner(self):
        response = self._dismiss('00000000-0000-0000-0000-000000000000')
        self.assertEqual(response.status_code, 404)

    def test_non_dismissible_banner_cannot_be_dismissed(self):
        banner = create_banner(title='Важно', dismissible=False)
        response = self._dismiss(banner.id)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AnnouncementDismissal.objects.exists())
        # Баннер по-прежнему показывается
        self.assertEqual(len(self._active().data), 1)

    def test_click_increments(self):
        banner = create_banner()
        response = self.server.post('/api/banner_ads/click/',
                                    {'announcement_id': str(banner.id)},
                                    format='json', HTTP_X_API_KEY=API_KEY)
        self.assertEqual(response.status_code, 200)
        banner.refresh_from_db()
        self.assertEqual(banner.clicks, 1)

    def test_click_on_disabled_banner_still_counts(self):
        """Клик мог прийти с задержкой, когда баннер уже выключили"""
        banner = create_banner(is_active=False)
        response = self.server.post('/api/banner_ads/click/',
                                    {'announcement_id': str(banner.id)},
                                    format='json', HTTP_X_API_KEY=API_KEY)
        self.assertEqual(response.status_code, 200)
        banner.refresh_from_db()
        self.assertEqual(banner.clicks, 1)

    def test_click_missing_banner(self):
        response = self.server.post('/api/banner_ads/click/',
                                    {'announcement_id': '00000000-0000-0000-0000-000000000000'},
                                    format='json', HTTP_X_API_KEY=API_KEY)
        self.assertEqual(response.status_code, 404)

    def test_ordering_by_priority_then_newest(self):
        create_banner(title='Обычный', priority=0)
        create_banner(title='Срочный', priority=10)
        create_banner(title='Обычный новее', priority=0)

        titles = [b['title'] for b in self._active().data]
        self.assertEqual(titles, ['Срочный', 'Обычный новее', 'Обычный'])
