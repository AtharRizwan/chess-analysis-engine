import type { MoveReview, Side } from "../api/client";
import { evalText } from "../lib/format";

type Props = { whiteWin: number; score: MoveReview["eval_after"] | null; orientation: Side };

/** Vertical bar: White's share grows from White's side of the board. */
export function EvalBar({ whiteWin, score, orientation }: Props) {
  const white = Math.max(2, Math.min(98, whiteWin));
  const whiteAtBottom = orientation === "white";
  const text = score ? evalText(score) : "";
  const whiteLeads = whiteWin >= 50;
  return (
    <div className="evalbar" role="img" aria-label={`White's winning chances ${Math.round(whiteWin)}%`}>
      <div className="white" style={{ height: `${white}%`, [whiteAtBottom ? "bottom" : "top"]: 0 }} />
      {text && (
        <div
          className="label"
          style={{
            [whiteLeads === whiteAtBottom ? "bottom" : "top"]: 4,
            color: whiteLeads ? "#0b0b0b" : "#f4f3ef",
          }}
        >
          {text}
        </div>
      )}
    </div>
  );
}
