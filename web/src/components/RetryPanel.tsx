import type { MoveReview } from "../api/client";

export type RetryFeedback =
  | { kind: "checking"; san: string }
  | { kind: "wrong" | "close"; san: string; attempt: MoveReview | null }
  | null;

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
  /** Take the tried move back and look again. */
  onTryAgain: () => void;
};

const sentence = (text: string) => (/[.!?…]$/.test(text) ? text : `${text}.`);

/** "Find a better move": progressive hints, feedback on each try, and a way out. */
export function RetryPanel(props: Props) {
  const { title, prompt, hints, hintsShown, attempts, feedback, error, onHint, onReveal, onTryAgain } = props;
  const explanation = feedback && feedback.kind !== "checking" ? feedback.attempt?.explanation : undefined;
  return (
    <div className="card coach">
      <div className="muted small">Your turn</div>
      <h2>{title}</h2>
      <p>{prompt}</p>
      {/* The buttons come before anything that appears or disappears, and never change place. */}
      <div className="row actions">
        <button className="hint-button" disabled={hintsShown >= hints.length} onClick={onHint}>
          {hintsShown >= hints.length ? (hints.length ? "No more hints" : "No hints") : hintsShown ? "Another hint" : "Give me a hint"}
        </button>
        <button className="ghost" onClick={onReveal}>
          Show me the answer
        </button>
        {attempts > 0 && <span className="muted small">{attempts} {attempts === 1 ? "try" : "tries"}</span>}
      </div>
      <div className="retry-feedback">
        {feedback?.kind === "checking" && <p className="muted">Checking {feedback.san}…</p>}
        {feedback?.kind === "wrong" && (
          <div className="lesson" style={{ borderLeftColor: "var(--serious)" }}>
            <strong>{feedback.san} isn't it.</strong> {explanation && sentence(explanation.headline)}{" "}
            {explanation?.sections?.[0]?.text}
            {feedback.attempt?.refutation?.san?.[0] && (
              <div className="muted small" style={{ marginTop: 4 }}>
                The red arrow shows the reply that makes it fail.
              </div>
            )}
            <div>
              <button className="primary" style={{ marginTop: 10 }} onClick={onTryAgain}>
                Try again
              </button>
            </div>
          </div>
        )}
        {feedback?.kind === "close" && (
          <div className="lesson">
            <strong>{feedback.san} is a good move</strong>, but there's a stronger one here. Keep looking.
            <div>
              <button className="primary" style={{ marginTop: 10 }} onClick={onTryAgain}>
                Try again
              </button>
            </div>
          </div>
        )}
        {error && <p className="error">{error}</p>}
      </div>
      {hints.slice(0, hintsShown).map((hint, i) => (
        <p key={i}>
          <strong>Hint {i + 1}:</strong> {hint}
        </p>
      ))}
    </div>
  );
}
