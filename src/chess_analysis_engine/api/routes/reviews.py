"""Starting reviews, following their progress (server-sent events), and fetching results."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from chess_analysis_engine.api.deps import StateDep
from chess_analysis_engine.api.schemas import JobStatus, ReviewRequest
from chess_analysis_engine.models import GameReview

router = APIRouter(prefix="/api", tags=["reviews"])


@router.post("/games/{game_id}/review", response_model=JobStatus)
def start_review(game_id: int, body: ReviewRequest, state: StateDep) -> JobStatus:
    if state.db.get_game(game_id) is None:
        raise HTTPException(404, "game not found")
    if state.review_pool is None:
        raise HTTPException(503, "Stockfish is not available")
    preset = body.preset or state.settings().preset
    return state.jobs.submit(game_id, preset).snapshot()


@router.get("/games/{game_id}/review", response_model=GameReview)
def get_review(game_id: int, state: StateDep) -> Response:
    row = state.db.get_review(game_id)
    if row is None or row["status"] != "done" or not row["payload"]:
        raise HTTPException(404, "no finished review for this game")
    # The stored JSON already matches GameReview; skip re-validating a large document.
    return Response(row["payload"], media_type="application/json")


@router.get("/games/{game_id}/job", response_model=JobStatus | None)
def active_job(game_id: int, state: StateDep) -> JobStatus | None:
    job = state.jobs.active_for(game_id)
    return job.snapshot() if job else None


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str, state: StateDep) -> JobStatus:
    job = state.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job.snapshot()


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request, state: StateDep) -> StreamingResponse:
    """Progress as server-sent events, until the job finishes."""
    if state.jobs.get(job_id) is None:
        raise HTTPException(404, "job not found")

    async def stream() -> AsyncIterator[str]:
        last = None
        while not await request.is_disconnected():
            job = state.jobs.get(job_id)
            if job is None:
                return
            payload = job.snapshot().model_dump_json()
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if job.status in ("done", "error"):
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
