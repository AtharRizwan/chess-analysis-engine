import { numberedMoves } from "../lib/chess";

type Props = {
  fen: string; // where the line starts
  sans: string[];
  index: number; // how many of the moves the board has played
  onSelect: (index: number) => void;
};

/** The moves of a line under the board: click one to put the board there. */
export function LineMoves({ fen, sans, index, onSelect }: Props) {
  return (
    <div className="line-moves">
      {numberedMoves(fen, sans).map((label, i) => (
        <button
          key={i}
          type="button"
          className={i + 1 === index ? "current" : i >= index ? "ahead" : undefined}
          aria-current={i + 1 === index ? "step" : undefined}
          onClick={() => onSelect(i + 1)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
