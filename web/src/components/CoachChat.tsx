import { useState } from "react";
import type { LineRef, MoveReview, Side } from "../api/client";
import { moveLabel } from "../lib/chess";
import type { CoachChat } from "../lib/coach";
import { BAD } from "../lib/format";
import type { NotationIndex } from "../lib/notation";
import { ChessText } from "./ChessText";

// Moves written in a question (piece moves, captures, castling), to say what the engine is checking.
const NAMED_MOVE =
  /(?<![A-Za-z0-9])(?:\d+\s*\.+\s*)?(?:O-O-O|O-O|[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?|[a-h]x[a-h][1-8](?:=[QRBN])?)[+#]?(?![A-Za-z0-9])/g;

function lineLabel(line: LineRef): string {
  const [, turn, , , , full] = line.start_fen.split(" ");
  return moveLabel(Number(full) || 1, turn === "w" ? "white" : "black", line.san[0] ?? "");
}

function waiting(question: string): string {
  const named = [...question.matchAll(NAMED_MOVE)].map((m) => m[0]).slice(0, 2);
  const checking = named.length ? `Checking ${named.join(" and ")} with the engine. ` : "";
  return `${checking}The coach is thinking… this can take a little while.`;
}

/** Questions that fit the move, for an empty conversation. */
export function suggestions(move: MoveReview, userColor: Side | null): string[] {
  if (!BAD.has(move.classification)) {
    return ["Why is this move good?", "What's the idea behind it?", "What should come next?"];
  }
  if (userColor && move.color !== userColor) {
    return ["Why is this move bad?", "How do I punish it?", "What should my opponent have played?"];
  }
  return ["Why exactly is this move bad?", "Why is the engine's move better?", "How do I spot this next time?"];
}

type ThreadProps = {
  chat: CoachChat;
  index: NotationIndex | null;
  onShowLine: (line: LineRef, title: string) => void;
  onRetry: (question: string) => void;
};

/** The questions asked about a move so far, each with the coach's answer and the lines it checked. */
export function ChatThreadView({ chat, index, onShowLine, onRetry }: ThreadProps) {
  if (!chat.turns.length && !chat.pending && !chat.error) return null;
  const last = chat.turns.length - 1;
  return (
    <div className="chat" aria-live="polite">
      <h4>
        Your questions
        <span className="ai-tag" title="Answered by Claude from the verified analysis, and checked against it">
          ✦ AI
        </span>
      </h4>
      {chat.turns.map((turn, i) => (
        <div key={i} className="chat-turn">
          <div className="chat-q">{turn.question}</div>
          {turn.verified ? (
            <div className="chat-a">
              <ChessText text={turn.answer} index={index} />
            </div>
          ) : (
            <div className="chat-a muted small">
              ✦ {turn.answer}{" "}
              {i === last && (
                <button className="linkish small" disabled={Boolean(chat.pending)} onClick={() => onRetry(turn.question)}>
                  Ask again
                </button>
              )}
              {(turn.problems ?? []).length > 0 && (
                <details>
                  <summary>What didn't match</summary>
                  <ul>
                    {(turn.problems ?? []).map((problem) => (
                      <li key={problem}>{problem}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
          {(turn.notes ?? []).map((note) => (
            <div key={note} className="muted small">
              Engine: {note}.
            </div>
          ))}
          {(turn.lines ?? []).map((line, j) => {
            const label = turn.labels?.[j] ?? lineLabel(line);
            return (
              <button key={j} className="linkish" onClick={() => onShowLine(line, `Checked by the engine: ${label}`)}>
                ▶ Show {label} on the board
              </button>
            );
          })}
        </div>
      ))}
      {chat.pending && (
        <div className="chat-turn">
          <div className="chat-q">{chat.pending}</div>
          <div className="chat-a muted small">✦ {waiting(chat.pending)}</div>
        </div>
      )}
      {chat.error && <div className="muted small">✦ The coach is unavailable: {chat.error}</div>}
    </div>
  );
}

type ComposerProps = {
  chat: CoachChat;
  /** Identifies the move: a half-written question stays with its move. */
  chatKey: string;
  suggestions: string[];
  onAsk: (question: string) => void;
};

/** Where you type a question about the move; stays in place under the explanation. */
export function ChatComposer({ chat, chatKey, suggestions: ideas, onAsk }: ComposerProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const draft = drafts[chatKey] ?? "";
  const setDraft = (text: string) => setDrafts((all) => ({ ...all, [chatKey]: text }));
  const full = chat.turns.length >= chat.limit;
  const busy = Boolean(chat.pending);

  const send = (question: string) => {
    if (!question.trim() || busy || full) return;
    onAsk(question);
    setDraft("");
  };

  return (
    <div className="composer">
      {chat.loaded && !chat.turns.length && !busy && (
        <div className="chips">
          {ideas.map((idea) => (
            <button key={idea} className="chip suggestion" onClick={() => send(idea)}>
              {idea}
            </button>
          ))}
        </div>
      )}
      <div className="composer-row">
        <textarea
          rows={1}
          value={draft}
          maxLength={500}
          disabled={full}
          aria-label="Ask the coach a question about this move"
          title="Moves you name (like Nxe5) are checked by the engine before the coach answers."
          placeholder={full ? "That's all the questions for this move: clear the conversation to ask more." : "Ask a question about this move…"}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send(draft);
            }
          }}
        />
        <button className="primary" disabled={!draft.trim() || busy || full} onClick={() => send(draft)}>
          Ask
        </button>
      </div>
      {chat.turns.length > 0 && (
        <button className="linkish small clear" disabled={busy} onClick={chat.clear}>
          Clear conversation
        </button>
      )}
    </div>
  );
}
