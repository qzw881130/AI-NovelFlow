"""Small in-process async workers for serial background queues."""
import asyncio
from typing import Awaitable, Callable, Dict, Optional


JobFactory = Callable[[], Awaitable[None]]


class AsyncWorker:
    """FIFO worker that runs one async job at a time."""

    def __init__(self, name: str):
        self.name = name
        self._queue: asyncio.Queue[JobFactory] = asyncio.Queue()
        self._runner: Optional[asyncio.Task] = None

    def enqueue(self, job_factory: JobFactory) -> None:
        self._ensure_started()
        self._queue.put_nowait(job_factory)

    def _ensure_started(self) -> None:
        if self._runner and not self._runner.done():
            return
        self._runner = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            job_factory = await self._queue.get()
            try:
                await job_factory()
            except Exception as exc:
                print(f"[Worker:{self.name}] job failed: {exc}")
            finally:
                self._queue.task_done()


class WorkerManager:
    def __init__(self):
        self._workers: Dict[str, AsyncWorker] = {}

    def worker(self, name: str) -> AsyncWorker:
        if name not in self._workers:
            self._workers[name] = AsyncWorker(name)
        return self._workers[name]


worker_manager = WorkerManager()
