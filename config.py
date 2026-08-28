"""Central configuration loaded from environment (.env).

Every module imports `settings` from here so there is a single source of
truth for credentials, plan definitions and limits.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


# ---- Plan catalogue -------------------------------------------------------
# Monthly price (CAD) and included document quota. "unlimited" => None.
PLANS = {
    "starter": {"price_cad": 79, "monthly_docs": 100, "label": "Starter"},
    "pro": {"price_cad": 199, "monthly_docs": 500, "label": "Professional"},
    "enterprise": {"price_cad": 499, "monthly_docs": None, "label": "Agency"},
}

# Statuses that allow document processing.
ACTIVE_SUB_STATUSES = {"active", "trialing"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Database
    database_url: str = "sqlite:///./brokerage.db"

    # Supabase storage
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_storage_bucket: str = "documents"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_pro: str = ""
    stripe_price_enterprise: str = ""

    # App
    api_base_url: str = "http://localhost:8000"
    app_base_url: str = "http://localhost:8501"
    webhook_shared_secret: str = "change-me"

    # n8n approval webhook: backend POSTs here AFTER a broker approval so n8n
    # FLOW 2 can send the final client email. Empty -> notification disabled
    # (approval still succeeds; non-breaking).
    n8n_approval_webhook_url: str = ""

    # Approval JWT (signed token embedded in draft email -> /approve/{token})
    jwt_secret: str = "change-me-to-a-long-random-jwt-secret"
    # Security hardening (both enforced only when set -> demo/tests unaffected)
    admin_api_key: str = ""          # if set, /admin/* requires x-admin-key header
    cors_origins: str = "*"          # comma-separated allowed origins in prod
    max_upload_mb: int = 10          # reject PDFs larger than this
    rate_limit_per_min: int = 0      # per-IP request cap on POST endpoints; 0 = disabled
    jwt_algorithm: str = "HS256"
    approval_token_ttl_hours: int = 168  # 7 days

    # Billing links surfaced by the 429 / 403 gates (n8n renders these)
    stripe_upgrade_url: str = "https://app.brokerage-ai.ca/billing/upgrade"
    stripe_billing_portal_url: str = "https://billing.stripe.com/p/login/portal"

    # CASL / legal
    company_legal_name: str = "Brokerage AI Inc."
    company_mailing_address: str = (
        "1000 Rue de la Gauchetiere O, Montreal, QC H3B 4W5, Canada"
    )
    company_unsubscribe_url: str = "https://app.brokerage-ai.ca/unsubscribe"

    demo_mode: bool = False

    # ---- helpers ----
    def price_id_for_plan(self, plan: str) -> str:
        return {
            "starter": self.stripe_price_starter,
            "pro": self.stripe_price_pro,
            "enterprise": self.stripe_price_enterprise,
        }.get(plan, "")

    def plan_for_price_id(self, price_id: str) -> str | None:
        mapping = {
            self.stripe_price_starter: "starter",
            self.stripe_price_pro: "pro",
            self.stripe_price_enterprise: "enterprise",
        }
        return mapping.get(price_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
