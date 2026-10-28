

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
DEBUG = config("DEBUG", default=False, cast=bool)


ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# за nginx: доверяем его заголовкам о схеме/хосте
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

INTERNAL_IPS = [
    # ...
    "127.0.0.1",
    # ...
]

# Application definition

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    "django_q",
    "chat.apps.ChatConfig",
    "users.apps.UsersConfig",
    "shop.apps.ShopConfig",
    "companies.apps.CompaniesConfig",
    "cart.apps.CartConfig",
    "orders.apps.OrdersConfig",
    "checkout.apps.CheckoutConfig",
    "adminsortable2",
    "django_browser_reload",    
    "django.contrib.postgres",
    "treebeard",
    "django_extensions",
    "debug_toolbar",
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
    "django_browser_reload.middleware.BrowserReloadMiddleware",
    "debug_toolbar.middleware.DebugToolbarMiddleware",
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
                'shop.context_processors.popup_notice',
                'cart.context_processors.cart_counters',
                'companies.context_processors.seller',
            ],
        },
    },
]

WSGI_APPLICATION = 'tools_shop.wsgi.application'
ASGI_APPLICATION = 'tools_shop.asgi.application'


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

LOGOUT_REDIRECT_URL = "shop:index"





# Читаем строку и сразу бьем её по запятым
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:8002,http://127.0.0.1:8002",
    cast=Csv(),
)


REDIS_HOST = config("REDIS_HOST", default="127.0.0.1")
REDIS_PORT = config("REDIS_PORT", default=6379, cast=int)

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [(REDIS_HOST, REDIS_PORT)]},
    }
}


CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/1",
    }
}


Q_CLUSTER = {
    "name": "myshop",
    "workers": 2,
    "recycle": 500,
    "timeout": 60,
    "retry": 120,
    # Письмо/PDF может временно не отправиться (SMTP, WeasyPrint, сеть).
    # django-q2 повторит задачу, а после исчерпания попыток оставит ошибку
    # в истории задач; счёт при этом останется выставленным.
    "max_attempts": 3,
    "queue_limit": 50,
    "bulk": 10,
    "redis": {
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        "db": 0,
    },
    "save_limit": 10000,
}


RU_EMAIL_PATTERN = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.ru$"

# ---- почта и заявки -------------------------------------------------------
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="noreply@tools-service.ru"
)
# Адреса менеджеров, которым уходят уведомления о новых заявках.
MANAGER_NOTIFY_EMAILS = config("MANAGER_NOTIFY_EMAILS", default="", cast=Csv())

# Реквизиты продавца. Источник истины — модель ``companies.SellerProfile``
# (редактируется в админке). Этот словарь — только fallback для тестов и
# первого запуска. Пустые значения намеренно: заглушки с фиктивным ИНН и
# банком не должны попасть в настоящий счёт.
SELLER_REQUISITES = {
    "legal_form": config("SELLER_LEGAL_FORM", default="ooo"),
    "name": config("SELLER_NAME", default=""),
    "full_name": config("SELLER_FULL_NAME", default=""),
    "inn": config("SELLER_INN", default=""),
    "kpp": config("SELLER_KPP", default=""),
    "ogrn": config("SELLER_OGRN", default=""),
    "address": config("SELLER_ADDRESS", default=""),
    "postal_address": config("SELLER_POSTAL_ADDRESS", default=""),
    "phone": config("SELLER_PHONE", default=""),
    "email": config("SELLER_EMAIL", default=""),
    "website": config("SELLER_WEBSITE", default=""),
    "bank_name": config("SELLER_BANK_NAME", default=""),
    "bik": config("SELLER_BIK", default=""),
    "correspondent_account": config(
        "SELLER_CORRESPONDENT_ACCOUNT", default=""
    ),
    "checking_account": config(
        "SELLER_CHECKING_ACCOUNT", default=""
    ),
    "director": config("SELLER_DIRECTOR", default=""),
    "director_position": config(
        "SELLER_DIRECTOR_POSITION", default="Генеральный директор"
    ),
}

