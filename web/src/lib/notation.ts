import { makeSquare } from "chessops/util";
import type { LineRef, MoveReview } from "../api/client";
import { play, position, uciFromDrag } from "./chess";

/** A move mentioned in a text, tied to the exact position it's played in. */
export type MoveRef = {
  kind: "move";
  text: string; // as written, e.g. "9. Nxf7+"
  label: string; // "9. Nxf7+" / "9...Nxf7" (always numbered)
  fen: string; // the position before the move
  uci: string;
  line: LineRef; // the line it belongs to (with SAN), from line.start_fen
  index: number; // the move's index in that line
  game: boolean; // a move of the game itself (not a variation)
  key: string;
};
export type Segment = string | MoveRef;

export type NotationContext = {
  lines: (LineRef | null | undefined)[]; // most relevant first
  game?: LineRef | null; // the game so far: mentions of earlier game moves link to it
  anchors?: string[]; // positions whose legal moves may be mentioned on their own ("Nxf7 doesn't work")
};

type Entry = {
  norm: string;
  number: number;
  white: boolean;
  fen: string;
  uci: string;
  line: LineRef;
  index: number;
  game: boolean;
  anchor: boolean;
};

export type NotationIndex = { bySan: Map<string, Entry[]> };

const norm = (san: string) => san.replace(/[+#!?]+$/, "").replace(/0/g, "O");

function walk(line: LineRef, game: boolean, out: Entry[], anchors: Set<string>): void {
  let fen = line.start_fen;
  const uci: string[] = [];
  const san: string[] = [];
  const entries: Entry[] = [];
  for (const move of line.uci) {
    let next: { fen: string; san: string };
    try {
      next = play(fen, move);
    } catch {
      break; // a line that stops being legal ends there
    }
    const [, turn, , , , full] = fen.split(" ");
    entries.push({
      norm: norm(next.san),
      number: Number(full) || 1,
      white: turn === "w",
      fen,
      uci: move,
      line: line, // replaced below by the checked copy
      index: uci.length,
      game,
      anchor: anchors.has(fen),
    });
    uci.push(move);
    san.push(next.san);
    fen = next.fen;
  }
  const checked: LineRef = { start_fen: line.start_fen, uci, san }; // SAN as computed, for the line player
  for (const entry of entries) out.push({ ...entry, line: checked });
}

function legalMoves(fen: string): LineRef[] {
  let pos;
  try {
    pos = position(fen);
  } catch {
    return [];
  }
  const lines: LineRef[] = [];
  for (const [from, dests] of pos.allDests()) {
    for (const to of dests) {
      const uci = uciFromDrag(fen, makeSquare(from), makeSquare(to));
      try {
        lines.push({ start_fen: fen, uci: [uci], san: [play(fen, uci).san] });
      } catch {
        // chessops lists castling as king-takes-rook; uciFromDrag normalizes it, anything else is skipped
      }
    }
  }
  return lines;
}

/** Everything the moves in a text may refer to, most relevant first. */
export function buildIndex(context: NotationContext): NotationIndex {
  const anchors = new Set(context.anchors ?? []);
  const entries: Entry[] = [];
  for (const line of context.lines) if (line && line.uci.length) walk(line, false, entries, anchors);
  if (context.game && context.game.uci.length) walk(context.game, true, entries, anchors);
  for (const fen of anchors) for (const line of legalMoves(fen)) walk(line, false, entries, anchors);
  const bySan = new Map<string, Entry[]>();
  for (const entry of entries) {
    const list = bySan.get(entry.norm) ?? [];
    list.push(entry);
    bySan.set(entry.norm, list);
  }
  return { bySan };
}

/** The lines a move's explanation can mention: its own lines first, then the game itself. */
export function contextFor(move: MoveReview, game?: LineRef | null): NotationContext {
  const lines: (LineRef | null | undefined)[] = [];
  for (const section of move.explanation?.sections ?? []) lines.push(section.line);
  const refutation = move.refutation?.uci ?? [];
  lines.push({ start_fen: move.fen_before, uci: [move.uci, ...refutation], san: [] });
  if (move.best) lines.push({ start_fen: move.fen_before, uci: move.best.uci, san: move.best.san });
  for (const alt of move.alternatives ?? []) lines.push({ start_fen: move.fen_before, uci: alt.uci, san: alt.san });
  for (const fact of move.facts ?? []) {
    lines.push(fact.line);
    const threat = (fact.data as Record<string, unknown> | undefined)?.threat_line as LineRef | undefined;
    if (threat?.start_fen && Array.isArray(threat.uci)) lines.push(threat);
  }
  return { lines, game, anchors: [move.fen_before, move.fen_after] };
}

const SAN_RE =
  /(?<![A-Za-z0-9])(?:(\d+)\s*(\.\s*\.\.|\.…|…|\.)\s*|(\.\.\.|…)\s*)?(O-O-O|O-O|0-0-0|0-0|[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?|[a-h]x[a-h][1-8](?:=[QRBN])?|[a-h][1-8](?:=[QRBN])?)[+#]?[!?]*(?![A-Za-z0-9])/g;

const labelOf = (e: Entry, san: string) => (e.white ? `${e.number}. ${san}` : `${e.number}...${san}`);

/** Split a text into plain strings and the moves it mentions (only those that can be placed on a board). */
export function linkify(text: string, index: NotationIndex): Segment[] {
  const segments: Segment[] = [];
  let cursor = 0;
  let previous = null as { entry: Entry; end: number } | null;
  for (const match of text.matchAll(SAN_RE)) {
    const [whole, number, sep, dots, san] = match;
    const start = match.index ?? 0;
    const side: boolean | null = number ? sep === "." : dots ? false : null; // true = White
    const prev: { entry: Entry; end: number } | null = previous;
    const continuing: boolean = prev !== null && /^\s*$/.test(text.slice(prev.end, start));
    const candidates: Entry[] = index.bySan.get(norm(san)) ?? [];
    const next: Entry | undefined =
      continuing && prev ? candidates.find((e) => e.line === prev.entry.line && e.index === prev.entry.index + 1) : undefined;
    let entry: Entry | undefined;
    if (number) {
      const numbered = candidates.filter((e) => e.number === Number(number) && e.white === side);
      entry = numbered.find((e) => e === next) ?? numbered[0];
    } else if (next && (side === null || next.white === side)) {
      entry = next;
    } else if (!/^[a-h][1-8]$/.test(san)) {
      // a lone piece move or capture: a legal move of the position at hand first
      const sided = candidates.filter((e) => side === null || e.white === side);
      entry = sided.find((e) => e.anchor) ?? sided[0];
    }
    if (!entry) {
      previous = null;
      continue;
    }
    if (start > cursor) segments.push(text.slice(cursor, start));
    const shown = entry.line.san[entry.index] ?? san;
    segments.push({
      kind: "move",
      text: whole,
      label: labelOf(entry, shown),
      fen: entry.fen,
      uci: entry.uci,
      line: entry.line,
      index: entry.index,
      game: entry.game,
      key: `${entry.fen}|${entry.uci}`,
    });
    cursor = start + whole.length;
    previous = { entry, end: cursor };
  }
  if (cursor < text.length) segments.push(text.slice(cursor));
  return segments;
}
