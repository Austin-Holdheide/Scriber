"""Worker-side config (203/204/205)."""
import os


class WorkerSettings:
    redis_host: str = os.getenv("REDIS_HOST", "192.168.1.203")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    queue_name: str = os.getenv("RQ_QUEUE", "transcribe")

    supabase_url: str = os.getenv("SUPABASE_URL", "http://192.168.1.201:8000")
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")

    media_root: str = os.getenv("MEDIA_ROOT", "/mnt/media")

    # ASR
    model_size: str = os.getenv("WHISPER_MODEL", "small")
    device: str = os.getenv("WHISPER_DEVICE", "cuda")       # cuda on 204/205, cpu on 203
    compute_type: str = os.getenv("COMPUTE_TYPE", "int8")   # INT8 always on Pascal
    cpu_threads: int = int(os.getenv("CPU_THREADS", "14"))  # 203 only

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"


wsettings = WorkerSettings()
