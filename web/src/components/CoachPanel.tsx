import { useEffect, useRef, useState } from "react";
import type { LineRef, MoveReview, Narration, Side } from "../api/client";
import { moveLabel } from "../lib/chess";
import { narrate, useCoachStatus, useCoachVoice } from "../lib/coach";
import { BAD, chancesFor, FACT_LABELS, MOTIF_LABELS, pct } from "../lib/format";
import { Badge } from "./Badge";

type Props = {
  move: MoveReview;
  userColor: Side | null;
  /** Shown above the move, e.g. "Your idea" when exploring. */
  kicker?: string;
  onShowLine: (line: LineRef, title: string) => void;
  /** Go back to the position before this move and try something else. */
  onTryAnother?: () => void;
  /** Link to this position's drill, for your own mistakes. */
  drillHref?: string;
};

const DIFFICULTY: Record<string, string> = {
  easy: "The better move was easy to find — a forcing move with a quick payoff.",
  medium: "The better move took a few moves of calculation.",
  hard: "The better move was hard to find, so focus on the lesson rather than the exact move.",
};

// With the coach voice on, these moves are narrated as soon as they're shown; others on request
// (each narration is a paid API call).
const AUTO_NARRATE = new Set(["inaccuracy", "mistake", "miss", "blunder", "great", "brilliant"]);

type CoachResult = { key: string; narration?: Narration; error?: string };

function chips(move: MoveReview): string[] {
  const seen = new Set<string>();
  for (const fact of move.facts ?? []) {
    const label = (fact.motif && MOTIF_LABELS[fact.motif]) || FACT_LABELS[fact.kind];
    if (label) seen.add(label);
  }
  return [...seen].slice(0, 5);
}

/** One move, explained: what happened, what was better, and the lesson to keep. */
export function CoachPanel({ move, userColor, kicker, onShowLine, onTryAnother, drillHref }: Props) {
  const status = useCoachStatus();
  const [voice, setVoice] = useCoachVoice();
  const [askedKey, setAskedKey] = useState<string | null>(null);
  const [result, setResult] = useState<CoachResult | null>(null);
  const moveKey = `${move.fen_before}|${move.uci}|${userColor ?? ""}`;
  const ready = Boolean(status?.ready);
  const wanted = ready && voice && (move.key_moment || AUTO_NARRATE.has(move.classification) || askedKey === moveKey);
  const current = result?.key === moveKey ? result : null;

  useEffect(() => {
    if (!wanted || current) return;
    let cancelled = false;
    // A short pause, so stepping quickly through the moves doesn't narrate every one passed.
    const timer = setTimeout(() => {
      narrate(move, userColor)
        .then((narration) => !cancelled && setResult({ key: moveKey, narration }))
        .catch((e: unknown) => !cancelled && setResult({ key: moveKey, error: e instanceof Error ? e.message : String(e) }));
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // `move` itself is identified by moveKey: a new object for the same move needs no new request.
  }, [wanted, moveKey, Boolean(current)]);

  const askAgain = () => {
    setResult(null);
    narrate(move, userColor, true)
      .then((narration) => setResult({ key: moveKey, narration }))
      .catch((e: unknown) => setResult({ key: moveKey, error: e instanceof Error ? e.message : String(e) }));
  };

  // A new move starts at the top of the explanation (it scrolls inside the card on wide screens).
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (body.current) body.current.scrollTop = 0;
  }, [moveKey]);

  const perspective: Side = userColor ?? move.color;
  const whose = userColor ? "Your" : `${perspective === "white" ? "White" : "Black"}'s`;
  const before = chancesFor(move.win_before, perspective);
  const after = chancesFor(move.win_after, perspective);
  const coached = voice && current?.narration?.source === "coach" ? current.narration.explanation : null;
  const explanation = coached ?? move.explanation;
  const fallback = voice && current?.narration?.source === "template" ? current.narration : null;
  const label = moveLabel(move.move_number, move.color, move.san);
  const bad = BAD.has(move.classification);
  const best = move.best?.san?.[0];
  const bestLine: LineRef | null =
    move.best && move.best.uci.length && best !== move.san
      ? { start_fen: move.fen_before, uci: move.best.uci, san: move.best.san }
      : null;

  return (
    <div className="card coach">
      <div className="coach-head">
        {kicker && <div className="muted small">{kicker}</div>}
        <div className="move-head">
          <h2>{label}</h2>
          <Badge value={move.classification} />
          {ready && (
            <button
              className="voice-toggle"
              aria-pressed={voice}
              title="Retell this move in a coach's words with Claude, checked against the verified facts"
              onClick={() => setVoice(!voice)}
            >
              ✦ Coach voice
            </button>
          )}
        </div>
        <div className="chances">
          {whose} winning chances {pct(before)} → {pct(after)}
          {move.clock?.spent !== null && move.clock?.spent !== undefined && ` · played in ${Math.round(move.clock.spent)}s`}
        </div>
      </div>
      <div className="coach-body" ref={body}>
        {explanation && (
          <div className="headline">
            {explanation.headline}
            {coached && (
              <span className="ai-tag" title="Written by Claude from the facts below, and checked against them">
                ✦ AI
              </span>
            )}
          </div>
        )}
        {voice && ready && wanted && !current && <div className="muted small">✦ The coach is writing…</div>}
        {voice && ready && !wanted && (
          <button className="linkish" onClick={() => setAskedKey(moveKey)}>
            ✦ Ask the coach about this move
          </button>
        )}
        {voice && current?.error && <div className="muted small">✦ The coach is unavailable: {current.error}</div>}
        {fallback && (
          <div className="muted small">
            ✦ The coach's wording didn't match the verified facts, so this is the standard explanation.{" "}
            <button className="linkish small" onClick={askAgain}>
              Ask again
            </button>
            {fallback.problems && fallback.problems.length > 0 && (
              <details>
                <summary>What didn't match</summary>
                <ul>
                  {fallback.problems.map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
        {(explanation?.sections ?? []).map((section, i) => (
          <section key={i}>
            <h4>{section.title}</h4>
            <p>{section.text}</p>
            {section.line && section.line.uci.length > 0 && (
              <button className="linkish" onClick={() => onShowLine(section.line!, section.title)}>
                ▶ Show this line on the board
              </button>
            )}
          </section>
        ))}
        {explanation?.lesson && (
          <div className="lesson">
            <strong>Lesson: </strong>
            {explanation.lesson}
          </div>
        )}
        {bad && move.difficulty && <p className="muted small">{DIFFICULTY[move.difficulty]}</p>}
        {chips(move).length > 0 && (
          <div className="chips">
            {chips(move).map((c) => (
              <span key={c} className="chip">
                {c}
              </span>
            ))}
          </div>
        )}
        {drillHref && (
          <p className="small">
            <a href={drillHref}>Practice this position as a drill →</a>
          </p>
        )}
      </div>
      {/* Same buttons in the same places on every move: unavailable ones are disabled, not removed. */}
      <div className="row actions">
        <button
          disabled={!bestLine}
          title={bestLine ? undefined : "This was the engine's move"}
          onClick={() => bestLine && onShowLine(bestLine, `Engine's best: ${moveLabel(move.move_number, move.color, best ?? "")}`)}
        >
          Show best line
        </button>
        {onTryAnother && <button onClick={onTryAnother}>Try a different move here</button>}
      </div>
    </div>
  );
}
