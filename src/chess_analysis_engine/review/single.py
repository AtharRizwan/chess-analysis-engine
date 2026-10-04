"""Review one move from any position: the "why not this move?" explorer."""

from __future__ import annotations

import chess

from chess_analysis_engine.config import Preset
from chess_analysis_engine.engine.pool import EnginePool, Request
from chess_analysis_engine.engine.scoring import ep_for, missed_mate
from chess_analysis_engine.explain.templates import build_explanation
from chess_analysis_engine.facts.extract import MoveInput, explain_move
from chess_analysis_engine.models import Color, MoveReview, color_name
from chess_analysis_engine.review.classify import MoveContext
from chess_analysis_engine.review.openings import load_book
from chess_analysis_engine.review.pipeline import make_move_review, static_facts
from chess_analysis_engine.storage.db import Database


def is_book(board_after: chess.Board) -> bool:
    """Every position from the standard start up to `board_after` is in the opening book."""
    root = board_after.root()
    if root.epd() != chess.Board().epd():
        return False
    book = load_book()
    replay = root.copy()
    for move in board_after.move_stack:
        replay.push(move)
        if not book.is_book(replay):
            return False
    return True


def review_move(
    board: chess.Board,
    move: chess.Move,
    engines: EnginePool,
    preset: Preset,
    user_color: Color | None = None,
    db: Database | None = None,
    threats: bool = True,
    tablebase: bool = True,
) -> MoveReview:
    """Classify and explain `move` in `board` (which may carry game history)."""
    if not board.is_legal(move):
        raise ValueError(f"{move.uci()} is not legal in this position")
    after = board.copy()
    after.push(move)
    before_eval, after_eval = engines.analyse_many(
        [
            Request(board, preset.depth, preset.multipv, preset.max_seconds),
            Request(after, preset.depth, 2, preset.max_seconds),
        ]
    )
    color = color_name(board.turn)
    static = static_facts(board, move)
    second = before_eval.lines[1] if len(before_eval.lines) > 1 else None
    book = is_book(after)
    ctx = MoveContext(
        played_uci=move.uci(),
        best_uci=before_eval.best.uci[0] if before_eval.best else None,
        ep_before=ep_for(before_eval.score, color),
        ep_after=ep_for(after_eval.score, color),
        second_best_ep=ep_for(second.score, color) if second else None,
        legal_moves=static.legal_moves,
        book=book,
        sacrifice=static.sacrifice,
        is_recapture=static.is_recapture,
        takes_material=static.takes_material,
        rescues_piece=static.rescues_piece,
        in_check=static.in_check,
        delivers_mate=static.delivers_mate,
        missed_mate=missed_mate(color, before_eval.score, after_eval.score),
    )
    review = make_move_review(
        board, move, before_eval, after_eval, ctx, ply=len(board.move_stack) + 1, book=book
    )
    result = explain_move(
        MoveInput(
            board=board,
            move=move,
            before=before_eval,
            after=after_eval,
            classification=review.classification,
            ep_loss=review.ep_loss,
            phase=review.phase,
            opening=load_book().name_of(after) if book else None,
        ),
        engines,
        db,
        use_threats=threats,
        use_tablebase=tablebase,
    )
    review.facts = result.facts
    review.difficulty = result.difficulty
    review.explanation = build_explanation(review, result.facts, user_color)
    return review
