import { useEffect, useState } from "react";
import { api, type CoachStatus, type MoveReview, type Narration, type Side } from "../api/client";

// One status request per page load (Settings refreshes it after a save).
let statusRequest: Promise<CoachStatus | null> | null = null;
const listeners = new Set<(status: CoachStatus | null) => void>();

export function refreshCoachStatus(): Promise<CoachStatus | null> {
  statusRequest = api.coachStatus().catch(() => null);
  statusRequest.then((status) => listeners.forEach((listener) => listener(status)));
  return statusRequest;
}

export function useCoachStatus(): CoachStatus | null {
  const [status, setStatus] = useState<CoachStatus | null>(null);
  useEffect(() => {
    listeners.add(setStatus);
    (statusRequest ?? refreshCoachStatus()).then(setStatus);
    return () => {
      listeners.delete(setStatus);
    };
  }, []);
  return status;
}

// "Coach voice" on or off is a per-browser preference; it works without storage too.
const VOICE_KEY = "coach-voice";
const voiceListeners = new Set<(on: boolean) => void>();

function readVoice(): boolean {
  try {
    return localStorage.getItem(VOICE_KEY) === "on";
  } catch {
    return false;
  }
}

let voice = readVoice();

export function useCoachVoice(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(voice);
  useEffect(() => {
    voiceListeners.add(setOn);
    return () => {
      voiceListeners.delete(setOn);
    };
  }, []);
  const set = (value: boolean) => {
    voice = value;
    try {
      localStorage.setItem(VOICE_KEY, value ? "on" : "off");
    } catch {
      // not remembered across visits; fine
    }
    voiceListeners.forEach((listener) => listener(value));
  };
  return [on, set];
}

// Narrations already asked for in this page load (the server caches them across visits).
const narrations = new Map<string, Promise<Narration>>();

export function narrationKey(move: MoveReview, userColor: Side | null): string {
  return `${move.fen_before}|${move.uci}|${userColor ?? ""}`;
}

/** Whether this move was already asked about in this page load (a failed request doesn't count). */
export function wasNarrated(move: MoveReview, userColor: Side | null): boolean {
  return narrations.has(narrationKey(move, userColor));
}

export function narrate(move: MoveReview, userColor: Side | null, refresh = false): Promise<Narration> {
  const key = narrationKey(move, userColor);
  let request = refresh ? undefined : narrations.get(key);
  if (!request) {
    request = api.narrate(move, userColor, refresh);
    narrations.set(key, request);
    request.catch(() => narrations.delete(key));
  }
  return request;
}
