import type { Classification } from "../api/client";
import { LABELS, SYMBOLS } from "../lib/format";

/** Classification as a colored dot plus its name (text stays in ink; the dot carries color). */
export function Badge({ value }: { value: Classification }) {
  const symbol = SYMBOLS[value];
  return (
    <span className="badge">
      <span className={`dot cls-${value}`} aria-hidden />
      {LABELS[value]}
      {symbol && <span className="muted">{symbol}</span>}
    </span>
  );
}
