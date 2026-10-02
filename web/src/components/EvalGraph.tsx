import { useState } from "react";
import type { Classification, MoveReview } from "../api/client";
import { moveLabel } from "../lib/chess";
import { LABELS, SYMBOLS } from "../lib/format";
import { useWidth } from "../lib/useWidth";

type Props = {
  moves: MoveReview[];
  ply: number;
  onSelect: (ply: number) => void;
};

const HEIGHT = 110;
const PAD_X = 6;
const PAD_Y = 8;
// Only the moments that matter get a marker; inaccuracies stay in the move list (?!), where
// they don't crowd the graph. Good moves are diamonds, bad ones circles: shape carries the
// good/bad split, so it never rests on color alone.
const MARKED: Partial<Record<Classification, { shape: "diamond" | "circle"; color: string }>> = {
  brilliant: { shape: "diamond", color: "var(--accent)" },
  great: { shape: "diamond", color: "var(--accent)" },
  mistake: { shape: "circle", color: "var(--serious)" },
  miss: { shape: "circle", color: "var(--serious)" },
  blunder: { shape: "circle", color: "var(--critical)" },
};

/** White's winning chances over the game. Click or hover to explore; the move list is the table view. */
export function EvalGraph({ moves, ply, onSelect }: Props) {
  const [box, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  if (!moves.length) return null;
  const wins = [moves[0].win_before, ...moves.map((m) => m.win_after)];
  const n = wins.length - 1;
  const x = (i: number) => PAD_X + (i / Math.max(1, n)) * (width - 2 * PAD_X);
  const y = (w: number) => PAD_Y + ((100 - w) / 100) * (HEIGHT - 2 * PAD_Y);
  const mid = y(50);
  const path = wins.map((w, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(w).toFixed(1)}`).join(" ");
  const area = `${path} L${x(n).toFixed(1)},${mid} L${x(0).toFixed(1)},${mid} Z`;

  const nearest = (clientX: number) => {
    const rect = box.current?.getBoundingClientRect();
    if (!rect) return 0;
    const fraction = (clientX - rect.left - PAD_X) / Math.max(1, rect.width - 2 * PAD_X);
    return Math.max(0, Math.min(n, Math.round(fraction * n)));
  };

  const hovered = hover !== null && hover > 0 ? moves[hover - 1] : null;
  return (
    <div className="evalgraph">
      <div className="title">White's winning chances</div>
      <div ref={box} style={{ position: "relative" }}>
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label="White's winning chances across the game; use the move list to read individual moves"
          onPointerMove={(e) => setHover(nearest(e.clientX))}
          onPointerLeave={() => setHover(null)}
          onClick={(e) => onSelect(nearest(e.clientX))}
        >
          <line x1={0} x2={width} y1={mid} y2={mid} stroke="var(--baseline)" strokeWidth={1} />
          <path d={area} fill="var(--accent-wash)" />
          <path d={path} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {hover !== null && (
            <line x1={x(hover)} x2={x(hover)} y1={0} y2={HEIGHT} stroke="var(--muted)" strokeWidth={1} />
          )}
          <line x1={x(ply)} x2={x(ply)} y1={0} y2={HEIGHT} stroke="var(--ink-2)" strokeWidth={1.5} />
          {moves.map((m, i) => {
            const mark = MARKED[m.classification];
            if (!mark) return null;
            const cx = x(i + 1);
            const cy = y(m.win_after);
            return mark.shape === "circle" ? (
              <circle key={i} cx={cx} cy={cy} r={4.5} fill={mark.color} stroke="var(--surface)" strokeWidth={2} />
            ) : (
              <rect
                key={i}
                x={cx - 4.5}
                y={cy - 4.5}
                width={9}
                height={9}
                transform={`rotate(45 ${cx} ${cy})`}
                fill={mark.color}
                stroke="var(--surface)"
                strokeWidth={2}
              />
            );
          })}
        </svg>
        {hovered && hover !== null && (
          <div className="tooltip" style={{ left: x(hover), top: y(hovered.win_after) }}>
            <strong>White {Math.round(hovered.win_after)}%</strong>
            <div className="muted">
              {moveLabel(hovered.move_number, hovered.color, hovered.san)}
              {SYMBOLS[hovered.classification] ?? ""} · {LABELS[hovered.classification]}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
