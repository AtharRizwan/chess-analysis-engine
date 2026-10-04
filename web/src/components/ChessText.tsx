import { createContext, Fragment, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { LineRef } from "../api/client";
import { linkify, type MoveRef, type NotationIndex } from "../lib/notation";

/** Provided by a page that owns the board: moves in texts preview on it and open lines on it. */
export type BoardLink = {
  /** Show a move on the board (null: back to what was shown). `sticky` previews stay until dismissed. */
  preview: (ref: MoveRef | null, sticky?: boolean) => void;
  /** Step the board into the move's line (or to that move of the game). */
  open: (ref: MoveRef) => void;
  /** The key of the move currently previewed by a tap, if any. */
  active: string | null;
  /** The game up to this point, so explanations can mention earlier moves. */
  game?: LineRef | null;
};

export const BoardLinkContext = createContext<BoardLink | null>(null);

/** Text with every move in it linked to the board: hover (or tap) to see it, click (or tap again) to step in. */
export function ChessText({ text, index }: { text: string; index: NotationIndex | null }) {
  const link = useContext(BoardLinkContext);
  const pointer = useRef("mouse");
  const segments = useMemo(() => (link && index ? linkify(text, index) : [text]), [text, index, link]);
  if (!link) return <>{text}</>;
  return (
    <>
      {segments.map((segment, i) =>
        typeof segment === "string" ? (
          <Fragment key={i}>{segment}</Fragment>
        ) : (
          <button
            key={i}
            type="button"
            className={`mv-ref${link.active === segment.key ? " active" : ""}`}
            title={`${segment.label}: hover to see it on the board, click to step through the line`}
            onPointerDown={(e) => {
              pointer.current = e.pointerType;
            }}
            onPointerEnter={(e) => e.pointerType === "mouse" && link.preview(segment)}
            onPointerLeave={(e) => e.pointerType === "mouse" && link.preview(null)}
            onFocus={() => link.preview(segment)}
            onBlur={() => link.preview(null)}
            onClick={() => {
              // A mouse already previewed on hover; a finger previews on the first tap and opens on the second.
              if (pointer.current === "mouse" || link.active === segment.key) link.open(segment);
              else link.preview(segment, true);
              pointer.current = "mouse";
            }}
          >
            {segment.text}
          </button>
        ),
      )}
    </>
  );
}

type Preview = { ref: MoveRef; sticky: boolean };

/** Preview state for a page's board. `resetKey` changing (a new move or view) clears it. */
export function useBoardPreview(resetKey: unknown) {
  const [preview, setPreview] = useState<Preview | null>(null);
  // Leaving a move waits a moment before showing the game again, so sliding the mouse from one move to
  // the next (across the space between them) goes straight from preview to preview.
  const leaving = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelLeave = () => {
    if (leaving.current) clearTimeout(leaving.current);
    leaving.current = null;
  };
  useEffect(() => cancelLeave, []);
  useEffect(() => {
    cancelLeave();
    setPreview(null);
  }, [resetKey]);
  useEffect(() => {
    // A tapped preview stays until the next tap somewhere other than a move.
    if (!preview?.sticky) return;
    const onDown = (e: PointerEvent) => {
      if (!(e.target instanceof Element && e.target.closest(".mv-ref"))) setPreview(null);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [preview?.sticky]);
  const show = useCallback((ref: MoveRef | null, sticky = false) => {
    cancelLeave();
    if (ref) {
      setPreview({ ref, sticky });
      return;
    }
    leaving.current = setTimeout(() => {
      leaving.current = null;
      setPreview((current) => (current?.sticky ? current : null)); // leaving with the mouse doesn't undo a tap
    }, 150);
  }, []);
  const clear = useCallback(() => {
    cancelLeave();
    setPreview(null);
  }, []);
  return { preview: preview?.ref ?? null, active: preview?.sticky ? preview.ref.key : null, show, clear };
}
