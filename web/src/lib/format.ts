import type { Classification, MoveReview, Side } from "../api/client";

export const LABELS: Record<Classification, string> = {
  brilliant: "Brilliant",
  great: "Great move",
  best: "Best",
  excellent: "Excellent",
  good: "Good",
  book: "Book",
  forced: "Forced",
  inaccuracy: "Inaccuracy",
  mistake: "Mistake",
  miss: "Miss",
  blunder: "Blunder",
};

export const SYMBOLS: Partial<Record<Classification, string>> = {
  brilliant: "!!",
  great: "!",
  inaccuracy: "?!",
  mistake: "?",
  miss: "?",
  blunder: "??",
};

export const BAD = new Set<Classification>(["inaccuracy", "mistake", "miss", "blunder"]);
export const SERIOUS = new Set<Classification>(["mistake", "miss", "blunder"]);

/** Winning chances for `side` in %, from White's percentage. */
export function chancesFor(whiteWin: number, side: Side): number {
  return side === "white" ? whiteWin : 100 - whiteWin;
}

export function pct(value: number): string {
  return `${Math.round(value)}%`;
}

export function evalText(score: MoveReview["eval_after"]): string {
  if (score.result) return score.result === "1/2-1/2" ? "½" : score.result;
  if (score.mate !== null && score.mate !== undefined) return `M${Math.abs(score.mate)}`;
  const cp = (score.cp ?? 0) / 100;
  return `${cp > 0 ? "+" : ""}${cp.toFixed(1)}`;
}

export const FACT_LABELS: Record<string, string> = {
  allows_mate: "Allows mate",
  missed_mate: "Missed mate",
  ignored_threat: "Ignored threat",
  hangs_piece: "Hanging piece",
  allows_tactic: "Allows a tactic",
  allows_attack: "Double attack",
  loses_material: "Loses material",
  missed_tactic: "Missed tactic",
  missed_material: "Missed free material",
  missed_win: "Missed win",
  tablebase: "Endgame",
  stalemate: "Stalemate",
  repetition: "Repetition",
  allows_repetition: "Allows repetition",
  positional: "Positional",
  opening_principle: "Opening principle",
  clock: "Clock",
  executes_tactic: "Tactic",
  forces_mate: "Forced mate",
  checkmate: "Checkmate",
  sacrifice: "Sacrifice",
  only_move: "Only move",
  parries_threat: "Stops a threat",
};

export const MOTIF_LABELS: Record<string, string> = {
  fork: "Fork",
  pin: "Pin",
  skewer: "Skewer",
  discovered_attack: "Discovered attack",
  discovered_check: "Discovered check",
  double_check: "Double check",
  removal_of_defender: "Removing the defender",
  trapped_piece: "Trapped piece",
  promotion: "Promotion",
  back_rank_mate: "Back-rank mate",
  smothered_mate: "Smothered mate",
  king_safety: "King safety",
  isolated_pawn: "Isolated pawn",
  doubled_pawns: "Doubled pawns",
  passed_pawn_allowed: "Passed pawn",
  bishop_pair: "Bishop pair",
  development: "Development",
  rushed: "Played too fast",
  time_trouble: "Time trouble",
  passed_pawn_missed: "Missed passed pawn",
  castling_lost: "Lost castling rights",
  activity: "Passive pieces",
  outpost_allowed: "Outpost for the opponent",
  outpost_missed: "Missed outpost",
  open_file: "Open file",
  early_queen: "Early queen move",
  same_piece_twice: "Same piece twice",
  king_walk: "King walk",
  weakening_pawn_move: "Weakening pawn move",
};

export function playedAt(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** Moves that count as finding the answer when retrying a mistake. */
export const SOLVED = new Set<Classification>(["best", "excellent", "great", "brilliant", "book", "forced"]);

const CAUSE_TEXT: Record<string, string> = {
  allows_mate: "Walked into a mate",
  missed_mate: "Missed a mate",
  ignored_threat: "Ignored the opponent's threat",
  allows_attack: "Allowed a double attack",
  loses_material: "Lost material in a sequence",
  missed_material: "Missed free material",
  missed_win: "Missed a winning sequence",
  tablebase: "Endgame technique",
  stalemate: "Stalemated a won position",
  allows_repetition: "Let a won game be drawn by repetition",
  repetition: "Repeated a won position into a draw",
  accuracy: "No single clear reason",
};
const HANG_TEXT: Record<string, string> = {
  moved_into_attack: "Moved a piece where it could be taken",
  removed_defender: "Moved a piece that was guarding another",
  left_unprotected: "Left a piece unprotected",
};

/** "Allowed a fork", "Missed a pin", "Moved a piece where it could be taken"… */
export function causeLabel(cause: string, motif?: string | null): string {
  const named = motif ? MOTIF_LABELS[motif]?.toLowerCase() : undefined;
  if (cause === "allows_tactic") return named ? `Allowed a ${named}` : "Allowed a tactic";
  if (cause === "missed_tactic") return named ? `Missed a ${named}` : "Missed a tactic";
  if (cause === "hangs_piece") return HANG_TEXT[motif ?? ""] ?? "Left a piece hanging";
  if (cause === "positional") return named ? `Positional: ${named}` : "Positional concession";
  if (cause === "opening_principle") return "Broke an opening principle";
  if (cause === "allows_mate" && named) return `Walked into a ${named}`;
  return CAUSE_TEXT[cause] ?? cause;
}

/** A drill theme (a cause like "ignored_threat" or a motif like "fork") in words. */
export function themeLabel(theme: string): string {
  return MOTIF_LABELS[theme] ?? FACT_LABELS[theme] ?? causeLabel(theme);
}
