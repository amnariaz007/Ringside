"""
Ring summaries written by the LLM, off the request path.

A page load must never wait on the model: Gemini can take tens of seconds when
busy. So the first time a ring is seen, the page gets the template text marked
"pending" and a background thread asks the model. The answer is stored (keyed
by the ring's stats), and every later load returns it instantly. When the
ring's stats change (a new order, refund or dispute), a new summary is written.

`manage.py warm_ai` writes all summaries ahead of time, e.g. before a demo.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time

from django.core.cache import cache
from django.db import close_old_connections

from .models import AICache
from .providers import TemplateProvider, get_provider

TASK = "ring_summary_final"
# One writer per ring at a time. The lock lives while the writer runs (it is released
# when the writer finishes); LOCK_SECONDS only bounds a writer that died without releasing it.
LOCK_SECONDS = 300
ATTEMPTS = 3  # the writer itself retries, so a busy model doesn't leave the page waiting for the lock to expire
RETRY_PAUSE = 3.0
GIVE_UP_SECONDS = 60  # after ATTEMPTS failures, don't relaunch a writer for this long


def _key(stats: dict) -> str:
    return hashlib.sha256(json.dumps([TASK, stats], sort_keys=True, default=str).encode()).hexdigest()


def generate(stats: dict) -> dict | None:
    """Ask the model now and store the result. Returns the stored summary, or None if the model was unavailable."""
    result = get_provider().summarize_ring(stats)
    rejected = any("rejected" in note for note in getattr(result, "notes", ()) or ())
    if result.source == "template" and not rejected:
        return None  # model down or rate-limited: keep "pending" and try again later
    # A rejected answer is final too: the model would give the same (cached) answer again.
    data = {"text": result.text, "source": result.source}
    AICache.objects.update_or_create(key=_key(stats), defaults={"task": TASK, "model": result.source[:80], "response": data})
    return data


def _worker(stats: dict, lock_key: str) -> None:
    close_old_connections()
    done = False
    try:
        for _ in range(ATTEMPTS):
            if generate(stats) is not None:
                done = True
                break
            time.sleep(RETRY_PAUSE)
    except Exception:
        pass  # the template text is already on screen; a later page load retries
    finally:
        if done:
            cache.delete(lock_key)
        else:
            cache.set(lock_key, 1, GIVE_UP_SECONDS)
        close_old_connections()


def ring_summary(stats: dict) -> dict:
    """What the API returns for a ring: stored AI text, or template text while the AI text is being written."""
    provider = get_provider()
    if isinstance(provider, TemplateProvider):
        text = provider.summarize_ring(stats)
        return {"summary": text.text, "summary_source": text.source, "summary_pending": False}
    key = _key(stats)
    hit = AICache.objects.filter(key=key).first()
    if hit:
        return {"summary": hit.response["text"], "summary_source": hit.response["source"], "summary_pending": False}
    lock_key = f"ring-summary-lock:{key}"
    if cache.add(lock_key, 1, LOCK_SECONDS):
        threading.Thread(target=_worker, args=(stats, lock_key), daemon=True, name="ring-summary").start()
    text = TemplateProvider().summarize_ring(stats)
    return {"summary": text.text, "summary_source": text.source, "summary_pending": True}
