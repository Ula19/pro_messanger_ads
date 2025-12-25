FROM python:3.11-alpine

# Устанавливаем системные зависимости
RUN apk update && apk add --no-cache \
    postgresql-dev \
    gcc \
    python3-dev \
    musl-dev \
    libffi-dev \
    openssl-dev

WORKDIR /app

# Копируем зависимости отдельно для кэширования
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем проект
COPY . .

# Создаем папки для статики и медиа
RUN mkdir -p staticfiles media

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "core.wsgi:application"]