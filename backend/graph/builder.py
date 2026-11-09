"""
Fraud-ring graph.

Buyers are joined into a cluster when they share a strong identifier: a
shipping address or a phone number. Email patterns are drawn inside a cluster
as supporting evidence but never join clusters on their own (see
risk.rules.STRONG_LINKS). A "ring" is a cluster with two or more buyers.

Output is plain dicts shaped for React Flow: nodes [{id, type, label, data}]
and edges [{id, source, target, kind}]. Layout is left to the frontend.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Prefetch

from ai.providers import get_provider
from core.models import Buyer, Order
from core.outcomes import result as dispute_result
from risk.models import RiskAssessment

# Short labels that fit a graph node. Unknown reasons fall back to the raw code.
DISPUTE_REASON_LABELS = {
    "MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "Item not received",
    "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": "Not as described",
    "UNAUTHORISED": "Unauthorised payment",
    "CREDIT_NOT_PROCESSED": "Credit not processed",
    "DUPLICATE_TRANSACTION": "Duplicate payment",
    "INCORRECT_AMOUNT": "Incorrect amount",
    "PAYMENT_BY_OTHER_MEANS": "Paid by other means",
    "CANCELED_RECURRING_BILLING": "Cancelled subscription",
    "PROBLEM_WITH_REMITTANCE": "Remittance problem",
    "OTHER": "Other",
}


class _UnionFind:
    def __init__(self):
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


@dataclass
class RingStats:
    buyers: int = 0
    orders: int = 0
    refunds: int = 0
    refunded_amount: Decimal = Decimal("0")
    disputes: int = 0
    disputes_lost: int = 0
    lost_amount: Decimal = Decimal("0")
    open_high_risk_amount: Decimal = Decimal("0")
    shared_addresses: int = 0
    shared_phones: int = 0
    shared_email_patterns: int = 0
    max_risk_score: int = 0
    newest_order_at: str = ""
    currency: str = "USD"

    def as_dict(self) -> dict:
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}


@dataclass
class Cluster:
    buyer_ids: list[int]
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    stats: RingStats = field(default_factory=RingStats)


def _orders_for(seller_id: int | None):
    qs = Order.objects.select_related("buyer", "shipping_address").prefetch_related(
        "captures__refunds",
        "disputes",
        Prefetch("assessments", queryset=RiskAssessment.objects.order_by("-created_at")),
    )
    return qs.filter(seller_id=seller_id) if seller_id else qs


def _clusters(orders: list[Order]) -> dict[int, list[int]]:
    """Union buyers that share an address or phone. Returns root -> buyer ids."""
    uf = _UnionFind()
    by_address: dict[int, set[int]] = defaultdict(set)
    by_phone: dict[str, set[int]] = defaultdict(set)
    for o in orders:
        uf.find(o.buyer_id)
        if o.shipping_address_id:
            by_address[o.shipping_address_id].add(o.buyer_id)
        if o.buyer.phone_hash:
            by_phone[o.buyer.phone_hash].add(o.buyer_id)
    for group in list(by_address.values()) + list(by_phone.values()):
        first, *rest = sorted(group)
        for other in rest:
            uf.union(first, other)
    clusters: dict[int, list[int]] = defaultdict(list)
    for bid in uf.parent:
        clusters[uf.find(bid)].append(bid)
    return clusters


def _latest(order: Order):
    items = list(order.assessments.all())
    return items[0] if items else None


def _build(buyer_ids: list[int], orders: list[Order]) -> Cluster:
    """Nodes, edges and stats for one cluster."""
    ids = set(buyer_ids)
    mine = [o for o in orders if o.buyer_id in ids]
    c = Cluster(buyer_ids=sorted(ids))
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}

    def node(nid, ntype, label, **data):
        nodes.setdefault(nid, {"id": nid, "type": ntype, "label": label, "data": data})

    def edge(src, dst, kind):
        eid = f"{src}->{dst}:{kind}"
        edges.setdefault(eid, {"id": eid, "source": src, "target": dst, "kind": kind})

    address_buyers: dict[int, set[int]] = defaultdict(set)
    phone_buyers: dict[str, set[int]] = defaultdict(set)
    stem_buyers: dict[str, set[int]] = defaultdict(set)
    buyers = {o.buyer_id: o.buyer for o in mine}
    buyer_refunds: dict[int, int] = defaultdict(int)
    buyer_disputes: dict[int, int] = defaultdict(int)
    buyer_max: dict[int, tuple[int, str]] = {}

    # Money totals use the cluster's main currency; never add GBP to USD.
    currencies = [o.currency for o in mine]
    c.stats.currency = max(set(currencies), key=currencies.count) if currencies else "USD"

    for o in mine:
        same_currency = o.currency == c.stats.currency
        a = _latest(o)
        score, level = (a.score, a.level) if a else (0, "low")
        if score >= buyer_max.get(o.buyer_id, (-1, ""))[0]:
            buyer_max[o.buyer_id] = (score, level)
        oid = f"order:{o.paypal_order_id}"
        refunds = [r for cap in o.captures.all() for r in cap.refunds.all()]
        disputes = list(o.disputes.all())
        node(oid, "order", f"{o.currency} {o.amount}", order_pk=o.pk, paypal_order_id=o.paypal_order_id,
             amount=str(o.amount), created_at=o.created_at.isoformat(), score=score, level=level,
             refunded=bool(refunds), disputed=bool(disputes))
        edge(f"buyer:{o.buyer.payer_id}", oid, "placed")
        for r in refunds:
            node(f"refund:{r.paypal_refund_id}", "refund", f"Refund {o.currency} {r.amount}", amount=str(r.amount))
            edge(oid, f"refund:{r.paypal_refund_id}", "refunded")
            c.stats.refunds += 1
            if same_currency:
                c.stats.refunded_amount += r.amount
            buyer_refunds[o.buyer_id] += 1
        for d in disputes:
            outcome = dispute_result(d.outcome)
            lost = outcome == "lost"
            node(f"dispute:{d.paypal_dispute_id}", "dispute",
                 DISPUTE_REASON_LABELS.get(d.reason, d.reason.replace("_", " ").capitalize()),
                 status=d.status, outcome=d.outcome, result=outcome, amount=str(d.amount), dispute_pk=d.pk)
            edge(oid, f"dispute:{d.paypal_dispute_id}", "disputed")
            c.stats.disputes += 1
            buyer_disputes[o.buyer_id] += 1
            if lost:
                c.stats.disputes_lost += 1
                if d.currency == c.stats.currency:
                    c.stats.lost_amount += d.amount
        refunded = sum((r.amount for r in refunds), Decimal("0"))
        if level == "high" and not disputes and refunded < o.amount and same_currency:
            c.stats.open_high_risk_amount += o.amount - refunded
        if o.shipping_address_id:
            address_buyers[o.shipping_address_id].add(o.buyer_id)
            addr = o.shipping_address
            node(f"address:{addr.pk}", "address", f"{addr.line1}, {addr.city}",
                 country=addr.country_code, is_reshipper=addr.is_reshipper)
            edge(f"buyer:{o.buyer.payer_id}", f"address:{addr.pk}", "ships_to")
        c.stats.newest_order_at = max(c.stats.newest_order_at, o.created_at.isoformat())

    for bid, b in buyers.items():
        if b.phone_hash:
            phone_buyers[b.phone_hash].add(bid)
        if b.email_stem_hash:
            stem_buyers[b.email_stem_hash].add(bid)

    # Mark which addresses are shared, so only shared ones are drawn as strong links.
    for addr_id, bids in address_buyers.items():
        shared = len(bids) > 1
        nodes[f"address:{addr_id}"]["data"]["shared"] = shared
        if shared:
            for e in edges.values():
                if e["target"] == f"address:{addr_id}":
                    e["kind"] = "ships_to_shared"

    # Phone and email-pattern nodes only when shared: a lone phone adds noise, not evidence.
    # Node ids are opaque counters, never hash prefixes (those could be brute-forced).
    shared_phones = [bids for _, bids in sorted(phone_buyers.items(), key=lambda kv: sorted(kv[1])) if len(bids) > 1]
    for i, bids in enumerate(shared_phones, 1):
        node(f"phone:{i}", "phone", f"Shared phone #{i}", shared=True)
        for bid in bids:
            edge(f"buyer:{buyers[bid].payer_id}", f"phone:{i}", "uses_phone")
    shared_stems = [bids for _, bids in sorted(stem_buyers.items(), key=lambda kv: sorted(kv[1])) if len(bids) > 1]
    for i, bids in enumerate(shared_stems, 1):
        domain = buyers[next(iter(bids))].email_domain
        node(f"email:{i}", "email_pattern", f"Email pattern @{domain}", shared=True)
        for bid in bids:
            edge(f"buyer:{buyers[bid].payer_id}", f"email:{i}", "email_pattern")

    for bid, b in buyers.items():
        score, level = buyer_max.get(bid, (0, "low"))
        node(f"buyer:{b.payer_id}", "buyer", b.display_name or b.payer_id, payer_id=b.payer_id,
             country=b.country_code, max_score=score, level=level,
             refunds=buyer_refunds[bid], disputes=buyer_disputes[bid])

    c.stats.buyers = len(buyers)
    c.stats.orders = len(mine)
    c.stats.shared_addresses = sum(1 for v in address_buyers.values() if len(v) > 1)
    c.stats.shared_phones = sum(1 for v in phone_buyers.values() if len(v) > 1)
    c.stats.shared_email_patterns = sum(1 for v in stem_buyers.values() if len(v) > 1)
    c.stats.max_risk_score = max((s for s, _ in buyer_max.values()), default=0)

    # Stable order: buyers first, then evidence, then orders and outcomes.
    rank = {"buyer": 0, "address": 1, "phone": 2, "email_pattern": 3, "order": 4, "refund": 5, "dispute": 6}
    c.nodes = sorted(nodes.values(), key=lambda n: (rank[n["type"]], n["id"]))
    c.edges = sorted(edges.values(), key=lambda e: e["id"])
    return c


def _summary(c: Cluster) -> dict:
    from ai.summaries import ring_summary
    return ring_summary(c.stats.as_dict())


def find_rings(seller_id: int | None = None) -> list[dict]:
    """All clusters with 2+ buyers, worst first."""
    orders = list(_orders_for(seller_id))
    rings = []
    for buyer_ids in _clusters(orders).values():
        if len(buyer_ids) < 2:
            continue
        c = _build(buyer_ids, orders)
        payer_ids = sorted(n["data"]["payer_id"] for n in c.nodes if n["type"] == "buyer")
        rings.append({
            "id": payer_ids[0],
            "payer_ids": payer_ids,
            "stats": c.stats.as_dict(),
            **_summary(c),
        })
    rings.sort(key=lambda r: (-r["stats"]["max_risk_score"], -r["stats"]["buyers"], r["id"]))
    return rings


def buyer_graph(payer_id: str) -> dict | None:
    """The cluster around one buyer (just the buyer's own orders if unlinked)."""
    buyer = Buyer.objects.filter(payer_id=payer_id).first()
    if buyer is None:
        return None
    seller_ids = set(Order.objects.filter(buyer=buyer).values_list("seller_id", flat=True))
    orders = list(_orders_for(next(iter(seller_ids)) if len(seller_ids) == 1 else None))
    for buyer_ids in _clusters(orders).values():
        if buyer.pk in buyer_ids:
            c = _build(buyer_ids, orders)
            return {"payer_id": payer_id, "is_ring": len(buyer_ids) > 1, "stats": c.stats.as_dict(),
                    "nodes": c.nodes, "edges": c.edges, **_summary(c)}
    return {"payer_id": payer_id, "is_ring": False, "stats": RingStats().as_dict(), "nodes": [], "edges": [],
            "summary": "This buyer has no orders yet.", "summary_source": "template", "summary_pending": False}
