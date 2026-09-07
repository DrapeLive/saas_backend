import io
import logging
import os

from django.conf import settings
from django.core.files.base import File
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

logger = logging.getLogger(__name__)


@deconstructible
class SupabaseStorage(Storage):
    """
    Django storage backend backed by Supabase Storage.

    Files are stored in a dedicated bucket and served through Supabase's
    public URL. Uses the official `supabase` Python client.
    """

    def __init__(
        self,
        bucket_name=None,
        supabase_url=None,
        supabase_key=None,
    ):
        self.bucket_name = bucket_name or getattr(settings, "SUPABASE_BUCKET", None)
        self._supabase_url = supabase_url or getattr(
            settings, "SUPABASE_URL", None
        )
        self._supabase_key = supabase_key or getattr(settings, "SUPABASE_KEY", None)

        if not (self.bucket_name and self._supabase_url and self._supabase_key):
            raise ValueError(
                "SupabaseStorage requires SUPABASE_BUCKET, SUPABASE_URL and "
                "SUPABASE_KEY to be configured."
            )

        self._client = None

    @property
    def client(self):
        if self._client is None:
            from supabase import create_client

            self._client = create_client(self._supabase_url, self._supabase_key)
        return self._client

    @property
    def bucket(self):
        return self.client.storage.from_(self.bucket_name)

    def _normalize_name(self, name):
        return str(name).replace("\\", "/").lstrip("/")

    def _open(self, name, mode="rb"):
        name = self._normalize_name(name)
        data = self.bucket.download(name)
        file = io.BytesIO(data)
        file.name = name
        return File(file, name)

    def _save(self, name, content):
        name = self._normalize_name(name)
        content.seek(0)
        data = content.read()
        content_type = getattr(content, "content_type", None)
        options = {
            "content-type": content_type or self._guess_content_type(name),
            "cache-control": "public, max-age=31536000, immutable",
        }
        if hasattr(self.bucket, "upload") and self._file_exists(name):
            self.bucket.update(name, data, options)
        else:
            self.bucket.upload(name, data, options)
        return name

    def _guess_content_type(self, name):
        ext = os.path.splitext(name)[1].lower()
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".csv": "text/csv",
            ".doc": "application/msword",
            ".docx": (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        }.get(ext, "application/octet-stream")

    def _file_exists(self, name):
        try:
            return self.bucket.exists(name)
        except Exception:
            return False

    def delete(self, name):
        name = self._normalize_name(name)
        try:
            self.bucket.remove(name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete '%s' from Supabase: %s", name, exc)

    def exists(self, name):
        name = self._normalize_name(name)
        try:
            return self.bucket.exists(name)
        except Exception:
            return False

    def listdir(self, path):
        path = self._normalize_name(path)
        try:
            items = self.bucket.list(path)
        except Exception:
            return [], []
        dirs, files = [], []
        for item in items:
            name = item.get("name", "")
            if not name:
                continue
            if item.get("metadata", None) is None:
                dirs.append(name)
            else:
                files.append(name)
        return dirs, files

    def size(self, name):
        name = self._normalize_name(name)
        try:
            info = self.bucket.info(name)
            return info.get("size", 0)
        except Exception:
            return 0

    def url(self, name):
        name = self._normalize_name(name)
        return self.bucket.get_public_url(name)

    def path(self, name):
        raise NotImplementedError(
            "SupabaseStorage does not support local filesystem paths."
        )

    def get_accessed_time(self, name):
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)

    def get_created_time(self, name):
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)

    def get_modified_time(self, name):
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)
