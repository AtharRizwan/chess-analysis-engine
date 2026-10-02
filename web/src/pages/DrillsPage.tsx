import type { Key } from "@lichess-org/chessground/types";
import { useCallback, useEffect, useMemo, useState } from "react";
import { type Annotation, api, type DrillCard, type DrillStats, type LineRef, type MoveReview } from "../api/client";
import { Board } from "../components/Board";
import { CoachPanel } from "../components/CoachPanel";
import { type RetryFeedback, RetryPanel } from "../components/RetryPanel";
import { numberLine, play, positionsAlong, squaresOf, uciFromDrag } from "../lib/chess";
import { themeLabel } from "../lib/format";

type Outcome = { correct: boolean; answer: MoveReview; san?: string };
type LineView = { line: LineRef; index: number; title: string };

/** Your own mistakes as puzzles, scheduled with spaced repetition. */
export function DrillsPage({ theme }: { theme?: string }) {
  const [cards, setCards] = useState<DrillCard[] | null>(null);
  const [stats, setStats] = useState<DrillStats | null>(null);
  const [index, setIndex] = useState(0);
  const [hints, setHints] = useState(0);
  const [attempts, setAttempts] = useState(0);
  const [feedback, setFeedback] = useState<RetryFeedback>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [lineView, setLineView] = useState<LineView | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.dueDrills(theme).then(setCards).catch((e) => setError(String(e.message ?? e)));
    api.drillStats().then(setStats).catch(() => undefined);
  }, [theme]);
  useEffect(load, [load]);

  const card = cards?.[index];
  const linePositions = useMemo(() => (lineView ? positionsAlong(lineView.line.start_fen, lineView.line.uci) : []), [lineView]);

  const next = () => {
    setIndex((i) => i + 1);
    setHints(0);
    setAttempts(0);
    setFeedback(null);
    setOutcome(null);
    setLineView(null);
    setError(null);
    api.drillStats().then(setStats).catch(() => undefined);
  };

  const onMove = (orig: Key, dest: Key) => {
    if (!card) return;
    const uci = uciFromDrag(card.fen, orig, dest);
    const san = play(card.fen, uci).san;
    setFeedback({ kind: "checking", san });
    setError(null);
    api
      .attemptDrill(card.id, uci)
      .then((result) => {
        setAttempts((a) => a + 1);
        if (result.correct) {
          setFeedback(null);
          setOutcome({ correct: true, answer: result.answer, san });
        } else if (result.attempt) {
          setFeedback({ kind: "wrong", attempt: result.attempt });
        }
      })
      .catch((e: unknown) => {
        setFeedback(null);
        setError(e instanceof Error ? e.message : String(e));
      });
  };

  const reveal = () => {
    if (!card) return;
    api
      .revealDrill(card.id)
      .then((answer) => {
        setFeedback(null);
        setOutcome({ correct: false, answer });
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  };

  const header = (
    <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
      <div>
        <h2 style={{ margin: 0 }}>Drills{theme ? ` · ${themeLabel(theme)}` : ""}</h2>
        <div className="muted small">
          Positions where you went wrong. Solve one and it comes back after 3, 7, 14 and 30 days; miss it and
          it returns tomorrow.
        </div>
      </div>
      {stats && (
        <div className="muted small">
          {stats.due} due · {stats.total} in total
          {theme && (
            <>
              {" · "}
              <a href="#/drills">all themes</a>
            </>
          )}
        </div>
      )}
    </div>
  );

  if (error && !card) return <p className="error">{error}</p>;
  if (!cards) return <p className="muted">Loading…</p>;
  if (!card) {
    return (
      <>
        {header}
        <div className="card">
          <h3>{cards.length ? "Session done!" : "Nothing due right now"}</h3>
          <p className="muted">
            {stats?.total
              ? "Come back later for the next round, or review more games to add new positions."
              : "Review some of your games first: every mistake, miss or blunder of yours becomes a drill."}
          </p>
          <a href="#/">Go to your games</a>
        </div>
      </>
    );
  }

  // --- board ---------------------------------------------------------------------------------
  let fen = card.fen;
  let lastMove: [Key, Key] | undefined = card.moves.length ? squaresOf(card.moves.at(-1)!) : undefined;
  let annotations: Annotation[] = hints >= 2 && card.focus ? [{ orig: card.focus, brush: "yellow" }] : [];
  if (outcome?.answer.best?.uci.length) {
    const best = outcome.answer.best.uci[0];
    annotations = [{ orig: best.slice(0, 2), dest: best.slice(2, 4), brush: "green" }];
  }
  if (lineView) {
    fen = linePositions[lineView.index];
    lastMove = lineView.index ? squaresOf(lineView.line.uci[lineView.index - 1]) : undefined;
    const upcoming = lineView.line.uci[lineView.index];
    annotations = upcoming ? [{ orig: upcoming.slice(0, 2), dest: upcoming.slice(2, 4), brush: "blue" }] : [];
  }

  return (
    <>
      {header}
      <div className="review">
        <div>
          <Board
            fen={fen}
            orientation={card.color}
            lastMove={lastMove}
            annotations={annotations}
            interactive={!outcome && !lineView && feedback?.kind !== "checking"}
            onMove={onMove}
          />
          {lineView && (
            <div className="mode-banner">
              <div className="grow small">
                <strong>{lineView.title}</strong>
                <div>{numberLine(lineView.line.start_fen, lineView.line.san.slice(0, Math.max(lineView.index, 1)))}</div>
              </div>
              <button onClick={() => setLineView({ ...lineView, index: Math.max(0, lineView.index - 1) })}>◀</button>
              <button
                onClick={() => setLineView({ ...lineView, index: Math.min(lineView.line.uci.length, lineView.index + 1) })}
              >
                ▶
              </button>
              <button className="primary" onClick={() => setLineView(null)}>
                Back
              </button>
            </div>
          )}
          <p className="muted small">
            Drill {index + 1} of {cards.length} · from <a href={`#/review/${card.game_id}/${card.ply}`}>this game</a>
          </p>
        </div>
        <div className="side-panel">
          {outcome ? (
            <>
              <div className="card">
                <h3 style={{ margin: 0 }}>
                  {outcome.correct ? `✓ Correct — ${outcome.san}` : `The answer was ${outcome.answer.best?.san?.[0] ?? ""}`}
                </h3>
                <p className="muted small" style={{ margin: "4px 0 10px" }}>
                  {outcome.correct
                    ? attempts > 1
                      ? `Found in ${attempts} tries — it will come back sooner than a first-try solve.`
                      : "First try. This one will come back in a few days."
                    : "It comes back tomorrow. Read why, then try the next one."}
                </p>
                <button className="primary" onClick={next}>
                  Next drill
                </button>
              </div>
              <CoachPanel
                move={outcome.answer}
                userColor={card.color}
                kicker="What happened in your game"
                onShowLine={(line, title) => setLineView({ line, index: 0, title })}
              />
            </>
          ) : (
            <RetryPanel
              title={`Find a better move for ${card.color === "white" ? "White" : "Black"}`}
              prompt={`In your game you played ${card.played} here. There was something clearly better — drag a piece to try.`}
              hints={card.hints ?? []}
              hintsShown={hints}
              attempts={attempts}
              feedback={feedback}
              error={error}
              onHint={() => setHints((h) => h + 1)}
              onReveal={reveal}
            />
          )}
        </div>
      </div>
    </>
  );
}
