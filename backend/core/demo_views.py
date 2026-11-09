"""
Demo controls for the logged-in seller: play a simulated PayPal event, or reset
the demo shop. The events go through the same webhook pipeline as real ones;
they are labelled "demo" in the UI. Turn off with DEMO_CONTROLS=false.
"""

from django.conf import settings
from django.core.management import call_command
from rest_framework.decorators import api_view
from rest_framework.response import Response

from audit.models import record
from core.models import Dispute, Order
from paypal_integration import demo

SCENARIOS = {"normal", "scammer", "ring", "dispute"}


@api_view(["POST"])
def play(request, scenario: str):
    if not settings.DEMO_CONTROLS:
        return Response({"detail": "Demo controls are turned off."}, status=404)
    if scenario not in SCENARIOS:
        return Response({"detail": "Unknown demo event."}, status=404)
    try:
        result = demo.live_scenario(scenario)
    except RuntimeError as exc:
        return Response({"detail": str(exc)}, status=409)
    record("seller", "demo.event_played", scenario=scenario, result=result.message[:200])
    if result.status != 200:
        return Response({"detail": result.message}, status=502)
    if scenario == "dispute":
        latest = Dispute.objects.order_by("-created_at").first()
        return Response({"detail": result.message, "go": f"/disputes/{latest.pk}" if latest else "/disputes"})
    latest = Order.objects.order_by("-created_at").first()
    return Response({"detail": result.message, "go": f"/orders/{latest.pk}" if latest else "/orders"})


@api_view(["POST"])
def reset(request):
    """Wipe the shop's data and seed the 30-day history again. Real orders already taken are forgotten too."""
    if not settings.DEMO_CONTROLS:
        return Response({"detail": "Demo controls are turned off."}, status=404)
    if request.data.get("confirm") is not True:
        return Response({"detail": "Confirmation required."}, status=400)
    call_command("seed_demo", "--reset")
    record("seller", "demo.reset", by=request.user.get_username())
    return Response({"detail": "Demo data reset.", "go": "/"})
