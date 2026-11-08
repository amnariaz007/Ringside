"""Score an order, store the assessment and findings, and write the audit trail."""

from django.db import transaction

from ai.providers import get_provider
from audit.models import record
from core.models import Order

from . import rules
from .context import order_facts, risk_context
from .models import Finding, RiskAssessment

ENGINE_VERSION = "rules-1.0"


@transaction.atomic
def score_order(order: Order) -> RiskAssessment:
    facts = order_facts(order)
    ctx = risk_context(order)
    score, level, hits = rules.evaluate(facts, ctx)

    provider = get_provider()
    explanation = provider.explain_risk(score=score, level=level, hits=hits, facts=facts)

    assessment = RiskAssessment.objects.create(
        order=order,
        score=score,
        level=level,
        explanation=explanation.text,
        explanation_source=explanation.source,
        engine_version=ENGINE_VERSION,
    )
    Finding.objects.bulk_create(
        Finding(assessment=assessment, rule=h.rule, points=h.points, reason=h.reason, evidence=h.evidence)
        for h in hits
    )
    record(
        "system", "order.scored", obj=order, paypal_id=order.paypal_order_id,
        score=score, level=level, rules=[h.rule for h in hits], engine_version=ENGINE_VERSION,
    )
    record(
        "ai", "risk.explained", obj=assessment, paypal_id=order.paypal_order_id,
        source=explanation.source, text=explanation.text,
    )
    return assessment
