import { Chessground } from "@lichess-org/chessground";
import type { Api } from "@lichess-org/chessground/api";
import "@lichess-org/chessground/assets/chessground.base.css";
import "@lichess-org/chessground/assets/chessground.brown.css";
import "@lichess-org/chessground/assets/chessground.cburnett.css";
import type { DrawShape } from "@lichess-org/chessground/draw";
import type { Key } from "@lichess-org/chessground/types";
import { useEffect, useRef } from "react";
import type { Annotation, Side } from "../api/client";
import { destsOf, inCheck, turnOf } from "../lib/chess";

type Props = {
  fen: string;
  orientation: Side;
  lastMove?: [Key, Key];
  annotations?: Annotation[];
  /** Let the side to move play a move (the "why not this move?" explorer). */
  interactive?: boolean;
  onMove?: (orig: Key, dest: Key) => void;
  /** A small tag in the corner, e.g. the move being previewed. Overlaid, so the layout doesn't move. */
  label?: string;
};

const BRUSHES: Record<Annotation["brush"] & string, string> = {
  green: "green",
  red: "red",
  blue: "blue",
  yellow: "yellow",
  grey: "paleGrey",
};

export function toShapes(annotations: Annotation[]): DrawShape[] {
  return annotations.map((a) => ({
    orig: a.orig as Key,
    dest: (a.dest ?? undefined) as Key | undefined,
    brush: BRUSHES[a.brush ?? "green"],
  }));
}

/** The chessboard (lichess's chessground), driven entirely by props. */
export function Board({ fen, orientation, lastMove, annotations = [], interactive = false, onMove, label }: Props) {
  const element = useRef<HTMLDivElement>(null);
  const ground = useRef<Api | null>(null);
  const moveHandler = useRef(onMove);
  moveHandler.current = onMove;

  useEffect(() => {
    if (!element.current) return;
    ground.current = Chessground(element.current, {
      animation: { enabled: true, duration: 160 },
      coordinates: true,
      drawable: { enabled: true, visible: true },
      highlight: { lastMove: true, check: true },
    });
    return () => {
      ground.current?.destroy();
      ground.current = null;
    };
  }, []);

  const shapeKey = JSON.stringify(annotations);
  useEffect(() => {
    const turn = turnOf(fen);
    ground.current?.set({
      fen,
      orientation,
      turnColor: turn,
      lastMove,
      check: inCheck(fen) ? turn : false,
      movable: interactive
        ? {
            free: false,
            color: turn,
            dests: destsOf(fen),
            showDests: true,
            events: { after: (orig, dest) => moveHandler.current?.(orig, dest) },
          }
        : { color: undefined, dests: new Map() },
      drawable: { autoShapes: toShapes(annotations) },
    });
    // annotations are compared by value (shapeKey) so a new array with the same content doesn't redraw
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fen, orientation, lastMove?.[0], lastMove?.[1], shapeKey, interactive]);

  return (
    <div className="board-wrap">
      <div ref={element} className="cg-wrap" />
      {label && <div className="board-label">{label}</div>}
    </div>
  );
}
