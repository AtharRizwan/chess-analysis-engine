import { useEffect, useState } from "react";
import { api, type CoachStatus, type Settings } from "../api/client";
import { refreshCoachStatus, useCoachStatus } from "../lib/coach";

function CoachState({ status, enabled }: { status: CoachStatus | null; enabled: boolean }) {
  if (!status) return null;
  const calls = status.usage?.reduce((n, u) => n + u.calls, 0) ?? 0;
  const known = status.usage?.every((u) => u.cost_usd !== null && u.cost_usd !== undefined);
  const cost = status.usage?.reduce((n, u) => n + (u.cost_usd ?? 0), 0) ?? 0;
  return (
    <div className="muted small">
      {status.problem
        ? status.problem
        : enabled
          ? "Ready. Use “✦ Coach voice” on any move."
          : "Anthropic credentials found."}
      {calls > 0 && (
        <>
          {" "}
          · {calls} {calls === 1 ? "call" : "calls"} so far{known ? `, about $${cost.toFixed(2)}` : ""}
        </>
      )}
    </div>
  );
}

export function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const coach = useCoachStatus();

  useEffect(() => {
    api.settings().then(setSettings);
    refreshCoachStatus(); // usage changes as moves are narrated
  }, []);

  if (!settings) return <p className="muted">Loading…</p>;
  const update = (patch: Partial<Settings>) => {
    setSettings({ ...settings, ...patch });
    setStatus(null);
  };
  const save = async () => {
    try {
      setSettings(await api.saveSettings(settings));
      setStatus("Saved.");
      refreshCoachStatus();
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="card stack" style={{ maxWidth: 780 }}>
      <h2>Settings</h2>
      <div className="form-grid">
        <label htmlFor="chesscom">chess.com username</label>
        <input id="chesscom" value={settings.chesscom_username ?? ""} onChange={(e) => update({ chesscom_username: e.target.value })} />
        <label htmlFor="lichess">lichess username</label>
        <input id="lichess" value={settings.lichess_username ?? ""} onChange={(e) => update({ lichess_username: e.target.value })} />
        <label htmlFor="preset">Analysis depth</label>
        <select id="preset" value={settings.preset ?? "standard"} onChange={(e) => update({ preset: e.target.value as Settings["preset"] })}>
          <option value="quick">Quick (depth 14, ~10 s per game)</option>
          <option value="standard">Standard (depth 18, ~30 s per game)</option>
          <option value="deep">Deep (depth 22, a few minutes per game)</option>
        </select>
        <span>Threat detection</span>
        <label className="row">
          <input type="checkbox" checked={settings.threats ?? true} onChange={(e) => update({ threats: e.target.checked })} />
          Explain what your opponent was threatening (extra engine work)
        </label>
        <span>Endgame tablebase</span>
        <label className="row">
          <input type="checkbox" checked={settings.tablebase ?? true} onChange={(e) => update({ tablebase: e.target.checked })} />
          Look up endgames with 7 pieces or fewer on lichess's tablebase
        </label>
        <span>Learn mode</span>
        <label className="row">
          <input type="checkbox" checked={settings.learn_mode ?? true} onChange={(e) => update({ learn_mode: e.target.checked })} />
          Hide the answer on your mistakes until you've tried to find it
        </label>
        <span>Claude coach</span>
        <div className="stack-tight">
          <label className="row">
            <input type="checkbox" checked={settings.coach_enabled ?? false} onChange={(e) => update({ coach_enabled: e.target.checked })} />
            Optionally retell moves in a coach's words with Claude. Every claim is checked against the verified
            facts, and the standard explanation is used if it doesn't match.
          </label>
          <CoachState status={coach} enabled={settings.coach_enabled ?? false} />
        </div>
        <label htmlFor="coach-model">Coach model</label>
        <input id="coach-model" value={settings.coach_model ?? ""} onChange={(e) => update({ coach_model: e.target.value })} />
        <label htmlFor="coach-effort">Coach effort</label>
        <select
          id="coach-effort"
          value={settings.coach_effort ?? "medium"}
          onChange={(e) => update({ coach_effort: e.target.value as Settings["coach_effort"] })}
        >
          <option value="low">Low (fastest, cheapest)</option>
          <option value="medium">Medium (recommended)</option>
          <option value="high">High (most careful)</option>
        </select>
      </div>
      <div className="row">
        <button className="primary" onClick={save}>Save</button>
        {status && <span className="muted">{status}</span>}
      </div>
      <p className="muted small">
        Your usernames are used to recognise your side in imported games. The coach uses your own Anthropic API
        key: start the server with <code>ANTHROPIC_API_KEY</code> set. With the default model a narrated move costs
        a few cents, and each one is cached so it's only paid for once.
      </p>
    </div>
  );
}
