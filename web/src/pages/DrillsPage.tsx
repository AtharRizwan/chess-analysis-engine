import type { Key } from "@lichess-org/chessground/types";
import { useCallback, useEffect, useMemo, useState } from "react";
import { type Annotation, api, type DrillCard, type DrillStats, type LineRef, type MoveReview } from "../api/client";
import { Board } from "../components/Board";
import { type BoardLink, BoardLinkContext, useBoardPreview } from "../components/ChessText";
import { CoachPanel } from "../components/CoachPanel";
import { DrillIntro } from "../components/DrillIntro";
import { type RetryFeedback, RetryPanel } from "../components/RetryPanel";
import { numberLine, play, positionsAlong, squaresOf, uciFromDrag } from "../lib/chess";
import { themeLabel } from "../lib/format";

type Outcome = { correct: boolean; answer: MoveReview; san?: string; dueAt?: string };
type LineView = { line: LineRef; index: number; title: string };
/** The move you just tried: the board shows it until you take it back. */
type Tried = { uci: string; san: string; fen: string };

function whenDue(dueAt: string | undefined): string {
  if (!dueAt) return "";
  const days = Math.round((Date.parse(dueAt) - Date.now()) / 86_400_000);
  if (days <= 0) return "It's still due, so you'll see it again.";
  return days === 1 ? "It comes back tomorrow." : `Next review in ${days} days.`;
}

