import type { Classification, GameReview } from "../api/client";
import { moveLabel } from "../lib/chess";
import { LABELS } from "../lib/format";
import { Badge } from "./Badge";

const ORDER: Classification[] = [
  "brilliant",
  "great",
  "best",
  "excellent",
  "good",
  "book",
  "inaccuracy",
  "mistake",
  "miss",
  "blunder",
];

type Props = { review: GameReview; onSelect: (ply: number) => void };

/** The game at a glance: accuracy, classifications per side and the moments worth studying. */
export function GameSummary({ review, onSelect }: Props) {
  const summary = review.summary ?? {};
  const white = summary.white;
  const black = summary.black;
  const moves = review.moves ?? [];
  const moments = (review.key_moments ?? []).map((ply) => moves[ply - 1]).filter(Boolean);
  const you = review.user_color;
  const name = (side: "white" | "black") =>
    `${review[side].name}${review[side].rating ? ` (${review[side].rating})` : ""}${you === side ? " · you" : ""}`;

  return (
    <div className="card stack">
      <div>
        <h2>
          {name("white")} vs {name("black")} — {review.result}
        </h2>
        {review.opening && (
          <div className="muted small">
            {review.opening.eco} {review.opening.name}
            {review.left_book_ply ? ` · left theory with ${leftBook(review)}` : ""}
          </div>
        )}
      </div>
      <div className="summary-grid">
        <span className="head" />
        <span className="head">White</span>
        <span className="head">Black</span>
        <span>Accuracy</span>
        <strong>{white?.accuracy ?? "–"}</strong>
        <strong>{black?.accuracy ?? "–"}</strong>
        {ORDER.filter((c) => white?.counts?.[c] || black?.counts?.[c]).map((c) => (
          <div key={c} style={{ display: "contents" }}>
            <span className="row" style={{ gap: 6 }}>
              <span className={`cls-dot cls-${c}`} aria-hidden />
              {LABELS[c]}
            </span>
            <span>{white?.counts?.[c] ?? 0}</span>
            <span>{black?.counts?.[c] ?? 0}</span>
          </div>
        ))}
      </div>
      {moments.length > 0 && (
        <div>
          <h3>{you ? "Your key moments" : "Key moments"}</h3>
          <div className="moments">
            {moments.map((m) => (
              <button key={m.ply} onClick={() => onSelect(m.ply)}>
                <Badge value={m.classification} />
                <span>{moveLabel(m.move_number, m.color, m.san)}</span>
                <span className="muted small">{m.explanation?.headline}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="muted small">
        {review.engine} · {review.preset} preset (depth {review.depth})
      </div>
    </div>
  );
}

function leftBook(review: GameReview): string {
  const move = (review.moves ?? [])[(review.left_book_ply ?? 1) - 1];
  return move ? moveLabel(move.move_number, move.color, move.san) : "";
}
