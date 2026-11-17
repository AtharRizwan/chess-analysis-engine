"""The optional Claude coach: narrate a move in a coach's words, and answer follow-up questions about it,
checked against the verified facts."""

from __future__ import annotations

import chess
from fastapi import APIRouter, HTTPException

from chess_analysis_engine.api.deps import StateDep
from chess_analysis_engine.api.schemas import (
    ChatRequest,
    ChatThreadRequest,
    ChatView,
    CoachStatus,
    CoachUsage,
    NarrateRequest,
    Settings,
)
from chess_analysis_engine.api.state import AppState
from chess_analysis_engine.config import PRESETS
from chess_analysis_engine.explain.coach_chat import MAX_TURNS, ChatThread, LookupFn, ask, thread_key
from chess_analysis_engine.explain.coach_llm import CoachError, Narration, Usage, estimate_cost, narrate_move
from chess_analysis_engine.models import Color, MoveReview
from chess_analysis_engine.review.single import review_move
from chess_analysis_engine.storage.db import Database

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


def _enabled(state: AppState) -> Settings:
    settings = state.settings()
    if not settings.coach_enabled:
        raise HTTPException(409, "The coach is turned off. Turn it on in Settings.")
    return settings


@router.post("/narrate", response_model=Narration)
def narrate(body: NarrateRequest, state: StateDep) -> Narration:
    settings = _enabled(state)
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


# --- follow-up questions ------------------------------------------------------------------------


def _thread(db: Database, key: str) -> ChatThread:
    saved = db.chat_get(key)
    return ChatThread.model_validate_json(saved) if saved else ChatThread()


def _lookup(state: AppState, settings: Settings, user_color: Color | None) -> LookupFn | None:
    """Stockfish's review of another move, the same one "Try a different move here" gives."""
    pool = state.interactive_pool
    if pool is None:
        return None  # no engine: Claude answers from the review's own lines

    def check(board: chess.Board, move: chess.Move) -> MoveReview:
        return review_move(
            board,
            move,
            pool,
            PRESETS[settings.preset],
            user_color=user_color,
            db=state.db,
            threats=settings.threats,
            tablebase=settings.tablebase,
        )

    return check


@router.post("/chat", response_model=ChatView)
def chat(body: ChatRequest, state: StateDep) -> ChatView:
    """Ask a question about a move; returns the move's whole conversation with the answer added."""
    settings = _enabled(state)
    key = thread_key(body.move.fen_before, body.move.uci, body.user_color)
    thread = _thread(state.db, key)
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "Write a question first.")
    last = thread.turns[-1] if thread.turns else None
    retrying = last is not None and not last.verified and last.question == question
    if len(thread.turns) >= MAX_TURNS and not retrying:
        raise HTTPException(
            409, f"That's {MAX_TURNS} questions about this move: clear the conversation to start again."
        )
    try:
        ask(
            body.move,
            body.user_color,
            question,
            thread,
            client=state.coach(),
            model=settings.coach_model,
            effort=settings.coach_effort,
            backend=settings.coach_backend,
            lookup=_lookup(state, settings, body.user_color),
            db=state.db,
            shown=body.shown,
        )
    except CoachError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    state.db.chat_put(key, thread.model_dump_json())
    return ChatView(turns=thread.turns)


@router.post("/chat/thread", response_model=ChatView)
def chat_thread(body: ChatThreadRequest, state: StateDep) -> ChatView:
    """A move's conversation so far (empty when there's none)."""
    return ChatView(turns=_thread(state.db, thread_key(body.fen_before, body.uci, body.user_color)).turns)


@router.post("/chat/clear", response_model=ChatView)
def chat_clear(body: ChatThreadRequest, state: StateDep) -> ChatView:
    state.db.chat_delete(thread_key(body.fen_before, body.uci, body.user_color))
    return ChatView()
