"""Local development. Never used in a deployed environment."""

from .base import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]  # noqa: S104

INSTALLED_APPS += ["django_extensions", "debug_toolbar", "nplusone.ext.django"]
MIDDLEWARE = [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "nplusone.ext.django.NPlusOneMiddleware",
    *MIDDLEWARE,
]
INTERNAL_IPS = ["127.0.0.1"]

# Surface N+1 queries during development rather than in the production p95.
NPLUSONE_RAISE = False
NPLUSONE_LOG_LEVEL = 30  # WARNING

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
CORS_ALLOW_ALL_ORIGINS = True
LOGGING["handlers"]["console"]["formatter"] = "simple"
