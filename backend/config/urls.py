from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.views import AuditEventViewSet, DisputeViewSet, OrderViewSet, dashboard_view
from graph import views as graph_views
from webhooks.views import paypal_webhook

router = DefaultRouter()
router.register("orders", OrderViewSet, basename="order")
router.register("disputes", DisputeViewSet, basename="dispute")
router.register("audit", AuditEventViewSet, basename="audit")


def health(request):
    from django.conf import settings
    return JsonResponse({"ok": True, "paypal_mode": settings.PAYPAL_MODE, "ai_provider": settings.AI_PROVIDER})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("api/webhooks/paypal/", paypal_webhook),
    path("api/dashboard/", dashboard_view),
    path("api/graph/rings/", graph_views.rings),
    path("api/graph/buyers/<str:payer_id>/", graph_views.buyer_graph),
    path("api/", include(router.urls)),
]
