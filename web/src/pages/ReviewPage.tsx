import type { Key } from "@lichess-org/chessground/types";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type Annotation,
  api,
  type GameReview,
  type GameSummary as GameRow,
  type JobStatus,
  type LineRef,
  type PositionScore,
  type Side,
  watchJob,
} from "../api/client";
import { Board } from "../components/Board";
import { type BoardLink, BoardLinkContext, useBoardPreview } from "../components/ChessText";
import { CoachPanel } from "../components/CoachPanel";
import { EvalBar } from "../components/EvalBar";
import { EvalGraph } from "../components/EvalGraph";
import { GameSummary } from "../components/GameSummary";
import { LineMoves } from "../components/LineMoves";
import { MoveList } from "../components/MoveList";
import { gamePliesAlong, positionsAlong, squaresOf, uciFromDrag } from "../lib/chess";
import { branchOff, explainRequest, type Exploration, exploreGame, moveKey, playMove, stepTo } from "../lib/explore";
import { useFetched } from "../lib/useFetched";

type View =
  | { kind: "game" }
  // `returnTo`: your own line, when this line was opened from one of its explanations.
  | { kind: "line"; line: LineRef; index: number; title: string; returnTo: Exploration | null }
  | { kind: "explore"; exploration: Exploration };

const STAGES: Record<string, string> = {
  engine: "Analyzing every position",
  critical: "Double-checking the critical moves",
  facts: "Working out why each move is good or bad",
};

const notGreen = (annotations: Annotation[] | undefined) => (annotations ?? []).filter((a) => a.brush !== "green");

