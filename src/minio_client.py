"""MinIO client helpers for Bronze layer uploads."""

import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def get_minio_client() -> Minio:
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

    return Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )


def get_bucket_name() -> str:
    return os.getenv("MINIO_BUCKET", "bronze")


def ensure_bucket(client: Minio | None = None, bucket_name: str | None = None) -> str:
    client = client or get_minio_client()
    bucket_name = bucket_name or get_bucket_name()

    if not client.bucket_exists(bucket_name):
        client.make_bucket(bucket_name)
        print(f"Bucket '{bucket_name}' criado.")

    return bucket_name


def upload_file(
    local_path: Path,
    object_name: str,
    client: Minio | None = None,
    bucket_name: str | None = None,
) -> None:
    client = client or get_minio_client()
    bucket_name = bucket_name or ensure_bucket(client)

    try:
        content_type, _ = mimetypes.guess_type(str(local_path))
        content_type = content_type or "application/octet-stream"
        client.fput_object(
            bucket_name,
            object_name,
            str(local_path),
            content_type=content_type,
        )
    except S3Error as error:
        raise RuntimeError(f"Falha ao enviar {local_path} para {bucket_name}/{object_name}: {error}") from error
