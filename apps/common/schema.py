# Типовые кусочки для @extend_schema — чтобы не повторять одни и те же словари в каждом view

# Ответ вида {"message": "..."}
MESSAGE_RESPONSE = {
    'type': 'object',
    'properties': {'message': {'type': 'string'}},
}

# Ответ-ошибка вида {"error": "..."} (наш кастомный формат ошибок)
ERROR_RESPONSE = {
    'type': 'object',
    'properties': {'error': {'type': 'string'}},
}

# Авторизация server-to-server эндпоинтов (permission HasServerApiKey):
# заголовок X-API-Key, JWT там не работает. Сама схема securitySchemes
# объявлена в SPECTACULAR_SETTINGS['APPEND_COMPONENTS'].
SERVER_API_KEY_AUTH = [{'serverApiKey': []}]
