

import os
from pathlib import Path

from decouple import Csv, config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!

SECRET_KEY = config("SECRET_KEY")
# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True


ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="").split(",")

INTERNAL_IPS = [
    # ...
    "127.0.0.1",
    # ...
]

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    "users.apps.UsersConfig",
    "shop.apps.ShopConfig",
    "django_extensions",
    "debug_toolbar",
    "django_q",
    "django_cleanup.apps.CleanupConfig",
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # "debug_toolbar.middleware.DebugToolbarMiddleware",
]

ROOT_URLCONF = 'tools_shop.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, "templates")],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'tools_shop.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST"),
        "PORT": config("DB_PORT"),
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "users.validators.RuMinimumLengthValidator", "OPTIONS": {"min_length": 6}},
    {
        "NAME": "users.validators.RuCommonPasswordValidator",
    },
    {
        "NAME": "users.validators.RuNumericPasswordValidator",
    },
    {
        "NAME": "users.validators.RuUserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ("username", "email"), "max_similarity": 0.6},
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "ru"

TIME_ZONE = "Asia/Novosibirsk"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "/static/"
# Папка, где лежат ваши исходные файлы (JS, CSS, картинки)
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "static"),
]


# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")


MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = "/media/"


AUTH_USER_MODEL = "users.User"


# Читаем строку и сразу бьем её по запятым
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:8002,http://127.0.0.1:8002",
    cast=Csv(),
)


REDIS_HOST = config("REDIS_HOST", default="127.0.0.1")
REDIS_PORT = config("REDIS_PORT", default=6379, cast=int)

Q_CLUSTER = {
    "name": "myshop",
    "workers": 2,
    "recycle": 500,
    "timeout": 60,
    "retry": 120,
    "queue_limit": 50,
    "bulk": 10,
    "redis": {
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        "db": 0,
    },
    "save_limit": 10000,
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/1",
    }
}


RU_EMAIL_PATTERN = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.ru$"

# Дополнительные разрешенные домены, которые не заканчиваются на .ru
EXTRA_ALLOWED_DOMAINS = ["yandex.by", "yandex.kz", "yandex.com"]

SESSION_COOKIE_NAME = "sessionid_hairshop"

# CSRF_COOKIE_NAME = "csrftoken_hairshop"

# SESSION_COOKIE_SECURE = True  # Включить на деплое, чтобы куки передавались только по HTTPS
# CSRF_COOKIE_SECURE = True  # Включить на деплое, чтобы куки передавались только по HTTPS
SESSION_COOKIE_HTTPONLY = True  # Куки сессии недоступны через JavaScript