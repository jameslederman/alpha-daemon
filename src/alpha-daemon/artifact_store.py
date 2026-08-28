from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class ArtifactIntegrityError(RuntimeError):
    """Raised when persisted artifact bytes no longer match their content hash."""


@dataclass(frozen=True)
class StoredArtifact:
    artifact_id: str
    source: str
    source_id: str
    content: bytes
    content_hash: str
    payload_path: Path
    media_type: str | None
    retrieved_at: datetime
    data_time: datetime | None
    expires_at: datetime | None
    parser_version: str | None
    metadata: dict[str, Any]


class ArtifactStore:
    """Persistent content-addressed cache for raw and derived research artifacts."""

    def __init__(self, root_path: str | Path) -> None:
        self.root_path = Path(root_path)
        self.database_path = self.root_path / "metadata.sqlite3"
        self.blob_root = self.root_path / "blobs"
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @staticmethod
    def request_fingerprint(
        method: str,
        url: str,
        params: Mapping[str, Any] | None = None,
    ) -> str:
        """Return a stable identifier for a semantically equivalent HTTP request."""

        parsed = urlsplit(url)
        query_items = parse_qsl(parsed.query, keep_blank_values=True)

        if params:
            for key, value in params.items():
                values = value if isinstance(value, (list, tuple)) else [value]
                query_items.extend((str(key), str(item)) for item in values)

        canonical_url = urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path,
                urlencode(sorted(query_items)),
                "",
            )
        )
        canonical_request = f"{method.strip().upper()}\n{canonical_url}"
        return hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()

    def get(
        self,
        source: str,
        source_id: str,
        *,
        now: datetime | None = None,
    ) -> StoredArtifact | None:
        resolved_now = _utc_datetime(now or datetime.now(timezone.utc))

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT artifact_id, source, source_id, payload_path,
                       content_hash, media_type, retrieved_at, data_time,
                       expires_at, parser_version, metadata_json
                FROM artifacts
                WHERE source = ? AND source_id = ?
                  AND retrieved_at <= ?
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY retrieved_at DESC
                LIMIT 1
                """,
                (
                    source,
                    source_id,
                    resolved_now.isoformat(),
                    resolved_now.isoformat(),
                ),
            ).fetchone()

        if row is None:
            return None

        return self._stored_artifact(row, f"{source}:{source_id}")

    def get_by_id(self, artifact_id: str) -> StoredArtifact | None:
        """Load an exact artifact version, including an expired one."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT artifact_id, source, source_id, payload_path,
                       content_hash, media_type, retrieved_at, data_time,
                       expires_at, parser_version, metadata_json
                FROM artifacts
                WHERE artifact_id = ?
                """,
                (artifact_id,),
            ).fetchone()

        if row is None:
            return None

        return self._stored_artifact(row, artifact_id)

    def _stored_artifact(
        self, row: sqlite3.Row | tuple, identity: str
    ) -> StoredArtifact:
        payload_path = self.root_path / row[3]
        try:
            content = payload_path.read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactIntegrityError(
                f"Artifact payload is missing for {identity}"
            ) from exc

        content_hash = hashlib.sha256(content).hexdigest()
        if content_hash != row[4]:
            raise ArtifactIntegrityError(f"Artifact hash mismatch for {identity}")

        return StoredArtifact(
            artifact_id=row[0],
            source=row[1],
            source_id=row[2],
            content=content,
            content_hash=row[4],
            payload_path=payload_path,
            media_type=row[5],
            retrieved_at=_required_datetime(row[6], "retrieved_at"),
            data_time=_parse_datetime(row[7]),
            expires_at=_parse_datetime(row[8]),
            parser_version=row[9],
            metadata=json.loads(row[10]),
        )

    def put(
        self,
        *,
        source: str,
        source_id: str,
        content: bytes,
        media_type: str | None = None,
        retrieved_at: datetime | None = None,
        data_time: datetime | None = None,
        expires_at: datetime | None = None,
        parser_version: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> StoredArtifact:
        resolved_retrieved_at = _utc_datetime(
            retrieved_at or datetime.now(timezone.utc)
        )
        resolved_data_time = _utc_datetime(data_time) if data_time else None
        resolved_expires_at = _utc_datetime(expires_at) if expires_at else None
        content_hash = hashlib.sha256(content).hexdigest()
        artifact_id = _artifact_id(
            source,
            source_id,
            content_hash,
            resolved_retrieved_at,
        )
        payload_path = self._persist_blob(content, content_hash)
        relative_payload_path = payload_path.relative_to(self.root_path)
        metadata_json = json.dumps(
            metadata or {}, sort_keys=True, separators=(",", ":")
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO artifacts (
                    artifact_id, source, source_id, payload_path, content_hash,
                    media_type, retrieved_at, data_time, expires_at,
                    parser_version, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    payload_path = excluded.payload_path,
                    expires_at = excluded.expires_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    artifact_id,
                    source,
                    source_id,
                    str(relative_payload_path),
                    content_hash,
                    media_type,
                    resolved_retrieved_at.isoformat(),
                    resolved_data_time.isoformat() if resolved_data_time else None,
                    resolved_expires_at.isoformat() if resolved_expires_at else None,
                    parser_version,
                    metadata_json,
                ),
            )

        artifact = self.get_by_id(artifact_id)
        if artifact is None:
            raise RuntimeError(
                "Artifact was not readable immediately after persistence"
            )
        return artifact

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    payload_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    media_type TEXT,
                    retrieved_at TEXT NOT NULL,
                    data_time TEXT,
                    expires_at TEXT,
                    parser_version TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_artifacts_expires_at
                ON artifacts(expires_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_artifacts_lookup
                ON artifacts(source, source_id, retrieved_at DESC)
                """
            )

    def _persist_blob(self, content: bytes, content_hash: str) -> Path:
        blob_path = self.blob_root / content_hash[:2] / content_hash
        if blob_path.exists():
            return blob_path

        blob_path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_path = tempfile.mkstemp(dir=blob_path.parent)
        try:
            with os.fdopen(file_descriptor, "wb") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, blob_path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

        return blob_path


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("artifact timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _artifact_id(
    source: str,
    source_id: str,
    content_hash: str,
    retrieved_at: datetime,
) -> str:
    identity = json.dumps(
        [source, source_id, content_hash, retrieved_at.isoformat()],
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return _utc_datetime(datetime.fromisoformat(value))


def _required_datetime(value: str | None, field_name: str) -> datetime:
    parsed = _parse_datetime(value)
    if parsed is None:
        raise ArtifactIntegrityError(f"Required artifact {field_name} is missing")
    return parsed
