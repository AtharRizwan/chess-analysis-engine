import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import {
  api,
  type ChatTurn,
  type CoachStatus,
  type Explanation,
  type MoveReview,
  type Narration,
  type Side,
} from "../api/client";

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

// --- follow-up questions ---------------------------------------------------------------------------
// One conversation per move (the server keeps them). Kept here by move, so an answer that arrives after
// you've stepped to another move is waiting when you come back, and never shows up on the wrong move.

type Chat = {
  turns: ChatTurn[];
  limit: number;
  loaded: boolean;
  pending: string | null; // the question waiting for its answer
  error: string | null;
};

const NO_CHAT: Chat = { turns: [], limit: 20, loaded: false, pending: null, error: null };
const chats = new Map<string, Chat>();
const chatListeners = new Set<() => void>();

function setChat(key: string, change: Partial<Chat>) {
  chats.set(key, { ...(chats.get(key) ?? NO_CHAT), ...change });
  chatListeners.forEach((listener) => listener());
}

function subscribeChats(listener: () => void) {
  chatListeners.add(listener);
  return () => {
    chatListeners.delete(listener);
  };
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export type CoachChat = Chat & {
  ask: (question: string, shown: Explanation | null) => void;
  clear: () => void;
};

/** The conversation about `move`: its turns so far, and asking or clearing. Loads only when `enabled`. */
export function useCoachChat(move: MoveReview, userColor: Side | null, enabled: boolean): CoachChat {
  const key = narrationKey(move, userColor);
  const chat = useSyncExternalStore(subscribeChats, () => chats.get(key) ?? NO_CHAT);

  useEffect(() => {
    if (!enabled || chats.has(key)) return;
    setChat(key, {});
    api
      .chatThread(move, userColor)
      .then((view) => setChat(key, { turns: view.turns ?? [], limit: view.limit, loaded: true }))
      .catch((e: unknown) => setChat(key, { loaded: true, error: message(e) }));
    // `move` is identified by `key`
  }, [enabled, key]);

  const ask = useCallback(
    (question: string, shown: Explanation | null) => {
      const text = question.trim();
      if (!text || chats.get(key)?.pending) return;
      setChat(key, { pending: text, error: null });
      api
        .chat(move, userColor, text, shown)
        .then((view) => setChat(key, { turns: view.turns ?? [], limit: view.limit, loaded: true, pending: null }))
        .catch((e: unknown) => setChat(key, { pending: null, error: message(e) }));
    },
    [key],
  );

  const clear = useCallback(() => {
    api
      .chatClear(move, userColor)
      .then((view) => setChat(key, { turns: view.turns ?? [], limit: view.limit, error: null }))
      .catch((e: unknown) => setChat(key, { error: message(e) }));
  }, [key]);

  return { ...chat, ask, clear };
}