/** Your own mistakes as puzzles, scheduled with spaced repetition. With `drillId`: practise just that one. */
export function DrillsPage({ theme, drillId }: { theme?: string; drillId?: number }) {
  const [cards, setCards] = useState<DrillCard[] | null>(null);
  const [stats, setStats] = useState<DrillStats | null>(null);
  const [index, setIndex] = useState(0);
  // Each drill starts by showing the move you played and why it was bad, then the puzzle.
  const [stage, setStage] = useState<"intro" | "try">("intro");
  const [hints, setHints] = useState(0);
  const [attempts, setAttempts] = useState(0);
  const [tried, setTried] = useState<Tried | null>(null);
  const [feedback, setFeedback] = useState<RetryFeedback>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [lineView, setLineView] = useState<LineView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const practice = drillId !== undefined;

  const load = useCallback(() => {
    const request = practice ? api.drill(drillId).then((c) => [c]) : api.dueDrills(theme);
    request.then(setCards).catch((e) => setError(String(e.message ?? e)));
    api.drillStats().then(setStats).catch(() => undefined);
  }, [theme, drillId, practice]);
  useEffect(load, [load]);

  const card = cards?.[index];
  const linePositions = useMemo(() => (lineView ? positionsAlong(lineView.line.start_fen, lineView.line.uci) : []), [lineView]);

  // Moves mentioned in the texts: hover shows one on the board, click steps into its line.
  const viewKey = `${index}:${stage}:${lineView?.index ?? ""}:${tried?.uci ?? ""}:${outcome ? 1 : 0}`;
  const { preview, active, show, clear } = useBoardPreview(viewKey);
  const boardLink = useMemo<BoardLink>(
    () => ({
      preview: show,
      active,
      game: card ? { start_fen: card.start_fen, uci: card.moves, san: [] } : null,
      open: (ref) => {
        clear();
        setLineView({ line: ref.line, index: ref.index + 1, title: `From the explanation: ${ref.label}` });
      },
    }),
    [show, active, clear, card],
  );

  const next = () => {
    setIndex((i) => i + 1);
    setStage("intro");
    setHints(0);
    setAttempts(0);
    setTried(null);
    setFeedback(null);
    setOutcome(null);
    setLineView(null);
    setError(null);
    api.drillStats().then(setStats).catch(() => undefined);
  };

  const tryAgain = () => {
    setTried(null);
    setFeedback(null);
  };

  const onMove = (orig: Key, dest: Key) => {
    if (!card) return;
    const uci = uciFromDrag(card.fen, orig, dest);
    const after = play(card.fen, uci);
    setTried({ uci, san: after.san, fen: after.fen });
    setFeedback({ kind: "checking", san: after.san });
    setError(null);
    api
      .attemptDrill(card.id, uci)
      .then((result) => {
        setAttempts((a) => a + 1);
        if (result.verdict === "solved") {
          setFeedback(null);
          setOutcome({ correct: true, answer: result.answer, san: after.san, dueAt: result.card.due_at });
        } else {
          setFeedback({ kind: result.verdict, san: after.san, attempt: result.attempt ?? null });
        }
      })
      .catch((e: unknown) => {
        setTried(null);
        setFeedback(null);
        setError(e instanceof Error ? e.message : String(e));
      });
  };

  const reveal = () => {
    if (!card) return;
    api
      .revealDrill(card.id)
      .then(async (answer) => {
        setTried(null);
        setFeedback(null);
        const updated = await api.drill(card.id).catch(() => null);
        setOutcome({ correct: false, answer, dueAt: updated?.due_at });
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  };

  const header = (
    <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
      <div>
        <h2 style={{ margin: 0 }}>{practice ? "Practice" : `Drills${theme ? ` · ${themeLabel(theme)}` : ""}`}</h2>
        <div className="muted small">
          {practice
            ? "One position from your game. Practising early doesn't change when it's next due."
            : "Positions where you went wrong. Solve one and it comes back after 3, 7, 14 and 30 days; miss it and it returns tomorrow."}
        </div>
      </div>
      {stats && (
        <div className="muted small">
          {stats.due} due · {stats.total} in total
          {(theme || practice) && (
            <>
              {" · "}
              <a href="#/drills">{practice ? "your due drills" : "all themes"}</a>
            </>
          )}
        </div>
      )}
    </div>
  );

  if (error && !card) return <p className="error">{error}</p>;
  if (!cards) return <p className="muted">Loading…</p>;
  if (!card) {
    const first = cards[0];
    return (
      <>
        {header}
        <div className="card">
          <h3>{practice ? "Done!" : cards.length ? "Session done!" : "Nothing due right now"}</h3>
          <p className="muted">
            {practice
              ? "Go back to the game, or carry on with the drills that are due."
              : stats?.total
                ? "Come back later for the next round, or review more games to add new positions."
                : "Review some of your games first: every mistake, miss or blunder of yours becomes a drill."}
          </p>
          <div className="row">
            {practice && first && <a href={`#/review/${first.game_id}/${first.ply}`}>Back to the game</a>}
            <a href={practice ? "#/drills" : "#/"}>{practice ? "Your due drills" : "Go to your games"}</a>
          </div>
        </div>
      </>
    );
  }

  // --- board ---------------------------------------------------------------------------------
  let fen = card.fen;
  let lastMove: [Key, Key] | undefined = card.moves.length ? squaresOf(card.moves.at(-1)!) : undefined;
  let annotations: Annotation[] = hints >= 2 && card.focus ? [{ orig: card.focus, brush: "yellow" }] : [];
  if (stage === "intro" && card.played_uci) {
    annotations = [{ orig: card.played_uci.slice(0, 2), dest: card.played_uci.slice(2, 4), brush: "red" }];
  } else if (tried) {
    // Your move stays on the board while it's checked, and afterwards, until you take it back.
    fen = tried.fen;
    lastMove = squaresOf(tried.uci);
    annotations = [];
    const reply = feedback?.kind === "wrong" ? feedback.attempt?.refutation?.uci?.[0] : undefined;
    if (reply) annotations = [{ orig: reply.slice(0, 2), dest: reply.slice(2, 4), brush: "red" }];
    if (outcome?.correct) annotations = [{ orig: tried.uci.slice(2, 4), brush: "green" }];
  } else if (outcome?.answer.best?.uci.length) {
    const best = outcome.answer.best.uci[0];
    annotations = [{ orig: best.slice(0, 2), dest: best.slice(2, 4), brush: "green" }];
  }
  if (lineView) {
    fen = linePositions[lineView.index];
    lastMove = lineView.index ? squaresOf(lineView.line.uci[lineView.index - 1]) : undefined;
    const upcoming = lineView.line.uci[lineView.index];
    annotations = upcoming ? [{ orig: upcoming.slice(0, 2), dest: upcoming.slice(2, 4), brush: "blue" }] : [];
  }
  if (preview) {
    fen = preview.fen;
    lastMove = undefined;
    annotations = [{ orig: preview.uci.slice(0, 2), dest: preview.uci.slice(2, 4), brush: "blue" }];
  }
  const side = card.color === "white" ? "White" : "Black";

  return (
    <BoardLinkContext.Provider value={boardLink}>
      {header}
      <div className="review">
        <div>
          <Board
            fen={fen}
            orientation={card.color}
            lastMove={lastMove}
            annotations={annotations}
            interactive={stage === "try" && !outcome && !lineView && !tried && !preview}
            onMove={onMove}
            animate={!preview}
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
            {practice ? "" : `Drill ${index + 1} of ${cards.length} · `}from{" "}
            <a href={`#/review/${card.game_id}/${card.ply}`}>this game</a>
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
                  {outcome.correct ? (attempts > 1 ? `Found in ${attempts} tries. ` : "First try! ") : "Read why below. "}
                  {whenDue(outcome.dueAt)}
                </p>
                <button className="primary" onClick={next}>
                  {practice ? "Done" : "Next drill"}
                </button>
              </div>
              <CoachPanel
                move={outcome.answer}
                userColor={card.color}
                kicker="What happened in your game"
                onShowLine={(line, title) => setLineView({ line, index: 0, title })}
              />
            </>
          ) : stage === "intro" ? (
            <DrillIntro
              card={card}
              onShowLine={(line, title) => setLineView({ line, index: 0, title })}
              onStart={() => {
                setLineView(null);
                setStage("try");
              }}
            />
          ) : (
            <RetryPanel
              title={`${side} to move: find a better move`}
              prompt={`In your game you played ${card.played} here. There was something clearly better — drag a piece to try.`}
              hints={card.hints ?? []}
              hintsShown={hints}
              attempts={attempts}
              feedback={feedback}
              error={error}
              onHint={() => setHints((h) => h + 1)}
              onReveal={reveal}
              onTryAgain={tryAgain}
            />
          )}
        </div>
      </div>
    </BoardLinkContext.Provider>
  );
}
