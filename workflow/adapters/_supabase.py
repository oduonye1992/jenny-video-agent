"""Shared Supabase upload helper for adapters that need public URLs for images/videos."""

import os
from datetime import datetime

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

IMAGE_BUCKET = "first_frame_images"
VIDEO_BUCKET = "first_frame_images"  # Same bucket — supports both images and videos

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_SECRET_KEY"),
        )
    return _client


def upload_to_supabase(bucket: str, local_path: str, remote_name: str) -> str:
    """Upload a file to Supabase storage and return its public URL."""
    client = _get_client()

    with open(local_path, "rb") as f:
        file_bytes = f.read()

    ext = os.path.splitext(local_path)[1].lower()
    content_types = {
        ".mp4": "video/mp4",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    content_type = content_types.get(ext, "application/octet-stream")

    client.storage.from_(bucket).upload(
        remote_name,
        file_bytes,
        file_options={"content-type": content_type, "upsert": "true"},
    )

    return client.storage.from_(bucket).get_public_url(remote_name)


def upload_frame(local_path: str, label: str = "frame") -> str:
    """Upload an image frame to the default image bucket with a timestamped name."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    ext = os.path.splitext(local_path)[1] or ".png"
    remote_name = f"{ts}-{label}{ext}"
    return upload_to_supabase(IMAGE_BUCKET, local_path, remote_name)
