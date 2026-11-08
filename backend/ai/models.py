from django.db import models


class AICache(models.Model):
    """
    Stored LLM answers keyed by a hash of (model, task, input). Re-running the
    same request (for example during the demo video) returns the stored answer
    instead of spending free-tier quota or hitting a 429.
    """

    key = models.CharField(max_length=64, unique=True)
    task = models.CharField(max_length=40)
    model = models.CharField(max_length=80)
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
