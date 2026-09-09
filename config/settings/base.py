"""Settings shared by every environment.

Environment-specific modules import * from here and override. Nothing in this
file may assume a particular environment; anything that differs belongs in
local.py, staging.py, production.py or test.py.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env()
env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
SITE_URL = env("DJANGO_SITE_URL", default="http://localhost:8000")
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:3000")
ADMIN_URL = env("ADMIN_URL", default="http://localhost:3001")

# ── Applications ──────────────────────────────────────────────────────────

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "corsheaders",
    "django_celery_beat",
    "django_celery_results",
    "axes",
]

# Order matters: accounts must load before anything referencing AUTH_USER_MODEL.
LOCAL_APPS = [
    "d2r.core",
    "d2r.accounts",
    "d2r.catalogue",
    "d2r.pricing",
    "d2r.inventory",
    "d2r.carts",
    "d2r.orders",
    "d2r.payments",
    "d2r.delivery",
    "d2r.dispatch",
    "d2r.procurement",
    "d2r.content",
    "d2r.ops",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "d2r.core.middleware.RequestIDMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "d2r.core.middleware.AuditContextMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "d2r" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ── Database ──────────────────────────────────────────────────────────────

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=0)
DATABASES["default"]["ATOMIC_REQUESTS"] = False  # transactions are explicit, in services
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Cache ─────────────────────────────────────────────────────────────────

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        "KEY_PREFIX": "d2r",
    }
}

# ── Authentication ────────────────────────────────────────────────────────

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",  # must be first
    "django.contrib.auth.backends.ModelBackend",
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Brute-force protection — see docs/backend/04-security.md §1.3
AXES_FAILURE_LIMIT = 10
AXES_COOLOFF_TIME = 0.25  # 15 minutes
AXES_LOCKOUT_PARAMETERS = ["ip_address", "username"]
AXES_RESET_ON_SUCCESS = True

# ── DRF ───────────────────────────────────────────────────────────────────

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "d2r.core.pagination.PageNumberPagination",
    "PAGE_SIZE": 24,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "d2r.core.exceptions.exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/min",
        "user": "600/min",
        "login": "5/min",
        "register": "3/hour",
        "password_reset": "3/hour",
        "search_suggest": "30/min",
        "checkout": "10/hour",
    },
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "public_id",
    "USER_ID_CLAIM": "sub",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Drive 2 Retail API",
    "DESCRIPTION": (
        "Wholesale e-commerce API for Drive 2 Retail Limited. "
        "See docs/backend/02-api.md for conventions, error codes and rate limits."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "ENUM_NAME_OVERRIDES": {
        "OrderStatus": "d2r.orders.constants.OrderStatus.choices",
        "FulfilmentStatus": "d2r.orders.constants.FulfilmentStatus.choices",
        "PaymentProvider": "d2r.payments.constants.PaymentProvider.choices",
        "PaymentAttemptStatus": "d2r.payments.constants.PaymentAttemptStatus.choices",
    },
    "TAGS": [
        {"name": "auth", "description": "Registration, login, tokens, password reset"},
        {"name": "catalogue", "description": "Products, categories, brands, search"},
        {"name": "cart", "description": "Cart and validation"},
        {"name": "checkout", "description": "Order placement and payment"},
        {"name": "account", "description": "Business account, addresses, orders, invoices"},
        {"name": "admin", "description": "Staff-only operations"},
        {"name": "driver", "description": "Driver app — trips and proof of delivery"},
        {"name": "webhooks", "description": "Payment provider callbacks"},
    ],
}

# ── Celery ────────────────────────────────────────────────────────────────

CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="django-db")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Africa/Lagos"
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Payment work must never queue behind a 20,000-row import.
CELERY_TASK_ROUTES = {
    "d2r.payments.*": {"queue": "critical"},
    "d2r.ops.tasks.import_*": {"queue": "bulk"},
    "d2r.ops.tasks.report_*": {"queue": "bulk"},
    "*": {"queue": "default"},
}

# ── Email (Resend) ────────────────────────────────────────────────────────

EMAIL_BACKEND = "d2r.core.email.ResendEmailBackend"
RESEND_API_KEY = env("RESEND_API_KEY", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Drive 2 Retail <noreply@drive2retail.com>")
SUPPORT_EMAIL = env("SUPPORT_EMAIL", default="support@drive2retail.com")

# ── Payments ──────────────────────────────────────────────────────────────

PAYMENT_ACTIVE_GATEWAY = env("PAYMENT_ACTIVE_GATEWAY", default="paystack")
PAYSTACK_SECRET_KEY = env("PAYSTACK_SECRET_KEY", default="")
PAYSTACK_PUBLIC_KEY = env("PAYSTACK_PUBLIC_KEY", default="")
PAYSTACK_WEBHOOK_IPS = env.list("PAYSTACK_WEBHOOK_IPS", default=[])
FLUTTERWAVE_SECRET_KEY = env("FLUTTERWAVE_SECRET_KEY", default="")
FLUTTERWAVE_WEBHOOK_HASH = env("FLUTTERWAVE_WEBHOOK_HASH", default="")

# ── Business rules ────────────────────────────────────────────────────────

DEFAULT_CURRENCY = env("DEFAULT_CURRENCY", default="NGN")
DEFAULT_TAX_RATE = env.float("DEFAULT_TAX_RATE", default=7.5)
CHECKOUT_RESERVATION_TTL_MINUTES = env.int("CHECKOUT_RESERVATION_TTL_MINUTES", default=20)
ACCOUNTS_REQUIRE_APPROVAL = env.bool("ACCOUNTS_REQUIRE_APPROVAL", default=True)

# ── i18n / tz ─────────────────────────────────────────────────────────────

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Lagos"  # storage is UTC; this is the presentation zone
USE_I18N = True
USE_TZ = True

# ── Static & media ────────────────────────────────────────────────────────

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# ── CORS ──────────────────────────────────────────────────────────────────

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True

# ── Logging ───────────────────────────────────────────────────────────────

LOG_LEVEL = env("LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "d2r.core.logging.JSONFormatter"},
        "simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "filters": {"request_id": {"()": "d2r.core.logging.RequestIDFilter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_id"],
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "d2r": {"level": LOG_LEVEL, "propagate": True},
    },
}
