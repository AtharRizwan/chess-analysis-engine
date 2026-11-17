import type { LineRef } from "../api/client";
import { play } from "./chess";

/**
 * A line of your own, tried out on the board. It's one line, not a tree: playing something else from an
 * earlier move replaces what came after it.
 */
export type Exploration = {
  /** Where the server replays from: the game's start when possible, so repetitions with the game count. */
  rootFen: string;
  /** The moves from rootFen to the line's first position. */
  history: string[];
  /** positions[0] is the line's first position; positions[i + 1] follows moves[i]. */
  positions: string[];
  moves: string[];
  sans: string[];
  /** Where the board is: 0 is the line's first position, moves.length its end. */
  index: number;
};

export function startExploring(rootFen: string, history: string[], startFen: string): Exploration {
  return { rootFen, history, positions: [startFen], moves: [], sans: [], index: 0 };
}

/** A line starting from a position of the game (`fens[ply]`, where `fens[0]` is the game's start). */
export function exploreGame(fens: string[], gameUci: string[], ply: number): Exploration {
  return startExploring(fens[0], gameUci.slice(0, ply), fens[ply]);
}

/** Play a move where the board is: the move that's already next steps forward and keeps the rest. */
export function playMove(line: Exploration, uci: string): Exploration {
  if (line.moves[line.index] === uci) return { ...line, index: line.index + 1 };
  const { fen, san } = play(line.positions[line.index], uci);
  return {
    ...line,
    positions: [...line.positions.slice(0, line.index + 1), fen],
    moves: [...line.moves.slice(0, line.index), uci],
    sans: [...line.sans.slice(0, line.index), san],
    index: line.index + 1,
  };
}

export function stepTo(line: Exploration, index: number): Exploration {
  return { ...line, index: Math.max(0, Math.min(line.moves.length, index)) };
}

/**
 * Your line after following a line you were shown for `followed` moves and then playing `uci`. It grows
 * out of the line you opened it from if it starts on that line, else out of the game if it starts on a
 * position of the game, else (a threat line, say) from its own start.
 */
export function branchOff(
  shown: LineRef,
  followed: number,
  uci: string,
  from: Exploration | null,
  fens: string[],
  gameUci: string[],
): Exploration {
  const onYourLine = from ? from.positions.indexOf(shown.start_fen) : -1;
  const gamePly = fens.indexOf(shown.start_fen);
  const base =
    from && onYourLine >= 0
      ? stepTo(from, onYourLine)
      : gamePly >= 0
        ? exploreGame(fens, gameUci, gamePly)
        : startExploring(shown.start_fen, [], shown.start_fen);
  return [...shown.uci.slice(0, followed), uci].reduce(playMove, base);
}

/** Identifies the move leading to position `index` by its whole path: its answers depend on nothing else. */
export function moveKey(line: Exploration, index = line.index): string {
  return [line.rootFen, ...line.history, ...line.moves.slice(0, index)].join(" ");
}

/** What the server needs to explain the move leading to position `index` (from 1). */
export function explainRequest(line: Exploration, index = line.index): { fen: string; moves: string[]; move: string } {
  return {
    fen: line.rootFen,
    moves: [...line.history, ...line.moves.slice(0, index - 1)],
    move: line.moves[index - 1],
  };
}
