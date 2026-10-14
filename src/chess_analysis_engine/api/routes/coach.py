"""The optional Claude coach: narrate a move in a coach's words, checked against the verified facts."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from chess_analysis_engine.api.deps import StateDep
from chess_analysis_engine.api.schemas import CoachStatus, CoachUsage, NarrateRequest
from chess_analysis_engine.explain.coach_llm import CoachError, Narration, Usage, estimate_cost, narrate_move

router = APIRouter(prefix="/api/coach", tags=["coach"])


@router.get("/status", response_model=CoachStatus)
def status(state: StateDep) -> CoachStatus:
    settings = state.settings()
    problem = None
    try:
        state.coach()
    except CoachError as exc:
        problem = str(exc)
    usage = []
    for row in state.db.coach_usage():
        tokens = Usage(**{k: row[k] or 0 for k in Usage.model_fields})
        usage.append(
            CoachUsage(
                backend=row["backend"],
                model=row["model"],
                calls=row["calls"],
                rejected=row["rejected"] or 0,
                **tokens.model_dump(),
                # Calls through Claude Code count toward the user's Claude plan, not an API bill.
                cost_usd=estimate_cost(row["model"], tokens) if row["backend"] == "api" else None,
            )
        )
    return CoachStatus(
        enabled=settings.coach_enabled,
        ready=settings.coach_enabled and problem is None,
        backend=settings.coach_backend,
        model=settings.coach_model,
        effort=settings.coach_effort,
        problem=problem,
        usage=usage,
    )


@router.post("/narrate", response_model=Narration)
def narrate(body: NarrateRequest, state: StateDep) -> Narration:
    settings = state.settings()
    if not settings.coach_enabled:
        raise HTTPException(409, "The coach is turned off. Turn it on in Settings.")
    try:
        return narrate_move(
            body.move,
            body.user_color,
            client=state.coach(),
            model=settings.coach_model,
            effort=settings.coach_effort,
            backend=settings.coach_backend,
            db=state.db,
            refresh=body.refresh,
        )
    except CoachError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
