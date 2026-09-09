"""Root URL configuration.

Versioned API under /api/v1/. The Django admin is the staff back office
(docs/backend/06-admin-ops.md §1) and is deliberately not exposed at /admin/.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from d2r.core.health import health, liveness

admin.site.site_header = "Drive 2 Retail"
admin.site.site_title = "Drive 2 Retail"
admin.site.index_title = "Operations"

api_v1 = [
    path("auth/", include("d2r.accounts.api.urls")),
    path("account/", include("d2r.accounts.api.account_urls")),
    path("catalogue/", include("d2r.catalogue.api.urls")),
    path("cart/", include("d2r.carts.api.urls")),
    path("checkout/", include("d2r.orders.api.checkout_urls")),
    path("delivery/", include("d2r.delivery.api.urls")),
    path("driver/", include("d2r.dispatch.api.driver_urls")),
    path("webhooks/", include("d2r.payments.api.webhook_urls")),
    path("admin/", include("d2r.ops.api.urls")),
]

urlpatterns = [
    path("staff/", admin.site.urls),
    path("health/", health, name="health"),
    path("health/live/", liveness, name="liveness"),
    path("api/v1/", include((api_v1, "v1"), namespace="v1")),
    # OpenAPI — the Next.js clients are generated from this schema
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
