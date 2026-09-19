"""Scriber API - FastAPI entrypoint."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import health, search, segments, transcripts, videos
from app.routers import videos_delete, videos_ops, videos_thumb, shares
from app.routers.videos_list import router as videos_list_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Scriber API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(videos.router, prefix="/api/videos", tags=["videos"])
app.include_router(videos_thumb.router, prefix="/api/videos", tags=["videos"])
app.include_router(videos_delete.router, prefix="/api/videos", tags=["videos"])
app.include_router(videos_list_router, prefix="/api/videos", tags=["videos"])
app.include_router(videos_ops.router, prefix="/api/videos", tags=["videos"])
app.include_router(shares.router, prefix="/api/videos", tags=["shares"])
app.include_router(transcripts.router, prefix="/api/videos", tags=["transcripts"])
app.include_router(segments.router, prefix="/api/segments", tags=["segments"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(health.router, prefix="/api", tags=["health"])
