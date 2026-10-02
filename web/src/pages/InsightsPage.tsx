import { useEffect, useState } from "react";
import { api, type Insights } from "../api/client";
import { causeLabel, playedAt } from "../lib/format";
import { useWidth } from "../lib/useWidth";

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="card tile">
      <div className="muted small">{label}</div>
      <div className="tile-value">{value}</div>
      {note && <div className="muted small">{note}</div>}
    </div>
  );
}

/** A horizontal bar with its value at the tip (single series, so one color for every bar). */
function Bar({ value, max, label }: { value: number; max: number; label: string }) {
  const width = max > 0 ? Math.max(2, (100 * value) / max) : 0;
  return (
    <div className="bar-row" title={label}>
      <div className="bar-track">
        <div className="bar" style={{ width: `${width}%` }} />
        <span className="bar-value">{label}</span>
      </div>
    </div>
  );
}

function Trend({ points }: { points: NonNullable<Insights["trend"]> }) {
  const [box, width] = useWidth<HTMLDivElement>();
  const values = points.filter((p) => p.accuracy !== null && p.accuracy !== undefined);
  if (values.length < 3) return null;
  const height = 140;
  const left = 32;
  const x = (i: number) => left + (i / (values.length - 1)) * (width - left - 12);
  const y = (a: number) => 10 + ((100 - a) / 100) * (height - 30);
  const path = values.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.accuracy!)}`).join(" ");
  return (
    <div className="card">
      <h3>Accuracy over time</h3>
      <div ref={box}>
        <svg width={width} height={height} role="img" aria-label="Your accuracy per game, oldest first">
          {[0, 50, 100].map((tick) => (
            <g key={tick}>
              <line x1={left} x2={width - 12} y1={y(tick)} y2={y(tick)} stroke="var(--grid)" strokeWidth={1} />
              <text x={left - 8} y={y(tick) + 4} fontSize={11} fill="var(--muted)" textAnchor="end">
                {tick}
              </text>
            </g>
          ))}
          <path d={path} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" />
          {values.map((p, i) => (
            <a key={p.game_id} href={`#/review/${p.game_id}`}>
              <circle cx={x(i)} cy={y(p.accuracy!)} r={4.5} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2}>
                <title>{`${Math.round(p.accuracy!)}% · ${playedAt(p.played_at)} · ${p.result ?? ""}`}</title>
              </circle>
            </a>
          ))}
        </svg>
      </div>
    </div>
  );
}

export function InsightsPage() {
  const [data, setData] = useState<Insights | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.insights().then(setData).catch((e) => setError(String(e.message ?? e)));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  if (!data.games) {
    return (
      <div className="card">
        <h2>Insights</h2>
        <p className="muted">
          Review a few of your games (and make sure your side is known — set your usernames in Settings) to see
          which mistakes keep costing you points.
        </p>
        <a href="#/">Go to your games</a>
      </div>
    );
  }
  const causes = data.causes ?? [];
  const maxLoss = Math.max(...causes.map((c) => c.points_lost), 0);
  return (
    <div className="stack">
      <div className="tiles">
        <Tile label="Games reviewed" value={String(data.games)} />
        <Tile label="Average accuracy" value={data.accuracy !== null && data.accuracy !== undefined ? `${data.accuracy}%` : "–"} />
        <Tile label="Blunders per game" value={String(data.blunders_per_game ?? "–")} />
        <Tile label="Mistakes per game" value={String(data.mistakes_per_game ?? "–")} />
        {data.serious_with_clock > 0 && (
          <Tile
            label="Played in under 5 s"
            value={`${data.fast_mistakes} of ${data.serious_with_clock}`}
            note="of your mistakes and blunders"
          />
        )}
      </div>

      <div className="card">
        <h3>What keeps costing you points</h3>
        <p className="muted small" style={{ marginTop: -6 }}>
          Grouped by the main reason behind each inaccuracy, mistake or blunder. Bar length is the winning
          chances lost in total (1 point = a whole game).
        </p>
        <div className="causes">
          {causes.map((c) => {
            const theme = c.motif ?? c.cause;
            return (
              <div key={`${c.cause}-${c.motif}`} className="cause">
                <div className="cause-head">
                  <strong>{causeLabel(c.cause, c.motif)}</strong>
                  <span className="muted small">
                    {c.count} {c.count === 1 ? "time" : "times"}
                  </span>
                </div>
                <Bar value={c.points_lost} max={maxLoss} label={`${c.points_lost.toFixed(2)} pts`} />
                {c.lesson && <p className="small">{c.lesson}</p>}
                <div className="row small">
                  {(c.examples ?? []).slice(0, 4).map((e) => (
                    <a key={`${e.game_id}-${e.ply}`} href={`#/review/${e.game_id}/${e.ply}`}>
                      vs {e.opponent ?? "?"}, move {Math.ceil(e.ply / 2)}
                    </a>
                  ))}
                  <a href={`#/drills?theme=${encodeURIComponent(theme)}`}>Drill these →</a>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="card">
        <h3>Accuracy by phase</h3>
        {(data.phases ?? []).map((p) => (
          <div key={p.phase} className="phase-row">
            <span className="phase-label">
              {p.phase[0].toUpperCase() + p.phase.slice(1)} <span className="muted small">({p.moves} moves)</span>
            </span>
            <Bar value={p.accuracy ?? 0} max={100} label={p.accuracy !== null && p.accuracy !== undefined ? `${p.accuracy}%` : "–"} />
          </div>
        ))}
      </div>

      <Trend points={data.trend ?? []} />
    </div>
  );
}
