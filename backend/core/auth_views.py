"""
Seller login. Plain Django views (not DRF) so CSRF protection applies to the
login form itself, and a simple per-IP limit slows down password guessing.
"""

import json

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from audit.models import record


def _user_json(user):
    return {"username": user.get_username(), "name": user.get_full_name() or user.get_username()}


def _client_ip(request) -> str:
    # Behind a reverse proxy (Caddy/nginx) the first X-Forwarded-For entry is the client.
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "unknown")


@require_GET
@ensure_csrf_cookie
def me(request):
    """Who is logged in. Also sets the CSRF cookie the frontend needs for POSTs."""
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False})
    return JsonResponse({"authenticated": True, "user": _user_json(request.user)})


@require_POST
@csrf_protect
def login_view(request):
    key = f"login-attempts:{_client_ip(request)}"
    attempts = cache.get(key, 0)
    if attempts >= settings.LOGIN_ATTEMPTS_PER_WINDOW:
        return JsonResponse({"detail": "Too many attempts. Try again in a few minutes."}, status=429)
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"detail": "Malformed request."}, status=400)
    user = authenticate(request, username=str(body.get("username", "")).strip(), password=str(body.get("password", "")))
    if user is None or not user.is_active:
        cache.set(key, attempts + 1, settings.LOGIN_WINDOW_SECONDS)
        record("system", "auth.login_failed", username=str(body.get("username", ""))[:80])
        return JsonResponse({"detail": "That email and password don't match."}, status=400)
    login(request, user)
    cache.delete(key)
    record("seller", "auth.login", username=user.get_username())
    return JsonResponse({"authenticated": True, "user": _user_json(user)})


@require_POST
@csrf_protect
def logout_view(request):
    if request.user.is_authenticated:
        record("seller", "auth.logout", username=request.user.get_username())
    logout(request)
    return JsonResponse({"authenticated": False})