export function ReviewPage({ gameId, initialPly }: { gameId: number; initialPly?: number }) {
  const [game, setGame] = useState<GameRow | null>(null);
  const [drills, setDrills] = useState<Map<number, number>>(new Map()); // ply -> drill id
  const [review, setReview] = useState<GameReview | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ply, setPly] = useState(0);
  const [view, setView] = useState<View>({ kind: "game" });
  const [flipped, setFlipped] = useState(false);
  const [lineEvals, setLineEvals] = useState<{ line: LineRef; evals: PositionScore[] } | null>(null);

  useEffect(() => {
    let cancelled = false;
    let stop: (() => void) | undefined;
    setReview(null);
    setError(null);
    setPly(0);
    setView({ kind: "game" });
    (async () => {
      try {
        const summary = await api.game(gameId);
        if (cancelled) return;
        setGame(summary);
        if (summary.review_status === "done") {
          const loaded = await api.review(gameId);
          if (!cancelled) setReview(loaded);
          return;
        }
        const active = (await api.activeJob(gameId)) ?? (await api.startReview(gameId));
        if (cancelled) return;
        setJob(active);
        stop = watchJob(active.id, (update) => {
          setJob(update);
          if (update.status === "done") api.review(gameId).then((loaded) => !cancelled && setReview(loaded));
          if (update.status === "error") setError(update.error ?? "The review failed.");
        });
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
      stop?.();
    };
  }, [gameId]);

  useEffect(() => {
    // Your mistakes become drills when the review finishes; link to them from the explanation.
    if (!review) return;
    api
      .gameDrills(gameId)
      .then((cards) => setDrills(new Map(cards.map((c) => [c.ply, c.id]))))
      .catch(() => undefined);
  }, [gameId, review]);

  const moves = useMemo(() => review?.moves ?? [], [review]);

  useEffect(() => {
    if (review && initialPly) setPly(Math.max(0, Math.min(review.moves?.length ?? 0, initialPly)));
  }, [review, initialPly]);
  const fens = useMemo(() => (review ? [review.start_fen, ...moves.map((m) => m.fen_after)] : []), [review, moves]);
  const gameUci = useMemo(() => moves.map((m) => m.uci), [moves]);
  const userColor: Side | null = review?.user_color ?? null;
  const baseOrientation: Side = userColor ?? "white";
  const orientation: Side = flipped ? (baseOrientation === "white" ? "black" : "white") : baseOrientation;

  const linePositions = useMemo(
    () => (view.kind === "line" ? positionsAlong(view.line.start_fen, view.line.uci) : []),
    [view],
  );
  // Stepping through a line moves the eval bar: positions of the game keep the review's numbers,
  // the others are evaluated once when the line opens.
  const openLine = view.kind === "line" ? view.line : null;
  const lineGamePlies = useMemo(
    () => (openLine ? gamePliesAlong(openLine.start_fen, openLine.uci, fens, gameUci) : []),
    [openLine, fens, gameUci],
  );
  useEffect(() => {
    if (!openLine) return;
    let cancelled = false;
    api
      .evaluate(openLine.start_fen, openLine.uci)
      .then((evals) => !cancelled && setLineEvals({ line: openLine, evals }))
      .catch(() => undefined); // no engine: the bar keeps showing the game's evaluation
    return () => {
      cancelled = true;
    };
  }, [openLine]);

  // Your own line: on the board, or behind the line you opened from it (the panel stays on its move).
  const exploring = view.kind === "explore" ? view.exploration : null;
  const mine = exploring ?? (view.kind === "line" ? view.returnTo : null);
  const exploringFen = exploring ? exploring.positions[exploring.index] : null;
  const explained = useFetched(mine?.index ? moveKey(mine) : null, () =>
    api.explain({ ...explainRequest(mine!), user_color: userColor }),
  );
  const answer = mine?.index ? explained.get(moveKey(mine)) : undefined;
  // The explanation takes seconds; a quick search moves the eval bar right away.
  const needsQuickScore = exploringFen !== null && !fens.includes(exploringFen) && !answer?.value;
  const quickScores = useFetched(needsQuickScore ? exploringFen : null, () =>
    api.evaluate(exploringFen!, []).then(([score]) => score),
  );

  const current = ply ? moves[ply - 1] : null;

  const goto = useCallback((target: number) => {
    setView({ kind: "game" });
    setPly(Math.max(0, Math.min(moves.length, target)));
  }, [moves.length]);

  // The control row and the arrow keys step through whatever the board is showing.
  const step = useMemo(() => {
    if (view.kind === "line") {
      const last = view.line.uci.length;
      return { at: view.index, last, go: (index: number) => setView({ ...view, index: Math.max(0, Math.min(last, index)) }) };
    }
    if (view.kind === "explore") {
      const line = view.exploration;
      return { at: line.index, last: line.moves.length, go: (index: number) => setView({ kind: "explore", exploration: stepTo(line, index) }) };
    }
    return { at: ply, last: moves.length, go: goto };
  }, [view, ply, moves.length, goto]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.closest("input, textarea, select")) return;
      if (event.key === "Escape") setView((v) => (v.kind === "line" && v.returnTo ? { kind: "explore", exploration: v.returnTo } : { kind: "game" }));
      else if (event.key === "f") setFlipped((f) => !f);
      else if (event.key === "ArrowLeft") step.go(step.at - 1);
      else if (event.key === "ArrowRight") step.go(step.at + 1);
      else if (event.key === "Home") step.go(0);
      else if (event.key === "End") step.go(step.last);
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step]);

  const showLineAt = useCallback((line: LineRef, index: number, title: string) => {
    setView((v) => ({
      kind: "line",
      line,
      index,
      title,
      returnTo: v.kind === "explore" ? v.exploration : v.kind === "line" ? v.returnTo : null,
    }));
  }, []);

  // Moves mentioned in the explanations: hover shows one on the board, click steps into its line.
  const viewKey = `${ply}:${view.kind}:${view.kind === "line" ? view.index : ""}:${exploringFen ?? ""}`;
  const { preview, active, show, clear } = useBoardPreview(viewKey);
  const gameLine = useMemo(
    () => (review ? { start_fen: review.start_fen, uci: gameUci, san: moves.map((m) => m.san) } : null),
    [review, gameUci, moves],
  );
  const boardLink = useMemo<BoardLink>(
    () => ({
      preview: show,
      active,
      game: gameLine,
      open: (ref) => {
        clear();
        if (ref.game) goto(ref.index + 1);
        else showLineAt(ref.line, ref.index + 1, `From the explanation: ${ref.label}`);
      },
    }),
    [show, active, gameLine, clear, goto, showLineAt],
  );

  if (error) {
    return (
      <div className="card">
        <h2>Couldn't review this game</h2>
        <p className="error">{error}</p>
        <a href="#/">Back to your games</a>
      </div>
    );
  }
  if (!review) {
    const share = job && job.total ? Math.round((100 * job.done) / job.total) : 0;
    return (
      <div className="card stack" style={{ maxWidth: 560 }}>
        <h2>{game ? `${game.white} vs ${game.black}` : "Loading…"}</h2>
        <div>{job ? (job.status === "queued" ? "Waiting for the engine…" : STAGES[job.stage] ?? "Starting…") : "Loading…"}</div>
        <div className="progress" aria-label="Review progress">
          <div style={{ width: `${share}%` }} />
        </div>
        <div className="muted small">
          {job && job.total ? `${job.done} / ${job.total}` : ""} — this usually takes under a minute.
        </div>
      </div>
    );
  }

  // --- what the board shows -------------------------------------------------------------
  let fen = fens[ply];
  let lastMove: [Key, Key] | undefined = ply ? squaresOf(moves[ply - 1].uci) : undefined;
  let annotations: Annotation[] = ply ? notGreen(moves[ply - 1].explanation?.annotations) : [];
  const evalAt = (p: number) =>
    p
      ? { whiteWin: moves[p - 1].win_after, score: moves[p - 1].eval_after }
      : { whiteWin: moves[0]?.win_before ?? 50, score: moves[0]?.eval_before ?? null };
  let { whiteWin, score } = evalAt(ply);
  let interactive = true;
  if (view.kind === "line") {
    fen = linePositions[view.index];
    lastMove = view.index ? squaresOf(view.line.uci[view.index - 1]) : undefined;
    const next = view.line.uci[view.index];
    annotations = next ? [{ orig: next.slice(0, 2), dest: next.slice(2, 4), brush: "blue" }] : [];
    const gamePly = lineGamePlies[view.index];
    const evaluated = lineEvals?.line === view.line ? lineEvals.evals[view.index] : undefined;
    if (gamePly !== undefined) ({ whiteWin, score } = evalAt(gamePly));
    else if (evaluated) ({ win: whiteWin, score } = evaluated);
  } else if (exploring) {
    fen = exploringFen!;
    const last = exploring.index ? exploring.moves[exploring.index - 1] : exploring.history.at(-1);
    lastMove = last ? squaresOf(last) : undefined;
    annotations = notGreen(answer?.value?.explanation?.annotations);
    // The position's own number if it's known yet, else the nearest one before it.
    for (let i = exploring.index; i >= 0; i--) {
      const gamePly = fens.indexOf(exploring.positions[i]);
      const played = i ? explained.get(moveKey(exploring, i))?.value : undefined;
      const quick = quickScores.get(exploring.positions[i])?.value;
      if (gamePly >= 0) ({ whiteWin, score } = evalAt(gamePly));
      else if (played) ({ win_after: whiteWin, eval_after: score } = played);
      else if (quick) ({ win: whiteWin, score } = quick);
      else continue;
      break;
    }
  }

  if (preview) {
    // A move hovered (or tapped) in the explanation: its position, with the move as an arrow.
    fen = preview.fen;
    lastMove = undefined;
    annotations = [{ orig: preview.uci.slice(0, 2), dest: preview.uci.slice(2, 4), brush: "blue" }];
    interactive = false;
  }

  const onBoardMove = (orig: Key, dest: Key) => {
    const uci = uciFromDrag(fen, orig, dest);
    if (exploring) {
      setView({ kind: "explore", exploration: playMove(exploring, uci) });
    } else if (view.kind === "line") {
      // Playing the line's next move follows it; anything else starts a line of your own from here.
      if (view.line.uci[view.index] === uci) step.go(view.index + 1);
      else setView({ kind: "explore", exploration: branchOff(view.line, view.index, uci, view.returnTo, fens, gameUci) });
    } else if (gameUci[ply] === uci) {
      goto(ply + 1); // the move that was played: its review is already here
    } else {
      setView({ kind: "explore", exploration: playMove(exploreGame(fens, gameUci, ply), uci) });
    }
  };

  const showLine = (line: LineRef, title: string) => showLineAt(line, 0, title);

  return (
    <BoardLinkContext.Provider value={boardLink}>
      <div className="review">
        <div>
          <div className="board-area">
            <EvalBar whiteWin={whiteWin} score={score} orientation={orientation} />
            <Board
              fen={fen}
              orientation={orientation}
              lastMove={lastMove}
              annotations={annotations}
              interactive={interactive}
              onMove={onBoardMove}
              animate={!preview}
            />
          </div>
          <div className="board-controls">
            <button className="ghost" onClick={() => step.go(0)} disabled={step.at === 0} aria-label="Start">⏮</button>
            <button className="ghost" onClick={() => step.go(step.at - 1)} disabled={step.at === 0} aria-label="Previous move">◀</button>
            <button className="ghost" onClick={() => step.go(step.at + 1)} disabled={step.at === step.last} aria-label="Next move">▶</button>
            <button className="ghost" onClick={() => step.go(step.last)} disabled={step.at === step.last} aria-label="End">⏭</button>
            <button className="ghost" onClick={() => setFlipped((f) => !f)} aria-label="Flip board">⇅</button>
          </div>
          {view.kind === "game" && <div className="board-hint muted small">Drag any piece to try your own line.</div>}
          {view.kind === "line" && (
            <div className="mode-banner">
              <div className="grow small">
                <strong>{view.title}</strong>
                <LineMoves
                  fen={view.line.start_fen}
                  sans={view.line.san.slice(0, Math.max(view.index, 1))}
                  index={view.index}
                  onSelect={step.go}
                />
              </div>
              {view.returnTo && (
                <button className="primary" onClick={() => setView({ kind: "explore", exploration: view.returnTo! })}>
                  Back to my line
                </button>
              )}
              <button className={view.returnTo ? undefined : "primary"} onClick={() => setView({ kind: "game" })}>
                Back to the game
              </button>
            </div>
          )}
          {exploring && (
            <div className="mode-banner">
              <div className="grow small">
                <strong>Your line</strong>
                {exploring.moves.length ? (
                  <LineMoves fen={exploring.positions[0]} sans={exploring.sans} index={exploring.index} onSelect={step.go} />
                ) : (
                  <div>Drag a piece to try your own move from this position.</div>
                )}
              </div>
              <button className="primary" onClick={() => setView({ kind: "game" })}>Back to the game</button>
            </div>
          )}
          <EvalGraph moves={moves} ply={ply} onSelect={goto} />
        </div>

        <div className="side-panel fixed">
          <div className="panel-slot">
            {mine ? (
              !mine.index ? (
                <div className="card">
                  {mine.moves.length
                    ? "This is where your line starts. Drag a piece to try a different move, or press ▶ to replay it."
                    : "Drag a piece on the board to play the move you were considering. You'll see how the engine rates it and why."}
                </div>
              ) : answer?.error ? (
                <div className="card error">{answer.error}</div>
              ) : answer?.value ? (
                <CoachPanel
                  move={answer.value}
                  userColor={userColor}
                  kicker="Your idea, explained"
                  onShowLine={showLine}
                  onTryAnother={() => setView({ kind: "explore", exploration: stepTo(mine, mine.index - 1) })}
                />
              ) : (
                <div className="card">
                  Thinking about {mine.sans[mine.index - 1]}… You can keep playing: the explanation follows the board.
                </div>
              )
            ) : current ? (
              <CoachPanel
                move={current}
                userColor={userColor}
                onShowLine={showLine}
                drillHref={drills.has(current.ply) ? `#/drills/${drills.get(current.ply)}` : undefined}
                onTryAnother={() => setView({ kind: "explore", exploration: exploreGame(fens, gameUci, current.ply - 1) })}
              />
            ) : (
              <GameSummary review={review} onSelect={goto} />
            )}
          </div>
          <div className="row">
            <button className="ghost" onClick={() => goto(0)}>Game summary</button>
            {game?.url && (
              <a className="small" href={game.url} target="_blank" rel="noreferrer">
                Open on {game.source === "lichess" ? "lichess" : game.source === "chesscom" ? "chess.com" : "the web"}
              </a>
            )}
          </div>
          <MoveList moves={moves} ply={ply} onSelect={goto} />
        </div>
      </div>
    </BoardLinkContext.Provider>
  );
}
