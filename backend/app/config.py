"""Central config - all values from environment."""
import os


class Settings:
    supabase_url: str = os.getenv("SUPABASE_URL", "http://192.168.1.201:8000")
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    media_root: str = os.getenv("MEDIA_ROOT", "/mnt/media")
    redis_host: str = os.getenv("REDIS_HOST", "192.168.1.203")
    media_token_secret: str = os.getenv("SUPABASE_JWT_SECRET", "")
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_GB", "5")) * 1024 * 1024 * 1024
    chunk_size: int = 1024 * 1024
    cors_origins: list = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://192.168.1.202,http://localhost:5173").split(",")
    ]


settings = Settings()