# Базовый адрес сайта для ссылок в письмах (без завершающего слэша).
SITE_URL = config("SITE_URL", default="http://localhost:8002").rstrip("/")

# SMTP для боевой отправки. В тестах используется locmem backend.
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=25, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=False, cast=bool)
EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=False, cast=bool)
EMAIL_TIMEOUT = config("EMAIL_TIMEOUT", default=30, cast=int)

# Ограничение POST на оформление заявки: 5 попыток в час с одного IP.
CHECKOUT_RATE_LIMIT = config("CHECKOUT_RATE_LIMIT", default=5, cast=int)
CHECKOUT_RATE_WINDOW = config("CHECKOUT_RATE_WINDOW", default=3600, cast=int)
# Включать только если перед Django стоит доверенный прокси, который
# перезаписывает X-Forwarded-For. Иначе клиент подделает IP и обойдёт лимит.
USE_X_FORWARDED_FOR = config("USE_X_FORWARDED_FOR", default=False, cast=bool)

# ---- подсказки реквизитов DaData -----------------------------------------
# Без DADATA_API_KEY подсказки для новых клиентов отключены, но повторные
# клиенты по-прежнему подгружаются из базы. Ключ используется только на
# сервере и не передаётся в шаблоны/JavaScript.
DADATA_API_KEY = config("DADATA_API_KEY", default="")
# Секрет нужен только для методов стандартизации; для Suggestions API
# достаточно API-ключа. Оставлен на случай расширения интеграции.
DADATA_SECRET_KEY = config("DADATA_SECRET_KEY", default="")
DADATA_SUGGEST_URL = config(
    "DADATA_SUGGEST_URL",
    default="https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party",
)
DADATA_TIMEOUT = config("DADATA_TIMEOUT", default=5, cast=int)
# Успешные ответы кэшируются, чтобы не тратить квоту на повторные запросы.
DADATA_CACHE_TTL = config("DADATA_CACHE_TTL", default=86400, cast=int)
# Отдельный лимит на кнопку «Заполнить по ИНН»: 10 запросов в минуту с IP.
DADATA_RATE_LIMIT = config("DADATA_RATE_LIMIT", default=10, cast=int)
DADATA_RATE_WINDOW = config("DADATA_RATE_WINDOW", default=60, cast=int)
# В админке менеджер проверяет несколько контрагентов подряд, поэтому лимит
# выше клиентского.
DADATA_ADMIN_RATE_LIMIT = config(
    "DADATA_ADMIN_RATE_LIMIT", default=30, cast=int
)

# Дополнительные разрешенные домены, которые не заканчиваются на .ru
EXTRA_ALLOWED_DOMAINS = ["yandex.by", "yandex.kz", "yandex.com"]

SESSION_COOKIE_NAME = "sessionid_hairshop"

# Корзина и избранное живут в сессии. cached_db: чтение из Redis, запись
# и в кэш, и в БД — сессии не теряются при перезапуске Redis.
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 90  # 90 дней

# CSRF_COOKIE_NAME = "csrftoken_hairshop"

# SESSION_COOKIE_SECURE = True  # Включить на деплое, чтобы куки передавались только по HTTPS
# CSRF_COOKIE_SECURE = True  # Включить на деплое, чтобы куки передавались только по HTTPS
# Web Push: use one persistent VAPID key pair for all deployments.
VAPID_PUBLIC_KEY = config("VAPID_PUBLIC_KEY", default="")
VAPID_PRIVATE_KEY = config("VAPID_PRIVATE_KEY", default="")
VAPID_SUBJECT = config("VAPID_SUBJECT", default="")

SESSION_COOKIE_HTTPONLY = True  # Куки сессии недоступны через JavaScript

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")