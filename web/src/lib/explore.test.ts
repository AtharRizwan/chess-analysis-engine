import { describe, expect, it } from "vitest";
import { positionsAlong } from "./chess";
import { branchOff, explainRequest, exploreGame, moveKey, playMove, startExploring, stepTo } from "./explore";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const GAME = ["e2e4", "e7e5", "g1f3", "b8c6"];
const FENS = positionsAlong(START, GAME);

const played = (...moves: string[]) => moves.reduce(playMove, startExploring(START, [], START));

describe("exploring a line", () => {
  it("plays moves and tracks where the board is", () => {
    const line = played("d2d4", "d7d5");
    expect(line.sans).toEqual(["d4", "d5"]);
    expect(line.index).toBe(2);
    expect(line.positions).toEqual(positionsAlong(START, ["d2d4", "d7d5"]));
  });

  it("steps back and forward, stopping at both ends", () => {
    const line = played("d2d4", "d7d5");
    expect(stepTo(line, 1).index).toBe(1);
    expect(stepTo(line, -1).index).toBe(0);
    expect(stepTo(line, 9).index).toBe(2);
    expect(stepTo(line, 1).moves).toEqual(line.moves); // stepping back forgets nothing
  });

  it("keeps the rest of the line when you replay the move that's next", () => {
    const line = playMove(stepTo(played("d2d4", "d7d5", "c2c4"), 1), "d7d5");
    expect(line.index).toBe(2);
    expect(line.moves).toEqual(["d2d4", "d7d5", "c2c4"]);
  });

  it("replaces the rest of the line when you play something else", () => {
    const line = playMove(stepTo(played("d2d4", "d7d5", "c2c4"), 1), "g8f6");
    expect(line.index).toBe(2);
    expect(line.moves).toEqual(["d2d4", "g8f6"]);
    expect(line.sans).toEqual(["d4", "Nf6"]);
    expect(line.positions).toEqual(positionsAlong(START, ["d2d4", "g8f6"]));
  });

  it("tells apart different moves at the same depth, and earlier moves of one line", () => {
    const line = played("d2d4", "d7d5");
    const other = playMove(stepTo(line, 1), "g8f6");
    expect(moveKey(other)).not.toBe(moveKey(line));
    expect(moveKey(line, 1)).toBe(moveKey(other, 1));
    expect(moveKey(line, 1)).not.toBe(moveKey(line, 2));
  });

  it("asks the server about a move with the whole path behind it", () => {
    const line = playMove(playMove(exploreGame(FENS, GAME, 2), "g1f3"), "g8f6");
    expect(line.positions[0]).toBe(FENS[2]);
    expect(explainRequest(line)).toEqual({ fen: START, moves: ["e2e4", "e7e5", "g1f3"], move: "g8f6" });
    expect(explainRequest(line, 1)).toEqual({ fen: START, moves: ["e2e4", "e7e5"], move: "g1f3" });
  });

  it("gives the same key to the same path, wherever it left the game", () => {
    const early = playMove(playMove(exploreGame(FENS, GAME, 2), "g1f3"), "g8f6");
    const late = playMove(exploreGame(FENS, GAME, 3), "g8f6");
    expect(moveKey(early)).toBe(moveKey(late));
  });
});

describe("branching off a line you were shown", () => {
  it("grows out of your own line when the shown line starts on it", () => {
    const from = played("d2d4", "d7d5", "c2c4");
    const shown = { start_fen: from.positions[1], uci: ["d7d5", "c2c4", "e7e6"], san: [] };
    const line = branchOff(shown, 2, "c7c6", from, FENS, GAME);
    expect(line.moves).toEqual(["d2d4", "d7d5", "c2c4", "c7c6"]);
    expect(line.index).toBe(4);
    expect(line.rootFen).toBe(START);
    expect(line.history).toEqual([]);
  });

  it("drops the part of your line the shown line left behind", () => {
    const from = played("d2d4", "d7d5", "c2c4");
    const shown = { start_fen: from.positions[1], uci: ["g8f6", "c2c4"], san: [] };
    expect(branchOff(shown, 1, "g2g3", from, FENS, GAME).moves).toEqual(["d2d4", "g8f6", "g2g3"]);
  });

  it("grows out of the game when the shown line starts on a position of the game", () => {
    const shown = { start_fen: FENS[2], uci: ["b1c3", "g8f6"], san: [] };
    const line = branchOff(shown, 1, "b8c6", null, FENS, GAME);
    expect(line.rootFen).toBe(START);
    expect(line.history).toEqual(["e2e4", "e7e5"]);
    expect(line.moves).toEqual(["b1c3", "b8c6"]);
    expect(line.positions[0]).toBe(FENS[2]);
  });

  it("can branch right at the start of the shown line", () => {
    const shown = { start_fen: FENS[2], uci: ["b1c3"], san: [] };
    expect(branchOff(shown, 0, "f2f4", null, FENS, GAME).moves).toEqual(["f2f4"]);
  });

  it("starts from the shown line's own position when that's on neither", () => {
    const elsewhere = positionsAlong(START, ["a2a3"])[1];
    const shown = { start_fen: elsewhere, uci: ["a7a6"], san: [] };
    const line = branchOff(shown, 1, "b2b3", played("d2d4"), FENS, GAME);
    expect(line.rootFen).toBe(elsewhere);
    expect(line.history).toEqual([]);
    expect(line.moves).toEqual(["a7a6", "b2b3"]);
    expect(explainRequest(line)).toEqual({ fen: elsewhere, moves: ["a7a6"], move: "b2b3" });
  });
});
