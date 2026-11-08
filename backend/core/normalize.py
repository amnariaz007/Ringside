"""Hashing and normalisation helpers for buyer identity and addresses."""

import hashlib
import hmac
import re

from django.conf import settings


def _hash(value: str) -> str:
    """Keyed HMAC-SHA256, so hashes can't be brute-forced without the secret key."""
    return hmac.new(settings.PII_HASH_SALT.encode(), value.encode(), hashlib.sha256).hexdigest()


def hash_email(email: str) -> str:
    email = email.strip().lower()
    return _hash(email) if email else ""


def email_domain(email: str) -> str:
    email = email.strip().lower()
    return email.rsplit("@", 1)[-1] if "@" in email else ""


def email_stem(email: str) -> str:
    """'Ali.K1+promo@Mail.com' -> 'alik@mail.com'. Catches numbered throwaway accounts."""
    local, _, domain = email.strip().lower().partition("@")
    local = local.split("+", 1)[0]
    local = re.sub(r"[\d._-]", "", local)
    return f"{local}@{domain}"


def hash_email_stem(email: str) -> str:
    # A missing email must not make every email-less buyer "share" a pattern.
    return _hash(email_stem(email)) if email.strip() else ""


def hash_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return _hash(digits) if digits else ""


_ABBREVIATIONS = {
    "street": "st", "road": "rd", "avenue": "ave", "suite": "ste",
    "apartment": "apt", "building": "bldg", "floor": "fl", "unit": "unit",
}


def normalize_address_text(text: str) -> str:
    text = re.sub(r"[^\w\s]", " ", (text or "").lower())
    words = [_ABBREVIATIONS.get(w, w) for w in text.split()]
    return " ".join(words)


def address_key(line1: str, line2: str, city: str, postal_code: str, country_code: str) -> str:
    """Stable key so '12 Main Street, Apt 4' and '12 main st apt 4' are one address."""
    parts = [
        normalize_address_text(line1),
        normalize_address_text(line2),
        normalize_address_text(city),
        re.sub(r"\s", "", (postal_code or "").lower()),
        (country_code or "").upper(),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
