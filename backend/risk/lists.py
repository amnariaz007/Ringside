"""
Static lookup lists.

In production these would be refreshed from maintained sources (for example
the open-source disposable-email-domains list). For the hackathon a curated
sample is enough and keeps the engine deterministic.
"""

DISPOSABLE_EMAIL_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "temp-mail.org", "yopmail.com", "trashmail.com", "sharklasers.com",
    "getnada.com", "dispostable.com", "maildrop.cc", "throwawaymail.com",
    "fakeinbox.com", "mintemail.com", "burnermail.io",
})

# Words that show up in package-forwarding addresses. Matched against the
# normalised address text. Demo forwarder names are fictional.
RESHIPPER_KEYWORDS = (
    "forwarding", "forwarder", "reship", "re ship", "package consolidation",
    "freight", "parcelhop", "boxbridge",
)
