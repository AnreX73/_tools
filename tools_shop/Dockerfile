FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Добавляем ffmpeg для сжатия видео
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libpq-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install gunicorn

COPY . .

EXPOSE 8000

# Запускаем migrate, collectstatic, затем gunicorn и qcluster параллельно
CMD ["sh", "-c", "\
    python manage.py migrate --noinput && \
    python manage.py collectstatic --no-input && \
    exec gunicorn --workers 3 --bind 0.0.0.0:8000 hair_shop.wsgi:application \
"]