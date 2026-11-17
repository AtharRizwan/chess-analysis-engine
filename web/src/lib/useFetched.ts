import { useEffect, useRef, useState } from "react";

export type Fetched<T> = { value?: T; error?: string };

/**
 * Fetch what `key` names, one request at a time: while one runs, only the newest key waits its turn, so
 * playing through moves quickly doesn't queue an engine search for each. Answers (failures too) are kept
 * by key, so coming back to one is instant. Null asks for nothing.
 */
export function useFetched<T>(key: string | null, fetch: () => Promise<T>): ReadonlyMap<string, Fetched<T>> {
  const [answers, setAnswers] = useState<ReadonlyMap<string, Fetched<T>>>(new Map());
  const [busy, setBusy] = useState(false);
  const latestFetch = useRef(fetch); // from the same render as `key` when the effect below reads it
  latestFetch.current = fetch;

  useEffect(() => {
    if (key === null || busy || answers.has(key)) return;
    setBusy(true);
    const settle = (answer: Fetched<T>) => {
      setAnswers((known) => new Map(known).set(key, answer));
      setBusy(false);
    };
    latestFetch.current().then(
      (value) => settle({ value }),
      (e: unknown) => settle({ error: e instanceof Error ? e.message : String(e) }),
    );
  }, [key, busy, answers]);

  return answers;
}
