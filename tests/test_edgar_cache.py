import sys
import tempfile
import unittest
from pathlib import Path

import httpx

SOURCE_ROOT = Path(__file__).parents[1] / "src" / "alpha-daemon"
sys.path.insert(0, str(SOURCE_ROOT))

from artifact_store import ArtifactStore
from edgar import sec_get


class EdgarCacheTest(unittest.IsolatedAsyncioTestCase):
    async def test_second_request_uses_persisted_response(self) -> None:
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(
                200,
                content=b"<html>filing</html>",
                headers={"content-type": "text/html"},
                request=request,
            )

        with tempfile.TemporaryDirectory() as temp_directory:
            store_path = Path(temp_directory) / "artifacts"
            store = ArtifactStore(store_path)
            transport = httpx.MockTransport(handler)
            url = (
                "https://www.sec.gov/Archives/edgar/data/320193/"
                "000032019326000020/aapl-20260627.htm"
            )

            async with httpx.AsyncClient(transport=transport) as client:
                first = await sec_get(
                    client,
                    url,
                    "AlphaDaemon test@example.com",
                    artifact_store=store,
                )
                reopened_store = ArtifactStore(store_path)
                second = await sec_get(
                    client,
                    url,
                    "AlphaDaemon test@example.com",
                    artifact_store=reopened_store,
                )

        self.assertEqual(first.text, "<html>filing</html>")
        self.assertEqual(second.text, first.text)
        self.assertEqual(request_count, 1)


if __name__ == "__main__":
    unittest.main()
