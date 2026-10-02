"""Background review jobs: one worker reviews games one at a time and reports progress."""

from __future__ import annotations

import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from chess_analysis_engine.api.schemas import JobStatus


@dataclass
class Job:
    game_id: int
    preset: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "queued"
    stage: str = ""
    done: int = 0
    total: int = 0
    error: str | None = None

    def progress(self, stage: str, done: int, total: int) -> None:
        self.stage, self.done, self.total = stage, done, total

    def snapshot(self) -> JobStatus:
        return JobStatus(
            id=self.id,
            game_id=self.game_id,
            preset=self.preset,
            status=self.status,  # type: ignore[arg-type]
            stage=self.stage,
            done=self.done,
            total=self.total,
            error=self.error,
        )


class JobManager:
    """A FIFO queue with a single worker thread: reviews use every engine, so one at a time."""

    def __init__(self, run: Callable[[Job], None]):
        self._run = run
        self._jobs: dict[str, Job] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._loop, name="review-worker", daemon=True)
        self._worker.start()

    def submit(self, game_id: int, preset: str) -> Job:
        with self._lock:
            active = self.active_for(game_id)
            if active is not None:
                return active
            job = Job(game_id=game_id, preset=preset)
            self._jobs[job.id] = job
        self._queue.put(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def active_for(self, game_id: int) -> Job | None:
        for job in self._jobs.values():
            if job.game_id == game_id and job.status in ("queued", "running"):
                return job
        return None

    def _loop(self) -> None:
        while True:
            job = self._jobs[self._queue.get()]
            job.status = "running"
            try:
                self._run(job)
                job.status = "done"
            except Exception as exc:  # the job records the failure; the worker keeps going
                job.status = "error"
                job.error = str(exc) or exc.__class__.__name__
