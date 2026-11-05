"""Central config - all values from environment."""
import os


class Settings:
    supabase_url: str = os.getenv("SUPABASE_URL", "http://192.168.1.201:8000")
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    media_root: str = os.getenv("MEDIA_ROOT", "/mnt/media")
    redis_host: str = os.getenv("REDIS_HOST", "192.168.1.203")
    media_token_secret: str = os.getenv("SUPABASE_JWT_SECRET", "")
    chunk_size: int = 1024 * 1024

    # --- billing (T-1). Absent keys mean "billing is off": the app still runs, and
    # /api/billing/* returns 503 instead of half-working.
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    stripe_price_monthly: str = os.getenv("STRIPE_PRICE_MONTHLY", "")
    stripe_price_annual: str = os.getenv("STRIPE_PRICE_ANNUAL", "")
    # where Checkout sends the browser back to; defaults to prod, dev .env overrides
    app_base_url: str = os.getenv("APP_BASE_URL", "https://app.scribly.cc")
    # days a failed payment may stay past_due before Pro is withdrawn
    billing_grace_days: int = int(os.getenv("BILLING_GRACE_DAYS", "7") or "7")
    # Stripe Tax is configured on in Checkout Studio, but the API refuses every
    # session until the account has a head-office address. Set STRIPE_AUTOMATIC_TAX=0
    # to keep selling while that is missing; see STRIPE_INTEGRATION_TODO.md.
    stripe_automatic_tax: bool = os.getenv("STRIPE_AUTOMATIC_TAX", "1") not in ("0", "false", "False", "")

    cors_origins: list = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://192.168.1.202,http://localhost:5173").split(",")
    ]


settings = Settings()
