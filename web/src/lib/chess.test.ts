import { describe, expect, it } from "vitest";
import { destsOf, gamePliesAlong, numberLine, play, positionsAlong, turnOf, uciFromDrag } from "./chess";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const CASTLE = "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1";

describe("chess helpers", () => {
  it("lists legal destinations", () => {
    expect(destsOf(START).get("e2")).toEqual(["e3", "e4"]);
    expect(destsOf(START).get("g1")?.sort()).toEqual(["f3", "h3"]);
  });

  it("plays moves and reports SAN", () => {
    const { fen, san } = play(START, "g1f3");
    expect(san).toBe("Nf3");
    expect(turnOf(fen)).toBe("black");
  });

  it("normalises castling drags to standard UCI", () => {
    expect(uciFromDrag(CASTLE, "e1", "h1")).toBe("e1g1");
    expect(uciFromDrag(CASTLE, "e1", "a1")).toBe("e1c1");
    expect(uciFromDrag(CASTLE, "e1", "g1")).toBe("e1g1");
    expect(play(CASTLE, "e1g1").san).toBe("O-O");
  });

  it("promotes to a queen by default", () => {
    expect(uciFromDrag("8/P7/8/8/8/8/8/k6K w - - 0 1", "a7", "a8")).toBe("a7a8q");
  });

  it("numbers lines from either side", () => {
    expect(numberLine(START, ["e4", "e5", "Nf3"])).toBe("1. e4 e5 2. Nf3");
    const afterE4 = play(START, "e2e4").fen;
    expect(numberLine(afterE4, ["e5", "Nf3"])).toBe("1...e5 2. Nf3");
  });

  it("walks positions along a line", () => {
    expect(positionsAlong(START, ["e2e4", "e7e5"])).toHaveLength(3);
  });

  it("finds where a line follows the game", () => {
    const game = ["e2e4", "e7e5", "g1f3", "b8c6"];
    const fens = positionsAlong(START, game);
    // From the start: follows 1. e4, then leaves the game with 1...c5.
    expect(gamePliesAlong(START, ["e2e4", "c7c5", "g1f3"], fens, game)).toEqual([0, 1]);
    // From the middle of the game, following it to the end.
    expect(gamePliesAlong(fens[2], ["g1f3", "b8c6"], fens, game)).toEqual([2, 3, 4]);
    // From a position that never happened in the game.
    expect(gamePliesAlong(play(START, "d2d4").fen, ["d7d5"], fens, game)).toEqual([]);
  });
});
