import type { components } from "./schema";

type S = components["schemas"];
export type GameReview = S["GameReview"];
export type MoveReview = S["MoveReview"];
export type GameSummary = S["GameSummary"];
export type Settings = S["Settings"];
export type JobStatus = S["JobStatus"];
export type Fact = S["Fact"];
export type LineRef = S["LineRef"];
export type Annotation = S["Annotation"];
export type Health = S["Health"];
export type ImportResult = S["ImportResult"];
export type DrillCard = S["DrillCard"];
export type DrillStats = S["DrillStats"];
export type AttemptResult = S["AttemptResult"];
export type Insights = S["Insights"];
export type Cause = S["Cause"];
export type CoachStatus = S["CoachStatus"];
export type Narration = S["Narration"];
export type Explanation = S["Explanation"];
export type Classification = MoveReview["classification"];
export type Side = "white" | "black";

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // keep the status text
    }
    throw new ApiError(detail || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
const put = (body: unknown): RequestInit => ({ method: "PUT", body: JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/api/health"),
  settings: () => request<Settings>("/api/settings"),
  saveSettings: (settings: Settings) => request<Settings>("/api/settings", put(settings)),
  games: () => request<GameSummary[]>("/api/games"),
  game: (id: number) => request<GameSummary>(`/api/games/${id}`),
  importPgn: (pgn: string, userColor: Side | null) =>
    request<ImportResult>("/api/import/pgn", post({ pgn, user_color: userColor })),
  importAccount: (source: "chesscom" | "lichess", username: string, maxGames = 20) =>
    request<ImportResult>(`/api/import/${source}`, post({ username, max_games: maxGames })),
  setSide: (id: number, color: Side | null) =>
    request<GameSummary>(`/api/games/${id}/side`, put({ user_color: color })),
  startReview: (id: number, preset?: Settings["preset"]) =>
    request<JobStatus>(`/api/games/${id}/review`, post({ preset: preset ?? null })),
  activeJob: (id: number) => request<JobStatus | null>(`/api/games/${id}/job`),
  review: (id: number) => request<GameReview>(`/api/games/${id}/review`),
  explain: (body: { fen: string; moves: string[]; move: string; user_color: Side | null }) =>
    request<MoveReview>("/api/explain", post(body)),
  drillStats: () => request<DrillStats>("/api/drills/stats"),
  dueDrills: (theme?: string) =>
    request<DrillCard[]>(`/api/drills/due${theme ? `?theme=${encodeURIComponent(theme)}` : ""}`),
  drill: (id: number) => request<DrillCard>(`/api/drills/${id}`),
  gameDrills: (gameId: number) => request<DrillCard[]>(`/api/games/${gameId}/drills`),
  attemptDrill: (id: number, move: string) => request<AttemptResult>(`/api/drills/${id}/attempt`, post({ move })),
  revealDrill: (id: number) => request<MoveReview>(`/api/drills/${id}/reveal`, post({})),
  insights: () => request<Insights>("/api/insights"),
  coachStatus: () => request<CoachStatus>("/api/coach/status"),
  narrate: (move: MoveReview, userColor: Side | null, refresh = false) =>
    request<Narration>("/api/coach/narrate", post({ move, user_color: userColor, refresh })),
};

/** Follow a review job's progress (server-sent events). Returns a function that stops listening. */
export function watchJob(jobId: string, onUpdate: (job: JobStatus) => void): () => void {
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  source.onmessage = (event) => {
    const job = JSON.parse(event.data) as JobStatus;
    onUpdate(job);
    if (job.status === "done" || job.status === "error") source.close();
  };
  source.onerror = () => source.close();
  return () => source.close();
}
