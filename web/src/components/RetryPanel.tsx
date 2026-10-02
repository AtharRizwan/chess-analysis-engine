import type { MoveReview } from "../api/client";

export type RetryFeedback = { kind: "checking"; san: string } | { kind: "wrong"; attempt: MoveReview } | null;

type Props = {
  title: string;
  prompt: string;
  hints: string[];
  hintsShown: number;
  attempts: number;
  feedback: RetryFeedback;
  error?: string | null;
  onHint: () => void;
  onReveal: () => void;
};

/** "Find a better move": progressive hints, feedback on each try, and a way out. */
export function RetryPanel({ title, prompt, hints, hintsShown, attempts, feedback, error, onHint, onReveal }: Props) {
  return (
    <div className="card coach">
      <div className="muted small">Your turn</div>
      <h2>{title}</h2>
      <p>{prompt}</p>
      {feedback?.kind === "checking" && <p className="muted">Checking {feedback.san}…</p>}
      {feedback?.kind === "wrong" && (
        <div className="lesson" style={{ borderLeftColor: "var(--serious)" }}>
          <strong>
            {feedback.attempt.san} isn't it{feedback.attempt.explanation ? ` — ${feedback.attempt.explanation.headline.toLowerCase()}` : ""}.
          </strong>{" "}
          {feedback.attempt.explanation?.sections?.[0]?.text}
          <div className="muted small" style={{ marginTop: 4 }}>
            Try another move on the board.
          </div>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {hints.slice(0, hintsShown).map((hint, i) => (
        <p key={i}>
          <strong>Hint {i + 1}:</strong> {hint}
        </p>
      ))}
      <div className="row actions">
        {hintsShown < hints.length && <button onClick={onHint}>{hintsShown ? "Another hint" : "Give me a hint"}</button>}
        <button className="ghost" onClick={onReveal}>
          Show me the answer
        </button>
        {attempts > 0 && <span className="muted small">{attempts} {attempts === 1 ? "try" : "tries"}</span>}
      </div>
    </div>
  );
}
