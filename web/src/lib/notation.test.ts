import { describe, expect, it } from "vitest";
import { positionsAlong } from "./chess";
import { buildIndex, linkify, type MoveRef } from "./notation";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const GAME = ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6"]; // 1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6??
const fens = positionsAlong(START, GAME);
const BEFORE = fens[5]; // Black to play move 3
const AFTER = fens[6];

const game = { start_fen: START, uci: GAME, san: [] };
const mate = { start_fen: AFTER, uci: ["h5f7"], san: ["Qxf7#"] };
const best = { start_fen: BEFORE, uci: ["g7g6", "h5f3", "g8f6"], san: [] };
const index = buildIndex({ lines: [mate, best], game, anchors: [BEFORE, AFTER] });

const moves = (text: string) => linkify(text, index).filter((s): s is MoveRef => typeof s !== "string");

describe("linkify", () => {
  it("ties numbered moves of both sides to their positions", () => {
    const [nf6, qxf7] = moves("After 3...Nf6 4. Qxf7# is mate.");
    expect([nf6.fen, nf6.uci, nf6.label, nf6.game]).toEqual([BEFORE, "g8f6", "3...Nf6", true]);
    expect([qxf7.fen, qxf7.uci, qxf7.label, qxf7.game]).toEqual([AFTER, "h5f7", "4. Qxf7#", false]);
  });

  it("follows a sequence of unnumbered moves along its line", () => {
    const refs = moves("Better was 3...g6 4. Qf3 Nf6.");
    expect(refs.map((r) => [r.uci, r.index])).toEqual([
      ["g7g6", 0],
      ["h5f3", 1],
      ["g8f6", 2],
    ]);
    expect(refs[2].fen).not.toBe(BEFORE); // this Nf6 comes after 4. Qf3, not the game's 3...Nf6
  });

  it("links a lone piece move to the position at hand", () => {
    const [ref] = moves("Qxf7# would end the game.");
    expect([ref.fen, ref.uci]).toEqual([AFTER, "h5f7"]);
  });

  it("keeps squares, impossible moves and the wrong side as plain text", () => {
    expect(moves("The f7 square is weak.")).toEqual([]);
    expect(moves("4. Qxe8 is impossible.")).toEqual([]);
    expect(moves("4...Qxf7 is White's move, not Black's.")).toEqual([]);
  });

  it("links earlier moves of the game itself", () => {
    const [ref] = moves("Their move 3. Qh5 attacked f7.");
    expect([ref.game, ref.index, ref.uci]).toEqual([true, 4, "d1h5"]);
  });

  it("keeps the rest of the text intact", () => {
    const text = "It allows 4. Qxf7#, a mate on f7.";
    const joined = linkify(text, index)
      .map((s) => (typeof s === "string" ? s : s.text))
      .join("");
    expect(joined).toBe(text);
  });
});
