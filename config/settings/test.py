"""Test settings. Fast, deterministic, no external calls."""

from .base import *

DEBUG = False
SECRET_KEY = "test-only-not-a-real-secret"  # noqa: S105
ALLOWED_HOSTS = ["*"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Tasks run inline so tests assert on outcomes, not on queue state.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# django-axes interferes with auth tests; exercised in its own suite.
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]

LOGGING["root"]["level"] = "ERROR"
