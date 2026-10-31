"""Short, reusable lessons: the habit that would have prevented (or found) the move."""

from __future__ import annotations

LESSONS: dict[tuple[str, str | None], str] = {
    ("allows_mate", "back_rank_mate"): (
        "Watch your back rank: when your king has no escape squares, a rook or queen check on the "
        'first rank can be mate. A quiet pawn move like h3 ("luft") removes the danger.'
    ),
    ("allows_mate", "smothered_mate"): (
        "A king surrounded by its own pieces can be mated by a single knight. Keep an escape square, "
        "and watch knight checks near your king."
    ),
    ("allows_mate", None): (
        "Before every move, look at all of your opponent's checks. Checks are the most forcing moves, "
        "and that is where mates hide."
    ),
    ("ignored_threat", None): (
        "After every move your opponent makes, ask: what does it threaten? Look at the checks, captures "
        "and attacks it creates before you think about your own plans."
    ),
    ("hangs_piece", "moved_into_attack"): (
        "Before letting go of a piece, check its new square: who attacks it, and who defends it?"
    ),
    ("hangs_piece", "removed_defender"): (
        "Pieces have jobs. Before moving one, check what it was protecting — if it was the only "
        "defender, that piece is now loose."
    ),
    ("hangs_piece", None): (
        "Loose pieces drop off. Do a quick blunder check every move: is everything of mine defended, "
        "and is anything attacked more times than it is defended?"
    ),
    ("allows_tactic", "fork"): (
        "Forks happen on squares you don't control. Look for squares where an enemy piece could attack "
        "two of yours at once — king and queen, or queen and rook, are the classic targets."
    ),
    ("allows_tactic", "pin"): (
        "Avoid lining up your king or queen behind another piece on a line an enemy bishop, rook or "
        "queen can reach — the piece in front gets pinned."
    ),
    ("allows_tactic", "skewer"): (
        "Keep your king and queen off open lines where something less valuable stands behind them: "
        "a check or attack on the front piece wins the one behind."
    ),
    ("allows_tactic", "discovered_attack"): (
        "When an enemy piece stands in front of their own bishop, rook or queen, expect it to move "
        "with a threat — the piece behind it attacks at the same moment."
    ),
    ("allows_tactic", "discovered_check"): (
        "When an enemy piece stands between your king and their bishop, rook or queen, any move it "
        "makes gives check — and it can grab something on the way."
    ),
    ("allows_tactic", "double_check"): (
        "Against a double check only a king move helps. Keep your king away from lines that two enemy "
        "pieces can open at once."
    ),
    ("allows_tactic", "removal_of_defender"): (
        "Count your defenders. If a piece has only one, your opponent can capture or chase that "
        "defender away and win it."
    ),
    ("allows_tactic", "trapped_piece"): (
        "Before sending a piece deep into enemy territory, check that it has a way back."
    ),
    ("allows_tactic", "promotion"): (
        "Passed pawns must be stopped early — blockade the square in front of them with a piece."
    ),
    ("allows_tactic", None): (
        "Look at your opponent's forcing replies — checks, captures and threats — before every move."
    ),
    ("allows_attack", None): (
        "Before each move, picture your opponent's strongest reply: can one move of theirs attack two "
        "of your weak points at once? Loose pawns and pieces are the usual targets."
    ),
    ("loses_material", None): (
        "Calculate the forcing replies first: what checks, captures and threats does my move allow?"
    ),
    ("missed_mate", None): (
        "When the enemy king is short of squares, look at every check — there may be a mate."
    ),
    ("missed_tactic", "fork"): (
        "Scan for double attacks: is there a square where one of your pieces hits two targets at once?"
    ),
    ("missed_tactic", None): ("Checks, captures, threats: look at your own forcing moves first, every turn."),
    ("missed_material", None): (
        "Every move, ask what your opponent's last move left undefended. Free material is the easiest "
        "win in chess."
    ),
    ("missed_win", None): (
        "In sharp positions, look for forcing moves first — checks, captures and threats."
    ),
    ("tablebase", None): (
        "Endgames reward precision: count tempi, and before trading or pushing, check whether the "
        "resulting position is still winning."
    ),
    ("stalemate", None): (
        "When you're winning, check that your opponent still has a legal move after yours — "
        "especially when their king is boxed in."
    ),
    ("allows_repetition", None): (
        "When you're winning, keep count of repeated positions: the third time is a draw. Instead of "
        "another check, bring a new piece into the attack."
    ),
    ("repetition", None): (
        "A position seen for the third time is a draw. When you're ahead, vary your moves and make "
        "progress rather than repeating."
    ),
    ("positional", "king_safety"): (
        "Pawns in front of a castled king are its shield. Push them only with a good reason."
    ),
    ("positional", "isolated_pawn"): (
        "An isolated pawn can't be defended by other pawns, so it tends to become a target."
    ),
    ("positional", "doubled_pawns"): (
        "Doubled pawns are often weak — they can't protect each other. Think twice before allowing them."
    ),
    ("positional", "passed_pawn_allowed"): (
        "A passed pawn has nothing in front of it but pieces. Don't hand your opponent one for free."
    ),
    ("positional", "development"): (
        "In the opening, bring out your knights and bishops first — every move that doesn't develop "
        "gives your opponent time."
    ),
    ("positional", "outpost_allowed"): (
        "A knight on a square that pawns can't attack is a monster. Don't give your opponent such "
        "outposts in your half of the board."
    ),
    ("positional", None): (
        "When there's no tactic, improve your worst-placed piece and keep your pawn structure healthy."
    ),
    ("opening_principle", "early_queen"): (
        "Bringing the queen out early lets your opponent develop with tempo by attacking it."
    ),
    ("opening_principle", "same_piece_twice"): (
        "In the opening, avoid moving the same piece twice before your other pieces are out."
    ),
    ("opening_principle", "king_walk"): (
        "Moving your king in the opening costs you castling. Castle early to keep the king safe."
    ),
    ("opening_principle", "weakening_pawn_move"): (
        "The f- and g-pawns shield your king. Moving them early opens lines toward it."
    ),
    ("clock", "rushed"): (
        "Spend your time where it matters: when there are checks, captures or threats on the board, "
        "slow down."
    ),
}


def lesson_for(kind: str, motif: str | None = None) -> str | None:
    return LESSONS.get((kind, motif)) or LESSONS.get((kind, None))
