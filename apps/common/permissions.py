from django.conf import settings
from django.utils.crypto import constant_time_compare
from rest_framework import permissions


class HasServerApiKey(permissions.BasePermission):
    """
    Пускает только запросы с валидным серверным API-ключом (server-to-server).

    Ключ приходит в заголовке X-API-Key и сверяется с settings.AD_SERVER_API_KEY
    через constant_time_compare (защита от timing-атаки при подборе). Если ключ на
    бэкенде не задан — доступ закрыт (fail-closed): пустой .env не должен открывать
    эндпоинты показа/клика рекламы.
    """
    message = 'Неверный или отсутствующий API-ключ.'

    def has_permission(self, request, view):
        expected = settings.AD_SERVER_API_KEY
        if not expected:
            return False
        provided = request.headers.get('X-API-Key')
        if not provided:
            return False
        return constant_time_compare(provided, expected)


class IsModerator(permissions.BasePermission):
    """Пускает только модераторов и суперадмина (проверка модерации рекламы)."""
    message = 'Требуются права модератора.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_moderator)


class IsSuperAdmin(permissions.BasePermission):
    """Пускает только суперадмина (создаётся через createsuperuser)."""
    message = 'Требуются права суперадмина.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)
