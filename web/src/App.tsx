import { useEffect, useState } from "react";
import { api, type Health } from "./api/client";
import { DrillsPage } from "./pages/DrillsPage";
import { GamesPage } from "./pages/GamesPage";
import { InsightsPage } from "./pages/InsightsPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SettingsPage } from "./pages/SettingsPage";

type Route =
  | { page: "games" }
  | { page: "review"; id: number; ply?: number }
  | { page: "drills"; theme?: string }
  | { page: "insights" }
  | { page: "settings" };

function parse(hash: string): Route {
  const [path, query] = hash.replace(/^#\/?/, "").split("?");
  const parts = path.split("/");
  if (parts[0] === "review" && Number(parts[1])) {
    return { page: "review", id: Number(parts[1]), ply: Number(parts[2]) || undefined };
  }
  if (parts[0] === "drills") return { page: "drills", theme: new URLSearchParams(query).get("theme") ?? undefined };
  if (parts[0] === "insights") return { page: "insights" };
  if (parts[0] === "settings") return { page: "settings" };
  return { page: "games" };
}

function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function App() {
  const route = useRoute();
  const [health, setHealth] = useState<Health | null>(null);
  const [due, setDue] = useState(0);
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);
  useEffect(() => {
    api.drillStats().then((s) => setDue(s.due)).catch(() => setDue(0));
  }, [route]);

  const link = (href: string, label: string, active: boolean) => (
    <a href={href} className={active ? "active" : undefined}>
      {label}
    </a>
  );

  return (
    <>
      <header className="topbar">
        <a className="brand" href="#/">
          <span aria-hidden>♞</span> Chess Analysis
        </a>
        <nav>
          {link("#/", "Games", route.page === "games" || route.page === "review")}
          {link("#/drills", due ? `Drills (${due})` : "Drills", route.page === "drills")}
          {link("#/insights", "Insights", route.page === "insights")}
          {link("#/settings", "Settings", route.page === "settings")}
        </nav>
        <span className="spacer" />
        <span className="engine">
          {health ? (health.engine ? `${health.engine} · ${health.engines} engines` : "Stockfish not found") : ""}
        </span>
      </header>
      <main className="page">
        {route.page === "games" && <GamesPage />}
        {route.page === "review" && <ReviewPage key={route.id} gameId={route.id} initialPly={route.ply} />}
        {route.page === "drills" && <DrillsPage key={route.theme ?? ""} theme={route.theme} />}
        {route.page === "insights" && <InsightsPage />}
        {route.page === "settings" && <SettingsPage />}
      </main>
    </>
  );
}
