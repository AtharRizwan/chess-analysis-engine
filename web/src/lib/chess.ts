import type { Key } from "@lichess-org/chessground/types";
import { Chess, normalizeMove } from "chessops/chess";
import { chessgroundDests } from "chessops/compat";
import { makeFen, parseFen } from "chessops/fen";
import { makeSan } from "chessops/san";
import { parseSquare, parseUci } from "chessops/util";

export type Side = "white" | "black";

export function position(fen: string): Chess {
  return Chess.fromSetup(parseFen(fen).unwrap()).unwrap();
}

export function turnOf(fen: string): Side {
  return position(fen).turn;
}

export function inCheck(fen: string): boolean {
  return position(fen).isCheck();
}

/** Legal destinations in chessground's format. */
export function destsOf(fen: string): Map<Key, Key[]> {
  return chessgroundDests(position(fen)) as Map<Key, Key[]>;
}

/** Standard UCI for a drag on the board: castling as e1g1 (not king-takes-rook), pawns promote to a queen. */
export function uciFromDrag(fen: string, orig: string, dest: string): string {
  const pos = position(fen);
  const from = parseSquare(orig);
  const piece = from === undefined ? undefined : pos.board.get(from);
  if (piece?.role === "king" && orig[0] === "e" && orig[1] === dest[1]) {
    if (dest[0] === "h") return `${orig}g${dest[1]}`;
    if (dest[0] === "a") return `${orig}c${dest[1]}`;
  }
  const lastRank = dest[1] === "8" || dest[1] === "1";
  return `${orig}${dest}${piece?.role === "pawn" && lastRank ? "q" : ""}`;
}

/** Play a UCI move: the new FEN and the move's SAN. */
export function play(fen: string, uci: string): { fen: string; san: string } {
  const pos = position(fen);
  const parsed = parseUci(uci);
  if (!parsed) throw new Error(`bad move ${uci}`);
  const move = normalizeMove(pos, parsed);
  if (!pos.isLegal(move)) throw new Error(`illegal move ${uci}`);
  const san = makeSan(pos, move);
  pos.play(move);
  return { fen: makeFen(pos.toSetup()), san };
}

/** Positions along a line of UCI moves, starting with `fen` itself. */
export function positionsAlong(fen: string, uci: string[]): string[] {
  const fens = [fen];
  for (const move of uci) fens.push(play(fens[fens.length - 1], move).fen);
  return fens;
}

/** "14. Bd3 Qxb2 15. Rb1" from a start position and SAN moves. */
export function numberLine(fen: string, sans: string[]): string {
  const setup = parseFen(fen).unwrap();
  let number = setup.fullmoves;
  let white = setup.turn === "white";
  return sans
    .map((san, i) => {
      const text = white ? `${number}. ${san}` : i === 0 ? `${number}...${san}` : san;
      if (!white) number += 1;
      white = !white;
      return text;
    })
    .join(" ");
}

export function moveLabel(moveNumber: number, color: Side, san: string): string {
  return color === "white" ? `${moveNumber}. ${san}` : `${moveNumber}...${san}`;
}

/** [orig, dest] squares of a UCI move, for chessground's lastMove highlight. */
export function squaresOf(uci: string): [Key, Key] {
  return [uci.slice(0, 2) as Key, uci.slice(2, 4) as Key];
}
