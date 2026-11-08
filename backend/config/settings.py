"""
PayGuard settings.

Everything that differs between laptop, Render and tests is read from
environment variables. Safe local defaults let the project run with no
accounts at all: SQLite, a fake PayPal client and template-based AI text.
"""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


# Render sets RENDER=true. Off Render (laptop, tests) dev defaults are allowed;
# on Render the app refuses to start with insecure defaults.
ON_RENDER = env_bool("RENDER", False)
DEV_SECRET_KEY = "dev-only-insecure-key-change-me"
DEV_PII_SALT = "payguard-dev-salt"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", DEV_SECRET_KEY)
DEBUG = env_bool("DJANGO_DEBUG", not ON_RENDER)
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "core",
    "graph",
    "risk",
    "paypal_integration",
    "webhooks",
    "ai",
    "audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "config.wsgi.application"

# SQLite locally; set DATABASE_URL (Render Postgres) in production.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
}

# --- PayGuard switches -------------------------------------------------------

# "mock" uses recorded PayPal-shaped JSON; "sandbox" calls api-m.sandbox.paypal.com.
PAYPAL_MODE = os.environ.get("PAYPAL_MODE", "mock")
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "")
PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID", "")
PAYPAL_API_BASE = os.environ.get("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com")

# "template" needs no key. Real providers (gemini, groq, claude) plug in later.
AI_PROVIDER = os.environ.get("AI_PROVIDER", "template")

# HMAC key for hashing buyer emails and phones. Must be secret in production.
PII_HASH_SALT = os.environ.get("PII_HASH_SALT", DEV_PII_SALT)

# Webhook bodies are small; refuse anything large before it reaches the handler.
DATA_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024

if not DEBUG:
    from django.core.exceptions import ImproperlyConfigured

    if ON_RENDER and (SECRET_KEY == DEV_SECRET_KEY or PII_HASH_SALT == DEV_PII_SALT):
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY and PII_HASH_SALT before deploying.")
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = ON_RENDER
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_CONTENT_TYPE_NOSNIFF = True
