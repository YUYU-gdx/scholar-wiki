from __future__ import annotations

import asyncio
import time
import unittest
from typing import Any

import httpx
from fastapi import FastAPI

from kn_graph.routers.literature import create_router


class _SlowDeleteLiteratureService:
    def delete_library(self, library_id: str, delete_workspace_data: bool = True) -> dict[str, Any]:
        time.sleep(0.2)
        return {"library_id": library_id, "deleted": True}


class LiteratureRouterDeleteAsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_delete_library_does_not_block_event_loop(self) -> None:
        app = FastAPI()
        app.include_router(create_router(_SlowDeleteLiteratureService()))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            started = time.perf_counter()
            task = asyncio.create_task(client.delete("/literature/libraries/lib_a"))

            await asyncio.sleep(0.03)

            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 0.12)
            response = await task

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
