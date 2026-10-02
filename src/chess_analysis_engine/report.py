"""Render a GameReview as a Markdown report (used by the CLI)."""

from __future__ import annotations

from chess_analysis_engine.explain.phrases import (
    CLASSIFICATION_LABELS,
    CLASSIFICATION_SYMBOLS,
    move_label,
    mover_win,
    numbered_line,
    percent,
)
from chess_analysis_engine.models import CLASSIFICATIONS, GameReview, MoveReview

MAX_LINE_PLIES = 8


def _player(review: GameReview, color: str) -> str:
    player = review.white if color == "white" else review.black
    rating = f" ({player.rating})" if player.rating else ""
    you = " — you" if review.user_color == color else ""
    return f"{player.name}{rating}{you}"


def _move_heading(m: MoveReview) -> str:
    symbol = CLASSIFICATION_SYMBOLS.get(m.classification, "")
    before = mover_win(m.win_before, m.color)
    after = mover_win(m.win_after, m.color)
    return (
        f"{move_label(m.move_number, m.color, m.san)}{symbol} — {CLASSIFICATION_LABELS[m.classification]} "
        f"({m.color}'s winning chances {percent(before)} → {percent(after)})"
    )


def _moment(m: MoveReview) -> list[str]:
    lines = [f"### {_move_heading(m)}", ""]
    if m.explanation is not None:
        for section in m.explanation.sections:
            lines.append(f"**{section.title}:** {section.text}")
            lines.append("")
        if m.explanation.lesson:
            lines += [f"**Lesson:** {m.explanation.lesson}", ""]
        return lines
    if m.best and m.best.uci and m.best.uci[0] != m.uci:
        lines.append(
            f"- Best was **{move_label(m.move_number, m.color, m.best.san[0])}**: "
            f"{numbered_line(m.fen_before, m.best.san, MAX_LINE_PLIES)}"
        )
    if m.refutation and m.refutation.san:
        lines.append(f"- After {m.san}: {numbered_line(m.fen_after, m.refutation.san, MAX_LINE_PLIES)}")
    lines.append("")
    return lines


def render_markdown(review: GameReview) -> str:
    h = review.headers
    out = [f"# {_player(review, 'white')} vs {_player(review, 'black')} — {review.result}", ""]
    meta = [x for x in (h.get("Event"), h.get("Date"), h.get("TimeControl")) if x and x != "?"]
    if review.opening:
        meta.append(f"{review.opening.eco} {review.opening.name}")
    if review.left_book_ply:
        m = review.moves[review.left_book_ply - 1]
        meta.append(f"left theory with {move_label(m.move_number, m.color, m.san)}")
    if meta:
        out += [" · ".join(meta), ""]
    out += [f"_{review.engine}, {review.preset} preset (depth {review.depth})_", ""]

    out += ["| | White | Black |", "|---|---|---|"]
    w, b = review.summary.get("white"), review.summary.get("black")
    out.append(f"| Accuracy | {w.accuracy if w else '–'} | {b.accuracy if b else '–'} |")
    for label in CLASSIFICATIONS:
        wc = w.counts.get(label, 0) if w else 0
        bc = b.counts.get(label, 0) if b else 0
        if wc or bc:
            out.append(f"| {CLASSIFICATION_LABELS[label]} | {wc} | {bc} |")
    out.append("")

    moments = [m for m in review.moves if m.ply in set(review.key_moments)]
    if moments:
        out += ["## Key moments", ""]
        for m in moments:
            out += _moment(m)

    out += ["## All moves", "", "| # | White | | Black | |", "|---|---|---|---|---|"]
    row: dict[str, str] = {}
    for m in review.moves:
        cell = f"{m.san}{CLASSIFICATION_SYMBOLS.get(m.classification, '')}"
        tag = CLASSIFICATION_LABELS[m.classification]
        if m.color == "white":
            row = {"n": str(m.move_number), "w": cell, "wt": tag, "b": "", "bt": ""}
        else:
            if not row:
                row = {"n": str(m.move_number), "w": "…", "wt": "", "b": "", "bt": ""}
            row.update(b=cell, bt=tag)
            out.append(f"| {row['n']} | {row['w']} | {row['wt']} | {row['b']} | {row['bt']} |")
            row = {}
    if row:
        out.append(f"| {row['n']} | {row['w']} | {row['wt']} | | |")
    out.append("")
    return "\n".join(out)
