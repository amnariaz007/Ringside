from django.db import models

from core.models import Order


class RiskAssessment(models.Model):
    LEVEL_CHOICES = [("low", "Low"), ("medium", "Medium"), ("high", "High")]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="assessments")
    score = models.PositiveSmallIntegerField()
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES)
    explanation = models.TextField(blank=True)
    explanation_source = models.CharField(max_length=30, blank=True)  # "template", "gemini", ...
    engine_version = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Finding(models.Model):
    assessment = models.ForeignKey(RiskAssessment, on_delete=models.CASCADE, related_name="findings")
    rule = models.CharField(max_length=40)
    points = models.PositiveSmallIntegerField()
    reason = models.CharField(max_length=300)
    evidence = models.JSONField(default=dict)

    class Meta:
        ordering = ["-points"]
