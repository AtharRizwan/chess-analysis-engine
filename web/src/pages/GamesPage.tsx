import { useCallback, useEffect, useState } from "react";
import { api, type GameSummary, type Settings, type Side } from "../api/client";
import { playedAt } from "../lib/format";

type Busy = "chesscom" | "lichess" | "pgn" | "analyze" | null;

function outcome(game: GameSummary): { text: string; tone: "" | "win" | "loss" } {
  const result = game.result ?? "*";
  if (!game.user_color || result === "*" || result === "1/2-1/2") {
    return { text: result === "1/2-1/2" ? "½–½" : result, tone: "" };
  }
  const won = (result === "1-0") === (game.user_color === "white");
  return { text: won ? "Won" : "Lost", tone: won ? "win" : "loss" };
}

function sideLabel(game: GameSummary): string {
  return game.user_color ? (game.user_color === "white" ? "White" : "Black") : "—";
}

export function GamesPage() {
  const [games, setGames] = useState<GameSummary[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [chesscom, setChesscom] = useState("");
  const [lichess, setLichess] = useState("");
  const [count, setCount] = useState(20);
  const [pgn, setPgn] = useState("");
  const [pgnSide, setPgnSide] = useState<Side | "">("");
  const [busy, setBusy] = useState<Busy>(null);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);

  const refresh = useCallback(() => api.games().then(setGames), []);

  useEffect(() => {
    refresh().catch((e) => setMessage({ text: String(e.message ?? e), error: true }));
    api.settings().then((s) => {
      setSettings(s);
      setChesscom(s.chesscom_username ?? "");
      setLichess(s.lichess_username ?? "");
    });
  }, [refresh]);

  // While reviews are running in the background, keep their status fresh.
  const running = games.some((g) => g.review_status === "running" || g.review_status === "queued");
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, [running, refresh]);

  const run = async (kind: Busy, task: () => Promise<string>) => {
    setBusy(kind);
    setMessage(null);
    try {
      setMessage({ text: await task() });
      await refresh();
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : String(e), error: true });
    } finally {
      setBusy(null);
    }
  };

  const importAccount = (source: "chesscom" | "lichess", username: string) =>
    run(source, async () => {
      const result = await api.importAccount(source, username.trim(), count);
      return `Fetched ${result.games.length} games (${result.created} new).`;
    });

  const importPgn = () =>
    run("pgn", async () => {
      const result = await api.importPgn(pgn, pgnSide || null);
      setPgn("");
      return result.created ? `Imported ${result.created} game(s).` : "Already imported.";
    });

  const unreviewed = games.filter((g) => !g.review_status || g.review_status === "error");
  const analyzeAll = () =>
    run("analyze", async () => {
      for (const game of unreviewed) await api.startReview(game.id);
      return `Queued ${unreviewed.length} games — they're analyzed one after another.`;
    });

  return (
    <>
      <div className="import-grid">
        <div className="card stack">
          <h2>chess.com</h2>
          <div className="row">
            <input
              aria-label="chess.com username"
              placeholder="Username"
              value={chesscom}
              onChange={(e) => setChesscom(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && chesscom.trim() && importAccount("chesscom", chesscom)}
            />
            <button className="primary" disabled={!chesscom.trim() || busy !== null} onClick={() => importAccount("chesscom", chesscom)}>
              {busy === "chesscom" ? "Fetching…" : "Fetch games"}
            </button>
          </div>
          <span className="muted small">Your most recent standard games.</span>
        </div>
        <div className="card stack">
          <h2>lichess</h2>
          <div className="row">
            <input
              aria-label="lichess username"
              placeholder="Username"
              value={lichess}
              onChange={(e) => setLichess(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && lichess.trim() && importAccount("lichess", lichess)}
            />
            <button className="primary" disabled={!lichess.trim() || busy !== null} onClick={() => importAccount("lichess", lichess)}>
              {busy === "lichess" ? "Fetching…" : "Fetch games"}
            </button>
          </div>
          <label className="row muted small">
            Games to fetch
            <select value={count} onChange={(e) => setCount(Number(e.target.value))}>
              {[10, 20, 50].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="card stack">
          <h2>Paste a PGN</h2>
          <textarea rows={3} placeholder="[Event …] 1. e4 e5 …" value={pgn} onChange={(e) => setPgn(e.target.value)} />
          <div className="row">
            <select aria-label="Your side" value={pgnSide} onChange={(e) => setPgnSide(e.target.value as Side | "")}>
              <option value="">I played… (auto)</option>
              <option value="white">I played White</option>
              <option value="black">I played Black</option>
            </select>
            <button className="primary" disabled={!pgn.trim() || busy !== null} onClick={importPgn}>
              {busy === "pgn" ? "Importing…" : "Import"}
            </button>
          </div>
        </div>
      </div>

      {message && <p className={message.error ? "error" : "muted"}>{message.text}</p>}

      <div className="card">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
          <h2 style={{ margin: 0 }}>Your games</h2>
          {unreviewed.length > 1 && (
            <button disabled={busy !== null} onClick={analyzeAll}>
              Analyze all {unreviewed.length} unreviewed
            </button>
          )}
        </div>
        {games.length === 0 ? (
          <p className="muted">
            No games yet. Fetch your recent games above{settings?.chesscom_username ? "" : " or paste a PGN"}.
          </p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="games-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Players</th>
                  <th>Result</th>
                  <th>You</th>
                  <th>Type</th>
                  <th>Review</th>
                </tr>
              </thead>
              <tbody>
                {games.map((game) => {
                  const result = outcome(game);
                  return (
                    <tr key={game.id}>
                      <td className="small muted">{playedAt(game.played_at)}</td>
                      <td>
                        {game.white}
                        {game.white_rating ? <span className="muted"> ({game.white_rating})</span> : null} vs {game.black}
                        {game.black_rating ? <span className="muted"> ({game.black_rating})</span> : null}
                      </td>
                      <td>
                        <span className={`result-pill ${result.tone}`}>{result.text}</span>
                      </td>
                      <td className="small">{sideLabel(game)}</td>
                      <td className="small muted">{game.time_class ?? game.time_control ?? ""}</td>
                      <td>
                        {game.review_status === "done" ? (
                          <a href={`#/review/${game.id}`}>Open review</a>
                        ) : game.review_status === "running" || game.review_status === "queued" ? (
                          <a href={`#/review/${game.id}`} className="muted">
                            {game.review_status === "running" ? "Analyzing…" : "Queued"}
                          </a>
                        ) : (
                          <a href={`#/review/${game.id}`}>{game.review_status === "error" ? "Retry review" : "Review"}</a>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
