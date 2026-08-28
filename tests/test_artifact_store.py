import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src" / "alpha-daemon"
sys.path.insert(0, str(SOURCE_ROOT))

from artifact_store import ArtifactStore


class ArtifactStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.store_path = Path(self.temp_directory.name) / "artifacts"

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_artifact_persists_across_store_instances(self) -> None:
        retrieved_at = datetime(2026, 8, 28, tzinfo=timezone.utc)
        first_store = ArtifactStore(self.store_path)
        written = first_store.put(
            source="sec_edgar_http",
            source_id="request-1",
            content=b"immutable filing",
            media_type="text/html",
            retrieved_at=retrieved_at,
            metadata={"url": "https://example.test/filing"},
        )

        second_store = ArtifactStore(self.store_path)
        loaded = second_store.get(
            "sec_edgar_http",
            "request-1",
            now=retrieved_at + timedelta(days=30),
        )

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.content, b"immutable filing")
        self.assertEqual(loaded.content_hash, written.content_hash)
        self.assertTrue(loaded.payload_path.exists())
        self.assertEqual(loaded.metadata["url"], "https://example.test/filing")

    def test_expired_artifact_is_a_cache_miss(self) -> None:
        retrieved_at = datetime(2026, 8, 28, tzinfo=timezone.utc)
        store = ArtifactStore(self.store_path)
        store.put(
            source="sec_edgar_http",
            source_id="request-2",
            content=b"mutable index",
            retrieved_at=retrieved_at,
            expires_at=retrieved_at + timedelta(minutes=30),
        )

        loaded = store.get(
            "sec_edgar_http",
            "request-2",
            now=retrieved_at + timedelta(minutes=31),
        )

        self.assertIsNone(loaded)

    def test_versions_remain_addressable_by_artifact_id(self) -> None:
        first_retrieval = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)
        store = ArtifactStore(self.store_path)
        first = store.put(
            source="fred_http",
            source_id="series-request",
            content=b"first vintage",
            retrieved_at=first_retrieval,
            expires_at=first_retrieval + timedelta(hours=1),
        )
        second = store.put(
            source="fred_http",
            source_id="series-request",
            content=b"revised vintage",
            retrieved_at=first_retrieval + timedelta(hours=2),
            expires_at=first_retrieval + timedelta(hours=3),
        )

        before_revision = store.get(
            "fred_http",
            "series-request",
            now=first_retrieval + timedelta(minutes=30),
        )
        latest = store.get(
            "fred_http",
            "series-request",
            now=first_retrieval + timedelta(hours=2, minutes=30),
        )

        self.assertEqual(before_revision, first)
        self.assertEqual(latest, second)
        self.assertEqual(store.get_by_id(first.artifact_id), first)

    def test_request_fingerprint_normalizes_query_parameter_order(self) -> None:
        first = ArtifactStore.request_fingerprint(
            "get",
            "https://EXAMPLE.test/data?b=2&a=1",
        )
        second = ArtifactStore.request_fingerprint(
            "GET",
            "https://example.test/data?a=1&b=2",
        )

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
