"""Stripe integration: checkout, webhook handling, subscription gating.

  - create_checkout_session(brokerage, plan)  -> Checkout URL
  - handle_webhook_event(payload, sig_header, db) -> updates brokerage status
  - check_subscription_active(db, brokerage_id) -> bool

When DEMO_MODE is on (or no Stripe key), checkout returns a local stub URL and
subscription state is read straight from the brokerage.status column so the gate
can still be exercised end-to-end.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from config import ACTIVE_SUB_STATUSES, PLANS, settings
from models import Brokerage

logger = logging.getLogger("brokerage.stripe")


def _stripe():
    import stripe

    stripe.api_key = settings.stripe_secret_key
    return stripe


# ---------------------------------------------------------------------------
#  Customer + Checkout
# ---------------------------------------------------------------------------
def ensure_customer(db: Session, brokerage: Brokerage) -> str:
    """Return a Stripe customer id, creating one if needed."""
    if brokerage.stripe_customer_id:
        return brokerage.stripe_customer_id

    if settings.demo_mode or not settings.stripe_secret_key:
        cust_id = f"cus_demo_{brokerage.id[:8]}"
    else:
        customer = _stripe().Customer.create(
            email=brokerage.email,
            name=brokerage.name,
            metadata={"brokerage_id": brokerage.id},
        )
        cust_id = customer.id

    brokerage.stripe_customer_id = cust_id
    db.commit()
    return cust_id


def create_checkout_session(db: Session, brokerage: Brokerage, plan: str) -> str:
    """Create a subscription Checkout session and return its URL."""
    if plan not in PLANS:
        raise ValueError(f"Unknown plan: {plan}")

    customer_id = ensure_customer(db, brokerage)

    if settings.demo_mode or not settings.stripe_secret_key:
        # Offline: immediately mark active so the rest of the flow is testable.
        brokerage.plan = plan
        brokerage.status = "active"
        brokerage.doc_limit = PLANS[plan]["monthly_docs"]
        db.commit()
        return f"{settings.app_base_url}?checkout=demo_success&plan={plan}"

    price_id = settings.price_id_for_plan(plan)
    session = _stripe().checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{settings.app_base_url}?checkout=success",
        cancel_url=f"{settings.app_base_url}?checkout=cancel",
        metadata={"brokerage_id": brokerage.id, "plan": plan},
        subscription_data={"metadata": {"brokerage_id": brokerage.id, "plan": plan}},
    )
    return session.url


# ---------------------------------------------------------------------------
#  Webhook
# ---------------------------------------------------------------------------
def handle_webhook_event(payload: bytes, sig_header: str, db: Session) -> dict:
    """Verify + process a Stripe webhook. Returns a small status dict."""
    if settings.demo_mode or not settings.stripe_webhook_secret:
        import json

        event = json.loads(payload.decode() or "{}")
    else:
        event = _stripe().Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )

    etype = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    logger.info("Stripe webhook: %s", etype)

    if etype in (
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
    ):
        _sync_subscription(db, obj)
    elif etype == "customer.subscription.deleted":
        _set_status_by_customer(db, obj.get("customer"), "canceled")
    elif etype == "invoice.payment_failed":
        _set_status_by_customer(db, obj.get("customer"), "past_due")

    return {"received": True, "type": etype}


def _sync_subscription(db: Session, obj: dict) -> None:
    customer_id = obj.get("customer")
    brokerage = (
        db.query(Brokerage)
        .filter(Brokerage.stripe_customer_id == customer_id)
        .first()
    )
    # fall back to metadata for checkout.session.completed
    if not brokerage:
        bid = (obj.get("metadata") or {}).get("brokerage_id")
        if bid:
            brokerage = db.query(Brokerage).filter(Brokerage.id == bid).first()
    if not brokerage:
        logger.warning("Webhook for unknown customer %s", customer_id)
        return

    sub_id = obj.get("subscription") or obj.get("id")
    status = obj.get("status", "active")
    # checkout.session has no 'status'; treat completed as active
    if obj.get("object") == "checkout.session":
        status = "active"

    brokerage.stripe_customer_id = customer_id or brokerage.stripe_customer_id
    brokerage.stripe_subscription_id = sub_id or brokerage.stripe_subscription_id
    brokerage.status = status

    # derive plan from price id if present, and keep the quota limit in sync
    items = (obj.get("items") or {}).get("data") or []
    if items:
        price_id = items[0].get("price", {}).get("id")
        plan = settings.plan_for_price_id(price_id)
        if plan:
            brokerage.plan = plan
    # plan metadata fallback (checkout.session / subscription metadata)
    meta_plan = (obj.get("metadata") or {}).get("plan")
    if meta_plan in PLANS:
        brokerage.plan = meta_plan
    if brokerage.plan in PLANS:
        brokerage.doc_limit = PLANS[brokerage.plan]["monthly_docs"]
    db.commit()


def _set_status_by_customer(db: Session, customer_id: str | None, status: str) -> None:
    if not customer_id:
        return
    brokerage = (
        db.query(Brokerage)
        .filter(Brokerage.stripe_customer_id == customer_id)
        .first()
    )
    if brokerage:
        brokerage.status = status
        db.commit()


# ---------------------------------------------------------------------------
#  Gate
# ---------------------------------------------------------------------------
def check_subscription_active(db: Session, brokerage_id: str) -> bool:
    """True if the brokerage's subscription is currently active/trialing."""
    brokerage = db.query(Brokerage).filter(Brokerage.id == brokerage_id).first()
    if not brokerage:
        return False

    # In live mode, optionally re-verify against Stripe for freshness.
    if (
        not settings.demo_mode
        and settings.stripe_secret_key
        and brokerage.stripe_subscription_id
    ):
        try:
            sub = _stripe().Subscription.retrieve(brokerage.stripe_subscription_id)
            brokerage.status = sub["status"]
            db.commit()
        except Exception as exc:  # noqa: BLE001 — fall back to stored status
            logger.warning("Stripe re-check failed: %s", exc)

    return brokerage.status in ACTIVE_SUB_STATUSES
