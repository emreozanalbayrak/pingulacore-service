from __future__ import annotations

from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config

from app.core.config import Settings, get_settings


class ObjectStorageService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.client = boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
            region_name=self.settings.s3_region,
            config=Config(signature_version="s3v4"),
        )

    def ensure_buckets(self) -> None:
        existing = {bucket["Name"] for bucket in self.client.list_buckets().get("Buckets", [])}
        for bucket in [
            self.settings.s3_catalog_bucket,
            self.settings.s3_generated_bucket,
            self.settings.s3_rendered_bucket,
        ]:
            if bucket not in existing:
                self.client.create_bucket(Bucket=bucket)

    def upload_bytes(self, *, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

    def upload_file(self, *, bucket: str, key: str, path: Path, content_type: str) -> None:
        self.client.upload_file(
            str(path),
            bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    def get_object(self, *, bucket: str, key: str) -> tuple[bytes, str | None]:
        obj: dict[str, Any] = self.client.get_object(Bucket=bucket, Key=key)
        data = obj["Body"].read()
        return data, obj.get("ContentType")
