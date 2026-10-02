"""End-to-end game review: engine pass → classification → deeper look at critical moves."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import chess

from chess_analysis_engine.config import Preset
from chess_analysis_engine.engine.pool import EnginePool, Request
from chess_analysis_engine.engine.scoring import (
    ep_for,
    game_accuracy,
    move_accuracy,
    mover_win_percents,
    white_win_percent,
)
from chess_analysis_engine.explain.templates import build_explanation
from chess_analysis_engine.facts.board import is_recapture, sacrificed_material
from chess_analysis_engine.facts.extract import MoveFacts, MoveInput, explain_move
from chess_analysis_engine.models import (
    CLASSIFICATIONS,
    ClockInfo,
    Color,
    GameReview,
    MoveReview,
    PlayerInfo,
    PositionEval,
    SideSummary,
    color_name,
)
from chess_analysis_engine.pgn import GameRecord
from chess_analysis_engine.review.classify import (
    BRILLIANT_MIN_SACRIFICE,
    GOOD,
    MoveContext,
    classify,
)
from chess_analysis_engine.review.moments import game_phase, key_moments
from chess_analysis_engine.review.openings import identify, load_book
from chess_analysis_engine.storage.db import Database, utcnow

ProgressFn = Callable[[str, int, int], None]

# A best move whose runner-up is this much worse might be an only-move: double-check it.
GREAT_CANDIDATE_GAP = 0.07


@dataclass
class ReviewOptions:
    preset: Preset
    user_color: Color | None = None
    deepen_critical: bool = True
    explain: bool = True  # build facts and explanations (the "why")
    threats: bool = True  # null-move threat searches (extra engine time)
    tablebase: bool = True  # online endgame tablebase lookups


@dataclass(frozen=True)
class _Static:
    """Per-move facts that don't depend on the engine."""

    legal_moves: int
    sacrifice: int
    is_recapture: bool
    in_check: bool
    delivers_mate: bool


def static_facts(board: chess.Board, move: chess.Move) -> _Static:
    return _Static(
        legal_moves=board.legal_moves.count(),
        sacrifice=sacrificed_material(board, move),
        is_recapture=is_recapture(board, move),
        in_check=board.is_check(),
        delivers_mate=_delivers_mate(board, move),
    )


def _delivers_mate(board: chess.Board, move: chess.Move) -> bool:
    board.push(move)
    try:
        return board.is_checkmate()
    finally:
        board.pop()


def _needs_deeper_look(ctx: MoveContext) -> bool:
    if ctx.legal_moves == 1 or ctx.book:
        return False
    if ctx.loss > GOOD:
        return True
    if ctx.sacrifice >= BRILLIANT_MIN_SACRIFICE:
        return True
    gap = None if ctx.second_best_ep is None else ctx.ep_before - ctx.second_best_ep
    return ctx.is_best and gap is not None and gap >= GREAT_CANDIDATE_GAP


class _Game:
    """Everything the classification pass needs, computed once."""

    def __init__(self, game: GameRecord):
        self.game = game
        self.boards = game.boards()
        self.n = len(game.moves)
        self.colors: list[Color] = [color_name(self.boards[i].turn) for i in range(self.n)]
        self.statics = [static_facts(self.boards[i], game.moves[i]) for i in range(self.n)]
        self.spent = game.time_spent()
        self.standard_start = self.boards[0].epd() == chess.Board().epd()
        self.book_flags, self.opening, self.left_book_ply = identify(self.boards[1:], self.standard_start)

    def contexts(self, evals: list[PositionEval]) -> list[MoveContext]:
        """Classification inputs for every move. Sequential because "Miss" depends on how
        costly the opponent's previous move was."""
        result: list[MoveContext] = []
        for i in range(self.n):
            color = self.colors[i]
            before, after = evals[i], evals[i + 1]
            second = before.lines[1] if len(before.lines) > 1 else None
            prev = result[-1] if result else None
            static = self.statics[i]
            result.append(
                MoveContext(
                    played_uci=self.game.moves[i].uci(),
                    best_uci=before.best.uci[0] if before.best else None,
                    ep_before=ep_for(before.score, color),
                    ep_after=ep_for(after.score, color),
                    second_best_ep=ep_for(second.score, color) if second else None,
                    legal_moves=static.legal_moves,
                    book=self.book_flags[i],
                    sacrifice=static.sacrifice,
                    is_recapture=static.is_recapture,
                    in_check=static.in_check,
                    delivers_mate=static.delivers_mate,
                    opponent_prev_loss=None if prev is None or prev.is_best else prev.loss,
                    ep_before_opponent_error=None if prev is None else 1.0 - prev.ep_before,
                )
            )
        return result

    def build(self, i: int, ctx: MoveContext, evals: list[PositionEval], critical: bool) -> MoveReview:
        remaining = self.game.clocks[i] if i < len(self.game.clocks) else None
        clock = ClockInfo(remaining=remaining, spent=self.spent[i]) if remaining is not None else None
        return make_move_review(
            self.boards[i],
            self.game.moves[i],
            evals[i],
            evals[i + 1],
            ctx,
            ply=i + 1,
            book=self.book_flags[i],
            clock=clock,
            critical=critical,
        )


