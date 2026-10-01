from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def register_background_task(app: FastAPI, work: Coroutine[Any, Any, None], name: str) -> None:
    task = asyncio.create_task(work, name=name)
    tasks: set[asyncio.Task[None]] = app.state.background_tasks
    tasks.add(task)

    def finished(done: asyncio.Task[None]) -> None:
        tasks.discard(done)
        if not done.cancelled():
            try:
                done.result()
            except Exception:
                logger.exception("Background task %s failed", name)

    task.add_done_callback(finished)
