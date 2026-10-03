import { useContext, useMemo } from "react";
import type { DrillCard, LineRef } from "../api/client";
import { moveLabel } from "../lib/chess";
import { chancesFor, pct } from "../lib/format";
import { buildIndex } from "../lib/notation";
import { Badge } from "./Badge";
import { BoardLinkContext, ChessText } from "./ChessText";

type Props = {
  card: DrillCard;
  onShowLine: (line: LineRef, title: string) => void;
  onStart: () => void;
};

/** Before the puzzle: the move you played in the game (red arrow on the board) and why it was bad. */
export function DrillIntro({ card, onShowLine, onStart }: Props) {
  const link = useContext(BoardLinkContext);
  const notation = useMemo(
    () => (link ? buildIndex({ lines: [card.why_line], game: link.game, anchors: [card.fen] }) : null),
    [card, link?.game],
  );
  const label = moveLabel(Number(card.fen.split(" ")[5]) || 1, card.color, card.played);
  const before = chancesFor(card.win_before ?? 50, card.color);
  const after = chancesFor(card.win_after ?? 50, card.color);
  return (
    <div className="card coach">
      <div className="muted small">In your game you played</div>
      <div className="move-head">
        <h2>{label}</h2>
        {card.classification && <Badge value={card.classification} />}
      </div>
      <div className="chances">
        Your winning chances {pct(before)} → {pct(after)}
      </div>
      <section>
        <h4>Why it's bad</h4>
        <p>
          <ChessText text={card.why ?? ""} index={notation} />
        </p>
      </section>
      <div className="row actions">
        <button className="primary" onClick={onStart}>
          Find a better move →
        </button>
        {card.why_line && card.why_line.uci.length > 1 && (
          <button onClick={() => onShowLine(card.why_line!, `What happens after ${label}`)}>▶ Show what happens</button>
        )}
      </div>
    </div>
  );
}
