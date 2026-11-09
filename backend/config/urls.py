from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core import auth_views, demo_views
from core.views import AuditEventViewSet, DisputeViewSet, OrderViewSet, dashboard_view
from disputes import views as copilot_views
from graph import views as graph_views
from shop import views as shop_views
from webhooks.views import paypal_webhook

router = DefaultRouter()
router.register("orders", OrderViewSet, basename="order")
router.register("disputes", DisputeViewSet, basename="dispute")
router.register("audit", AuditEventViewSet, basename="audit")


def health(request):
    from django.conf import settings
    return JsonResponse({
        "ok": True, "paypal_mode": settings.PAYPAL_MODE, "ai_provider": settings.AI_PROVIDER,
        "demo_controls": settings.DEMO_CONTROLS,
        # Booleans only: enough to see whether sandbox setup is complete, never the values.
        "paypal_setup": {"keys": bool(settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET),
                         "webhook_id": bool(settings.PAYPAL_WEBHOOK_ID),
                         "merchant_id": bool(settings.PAYPAL_MERCHANT_ID)},
    })


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("api/auth/me/", auth_views.me),
    path("api/auth/login/", auth_views.login_view),
    path("api/auth/logout/", auth_views.logout_view),
    path("api/webhooks/paypal/", paypal_webhook),
    path("api/shop/", shop_views.shop_info),
    path("api/shop/orders/", shop_views.create_order),
    path("api/shop/orders/<str:order_id>/capture/", shop_views.capture_order),
    path("api/demo/reset/", demo_views.reset),
    path("api/demo/<str:scenario>/", demo_views.play),
    path("api/dashboard/", dashboard_view),
    path("api/graph/rings/", graph_views.rings),
    path("api/graph/buyers/<str:payer_id>/", graph_views.buyer_graph),
    path("api/disputes/<int:pk>/copilot/", copilot_views.case_detail),
    path("api/disputes/<int:pk>/copilot/regenerate/", copilot_views.case_regenerate),
    path("api/disputes/<int:pk>/copilot/submit/", copilot_views.case_submit),
    path("api/", include(router.urls)),
]
