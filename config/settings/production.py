"""Production. Staging imports from here and overrides only what differs."""

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *

# Refuse to boot rather than serve with DEBUG on.
assert not DEBUG, "DEBUG must be False in production"
assert ALLOWED_HOSTS, "ALLOWED_HOSTS must be set in production"

# ── HTTPS / headers — docs/backend/04-security.md §5 ──────────────────────
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_TRUSTED_ORIGINS = [FRONTEND_URL, ADMIN_URL]

# ── Media on S3 ───────────────────────────────────────────────────────────
STORAGES["default"] = {
    "BACKEND": "storages.backends.s3.S3Storage",
    "OPTIONS": {
        "bucket_name": env("AWS_STORAGE_BUCKET_NAME"),
        "endpoint_url": env("AWS_S3_ENDPOINT_URL", default=None),
        "region_name": env("AWS_S3_REGION_NAME", default="eu-west-1"),
        "custom_domain": env("AWS_S3_CUSTOM_DOMAIN", default=None),
        "querystring_auth": False,
        "file_overwrite": False,
        "default_acl": None,
    },
}

# ── Observability ─────────────────────────────────────────────────────────
if SENTRY_DSN := env("SENTRY_DSN", default=""):
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1),
        send_default_pii=False,  # never ship PII to a third party
        environment=env("SENTRY_ENVIRONMENT", default="production"),
    )