def make_move_review(
    board: chess.Board,
    move: chess.Move,
    before: PositionEval,
    after: PositionEval,
    ctx: MoveContext,
    *,
    ply: int,
    book: bool = False,
    clock: ClockInfo | None = None,
    critical: bool = False,
) -> MoveReview:
    """Scores and classification for one move, given the evaluations around it."""
    color = color_name(board.turn)
    win_before = white_win_percent(before.score)
    win_after = white_win_percent(after.score)
    best = ctx.is_best
    accuracy = 100.0 if best else move_accuracy(*mover_win_percents(win_before, win_after, color))
    position_after = board.copy(stack=False)
    position_after.push(move)
    return MoveReview(
        ply=ply,
        move_number=board.fullmove_number,
        color=color,
        san=board.san(move),
        uci=move.uci(),
        fen_before=board.fen(),
        fen_after=position_after.fen(),
        eval_before=before.score,
        eval_after=after.score,
        win_before=round(win_before, 2),
        win_after=round(win_after, 2),
        ep_before=round(ctx.ep_before, 4),
        ep_after=round(ctx.ep_after, 4),
        ep_loss=0.0 if best else round(ctx.loss, 4),
        accuracy=round(accuracy, 1),
        classification=classify(ctx),
        best=before.best,
        refutation=after.best,
        alternatives=before.lines,
        phase=game_phase(board),
        book=book,
        clock=clock,
        critical=critical,
        sacrifice=ctx.sacrifice,
    )


def _explain(
    g: _Game,
    evals: list[PositionEval],
    moves: list[MoveReview],
    engines: EnginePool,
    options: ReviewOptions,
    db: Database | None,
    report: ProgressFn,
) -> None:
    """Facts, difficulty and the written explanation for every move (in parallel)."""
    base = g.game.time_control[0] if g.game.time_control else None
    book_names = {i: m.opening for i, m in enumerate(moves)}

    def work(i: int) -> MoveFacts:
        m = moves[i]
        opening = book_names.get(i) or (moves[i - 1].opening if i else None)
        inp = MoveInput(
            board=g.boards[i],
            move=g.game.moves[i],
            before=evals[i],
            after=evals[i + 1],
            classification=m.classification,
            ep_loss=m.ep_loss,
            clock=m.clock,
            base_seconds=base,
            phase=m.phase,
            opening=opening,
        )
        return explain_move(inp, engines, db, use_threats=options.threats, use_tablebase=options.tablebase)

    with ThreadPoolExecutor(engines.size) as workers:
        for done, (i, result) in enumerate(
            zip(range(len(moves)), workers.map(work, range(len(moves))), strict=True), start=1
        ):
            m = moves[i]
            m.facts = result.facts
            m.difficulty = result.difficulty
            m.explanation = build_explanation(m, result.facts, options.user_color)
            report("facts", done, len(moves))


def review_game(
    game: GameRecord,
    engines: EnginePool,
    options: ReviewOptions,
    progress: ProgressFn | None = None,
    db: Database | None = None,
) -> GameReview:
    report = progress or (lambda stage, done, total: None)
    preset = options.preset
    g = _Game(game)
    n = g.n

    # Last position first, so each engine's hash carries late tactics back to earlier positions.
    order = list(range(n, -1, -1))
    requests = [Request(g.boards[i], preset.depth, preset.multipv, preset.max_seconds) for i in order]
    results = engines.analyse_many(requests, on_done=lambda done, total: report("engine", done, total))
    evals = list(reversed(results))

    # Re-check critical moves with a deeper search. Every position keeps its deepest eval.
    critical: set[int] = set()
    if options.deepen_critical and n:
        critical = {i for i, ctx in enumerate(g.contexts(evals)) if _needs_deeper_look(ctx)}
        wanted: dict[int, int] = {}
        for i in critical:
            wanted[i] = max(wanted.get(i, 0), preset.critical_multipv)
            wanted[i + 1] = max(wanted.get(i + 1, 0), 2)
        positions = sorted(wanted, reverse=True)
        deep_requests = [
            Request(g.boards[pos], preset.critical_depth, wanted[pos], preset.critical_max_seconds)
            for pos in positions
        ]
        deep_results = engines.analyse_many(
            deep_requests, on_done=lambda done, total: report("critical", done, total)
        )
        for pos, result in zip(positions, deep_results, strict=True):
            evals[pos] = result

    moves = [g.build(i, ctx, evals, critical=i in critical) for i, ctx in enumerate(g.contexts(evals))]
    if g.standard_start:
        book = load_book()
        for i, m in enumerate(moves):
            m.opening = book.name_of(g.boards[i + 1])
    if options.explain and n:
        _explain(g, evals, moves, engines, options, db, report)

    accuracy = game_accuracy([white_win_percent(e.score) for e in evals], color_name(g.boards[0].turn))
    summary = {
        side: SideSummary(
            accuracy=None if accuracy[side] is None else round(accuracy[side], 1),
            counts=dict(
                sorted(
                    Counter(m.classification for m in moves if m.color == side).items(),
                    key=lambda kv: CLASSIFICATIONS.index(kv[0]),
                )
            ),
        )
        for side in ("white", "black")
    }

    return GameReview(
        headers=game.headers,
        white=PlayerInfo(name=game.white, rating=game.rating("white")),
        black=PlayerInfo(name=game.black, rating=game.rating("black")),
        result=game.result,
        start_fen=game.start_fen,
        user_color=options.user_color,
        opening=g.opening,
        left_book_ply=g.left_book_ply,
        preset=preset.name,
        depth=preset.depth,
        engine=engines.name,
        moves=moves,
        final_eval=evals[-1].score,
        summary=summary,
        key_moments=key_moments(moves, options.user_color),
        created_at=utcnow(),
    )
