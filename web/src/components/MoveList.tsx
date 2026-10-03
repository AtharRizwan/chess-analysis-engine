import { useEffect, useRef } from "react";
import type { MoveReview } from "../api/client";
import { SYMBOLS } from "../lib/format";

type Props = { moves: MoveReview[]; ply: number; onSelect: (ply: number) => void };
type Row = { number: number; white?: MoveReview; black?: MoveReview };

function rows(moves: MoveReview[]): Row[] {
  const result: Row[] = [];
  for (const move of moves) {
    const last = result[result.length - 1];
    if (move.color === "white" || !last || last.black || last.number !== move.move_number) {
      result.push({ number: move.move_number, [move.color]: move });
    } else {
      last.black = move;
    }
  }
  return result;
}

/** The game as a table of moves; each move carries its classification. */
export function MoveList({ moves, ply, onSelect }: Props) {
  const list = useRef<HTMLDivElement>(null);
  const current = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Scroll the list itself (not the page, which scrollIntoView would also do) to keep the move in view.
    const box = list.current;
    const row = current.current;
    if (!box || !row) return;
    const top = row.offsetTop; // .movelist is position: relative
    const bottom = top + row.offsetHeight;
    if (top < box.scrollTop) box.scrollTop = top;
    else if (bottom > box.scrollTop + box.clientHeight) box.scrollTop = bottom - box.clientHeight;
  }, [ply]);

  const cell = (move: MoveReview | undefined) => {
    if (!move) return <div className="mv" aria-hidden />;
    const active = move.ply === ply;
    return (
      <div
        ref={active ? current : undefined}
        className={`mv${active ? " current" : ""}`}
        onClick={() => onSelect(move.ply)}
        role="button"
        tabIndex={-1}
        title={move.classification}
      >
        <span className={`cls-dot cls-${move.classification}`} aria-hidden />
        <span>{move.san}</span>
        {SYMBOLS[move.classification] && <span className="sym">{SYMBOLS[move.classification]}</span>}
      </div>
    );
  };

  return (
    <div ref={list} className="movelist" aria-label="Moves">
      {rows(moves).map((row, i) => (
        <div key={i} style={{ display: "contents" }}>
          <div className="num">{row.number}.</div>
          {cell(row.white)}
          {cell(row.black)}
        </div>
      ))}
    </div>
  );
}
