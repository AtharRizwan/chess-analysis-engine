import type { Key } from "@lichess-org/chessground/types";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type Annotation,
  api,
  type GameReview,
  type GameSummary as GameRow,
  type JobStatus,
  type LineRef,
  type MoveReview,
  type Side,
  watchJob,
} from "../api/client";
import { Board } from "../components/Board";
import { type BoardLink, BoardLinkContext, useBoardPreview } from "../components/ChessText";
import { CoachPanel } from "../components/CoachPanel";
import { EvalBar } from "../components/EvalBar";
import { EvalGraph } from "../components/EvalGraph";
import { GameSummary } from "../components/GameSummary";
import { MoveList } from "../components/MoveList";
import { numberLine, play, positionsAlong, squaresOf, uciFromDrag } from "../lib/chess";

type View =
  | { kind: "game" }
  | { kind: "line"; line: LineRef; index: number; title: string }
  | {
      kind: "explore";
      basePly: number;
      moves: string[];
      sans: string[];
      result: MoveReview | null;
      loading: boolean;
      error: string | null;
    };

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
  const userColor: Side | null = review?.user_color ?? null;
  const baseOrientation: Side = userColor ?? "white";
  const orientation: Side = flipped ? (baseOrientation === "white" ? "black" : "white") : baseOrientation;

  const linePositions = useMemo(
    () => (view.kind === "line" ? positionsAlong(view.line.start_fen, view.line.uci) : []),
    [view],
  );
  const explorePositions = useMemo(
    () => (view.kind === "explore" && fens.length ? positionsAlong(fens[view.basePly], view.moves) : []),
    [view, fens],
  );

  const explore = useCallback(
    (basePly: number, previous: string[], previousSans: string[], uci: string) => {
      if (!review) return;
      const from = positionsAlong(fens[basePly], previous).at(-1)!;
      const san = play(from, uci).san;
      const nextMoves = [...previous, uci];
      const nextSans = [...previousSans, san];
      setView({ kind: "explore", basePly, moves: nextMoves, sans: nextSans, result: null, loading: true, error: null });
      api
        .explain({
          fen: review.start_fen,
          moves: [...moves.slice(0, basePly).map((m) => m.uci), ...previous],
          move: uci,
          user_color: userColor,
        })
        .then((result) =>
          setView((v) => (v.kind === "explore" && v.moves.length === nextMoves.length ? { ...v, result, loading: false } : v)),
        )
        .catch((e: unknown) =>
          setView((v) =>
            v.kind === "explore" ? { ...v, loading: false, error: e instanceof Error ? e.message : String(e) } : v,
          ),
        );
    },
    [review, fens, moves, userColor],
  );

  const current = ply ? moves[ply - 1] : null;

  const onBoardMove = (orig: Key, dest: Key) => {
    if (view.kind === "game") {
      explore(ply, [], [], uciFromDrag(fens[ply], orig, dest));
    } else if (view.kind === "explore") {
      explore(view.basePly, view.moves, view.sans, uciFromDrag(explorePositions.at(-1)!, orig, dest));
    }
  };

  const goto = useCallback((target: number) => {
    setView({ kind: "game" });
    setPly(Math.max(0, Math.min(moves.length, target)));
  }, [moves.length]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.closest("input, textarea, select")) return;
      if (event.key === "Escape") setView({ kind: "game" });
      else if (event.key === "f") setFlipped((f) => !f);
      else if (view.kind === "line" && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
        const delta = event.key === "ArrowLeft" ? -1 : 1;
        setView({ ...view, index: Math.max(0, Math.min(view.line.uci.length, view.index + delta)) });
      } else if (view.kind === "game") {
        if (event.key === "ArrowLeft") goto(ply - 1);
        else if (event.key === "ArrowRight") goto(ply + 1);
        else if (event.key === "Home") goto(0);
        else if (event.key === "End") goto(moves.length);
        else return;
      } else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, ply, moves.length, goto]);

  // Moves mentioned in the explanations: hover shows one on the board, click steps into its line.
  const viewKey = `${ply}:${view.kind}:${view.kind === "line" ? view.index : ""}:${view.kind === "explore" ? view.moves.length : ""}`;
  const { preview, active, show, clear } = useBoardPreview(viewKey);
  const gameLine = useMemo(
    () => (review ? { start_fen: review.start_fen, uci: moves.map((m) => m.uci), san: moves.map((m) => m.san) } : null),
    [review, moves],
  );
  const boardLink = useMemo<BoardLink>(
    () => ({
      preview: show,
      active,
      game: gameLine,
      open: (ref) => {
        clear();
        if (ref.game) goto(ref.index + 1);
        else setView({ kind: "line", line: ref.line, index: ref.index + 1, title: `From the explanation: ${ref.label}` });
      },
    }),
    [show, active, gameLine, clear, goto],
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
  let whiteWin = ply ? moves[ply - 1].win_after : moves[0]?.win_before ?? 50;
  let score = ply ? moves[ply - 1].eval_after : moves[0]?.eval_before ?? null;
  let interactive = true;
  if (view.kind === "line") {
    fen = linePositions[view.index];
    lastMove = view.index ? squaresOf(view.line.uci[view.index - 1]) : undefined;
    const next = view.line.uci[view.index];
    annotations = next ? [{ orig: next.slice(0, 2), dest: next.slice(2, 4), brush: "blue" }] : [];
    interactive = false;
  } else if (view.kind === "explore") {
    fen = explorePositions.at(-1)!;
    lastMove = view.moves.length ? squaresOf(view.moves.at(-1)!) : view.basePly ? squaresOf(moves[view.basePly - 1].uci) : undefined;
    annotations = view.result ? notGreen(view.result.explanation?.annotations) : [];
    interactive = !view.loading;
    if (view.result) {
      whiteWin = view.result.win_after;
      score = view.result.eval_after;
    }
  }

  if (preview) {
    // A move hovered (or tapped) in the explanation: its position, with the move as an arrow.
    fen = preview.fen;
    lastMove = undefined;
    annotations = [{ orig: preview.uci.slice(0, 2), dest: preview.uci.slice(2, 4), brush: "blue" }];
    interactive = false;
  }

  const showLine = (line: LineRef, title: string) => setView({ kind: "line", line, index: 0, title });

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
          {view.kind === "game" && (
            <div className="board-controls">
              <button className="ghost" onClick={() => goto(0)} aria-label="Start">⏮</button>
              <button className="ghost" onClick={() => goto(ply - 1)} aria-label="Previous move">◀</button>
              <button className="ghost" onClick={() => goto(ply + 1)} aria-label="Next move">▶</button>
              <button className="ghost" onClick={() => goto(moves.length)} aria-label="End">⏭</button>
              <button className="ghost" onClick={() => setFlipped((f) => !f)} aria-label="Flip board">⇅</button>
            </div>
          )}
          {view.kind === "line" && (
            <div className="mode-banner">
              <div className="grow small">
                <strong>{view.title}</strong>
                <div>{numberLine(view.line.start_fen, view.line.san.slice(0, Math.max(view.index, 1)))}</div>
              </div>
              <button onClick={() => setView({ ...view, index: Math.max(0, view.index - 1) })} disabled={view.index === 0}>◀</button>
              <button
                onClick={() => setView({ ...view, index: Math.min(view.line.uci.length, view.index + 1) })}
                disabled={view.index === view.line.uci.length}
              >
                ▶
              </button>
              <button className="primary" onClick={() => setView({ kind: "game" })}>Back to the game</button>
            </div>
          )}
          {view.kind === "explore" && (
            <div className="mode-banner">
              <div className="grow small">
                <strong>Exploring</strong>
                <div>
                  {view.sans.length
                    ? numberLine(fens[view.basePly], view.sans)
                    : "Drag a piece to try your own move from this position."}
                </div>
              </div>
              <button className="primary" onClick={() => setView({ kind: "game" })}>Back to the game</button>
            </div>
          )}
          <EvalGraph moves={moves} ply={ply} onSelect={goto} />
        </div>

        <div className="side-panel fixed">
          <div className="panel-slot">
            {view.kind === "explore" ? (
              view.loading ? (
                <div className="card">Thinking about {view.sans.at(-1)}…</div>
              ) : view.error ? (
                <div className="card error">{view.error}</div>
              ) : view.result ? (
                <CoachPanel move={view.result} userColor={userColor} kicker="Your idea, explained" onShowLine={showLine} />
              ) : (
                <div className="card">
                  Drag a piece on the board to play the move you were considering. You'll see how the engine
                  rates it and why.
                </div>
              )
            ) : current ? (
              <CoachPanel
                move={current}
                userColor={userColor}
                onShowLine={showLine}
                drillHref={drills.has(current.ply) ? `#/drills/${drills.get(current.ply)}` : undefined}
                onTryAnother={() =>
                  setView({ kind: "explore", basePly: current.ply - 1, moves: [], sans: [], result: null, loading: false, error: null })
                }
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
