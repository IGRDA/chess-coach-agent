# Coaching notes

Reference material for pitching explanations and naming motifs. Read this when you
want the teaching to land — the concrete facts still come from the tools.

## Pitch by level

- **beginner** — one idea, no jargon. "The rook slides to e8 and it's checkmate:
  the king is trapped behind its own pawns." Avoid variations. Ask simple, concrete
  questions ("is the black king safe?").
- **intermediate** — name the motif and the reason. "A knight fork with check:
  because it's check, Black must move the king, so you win the rook next move." Invite
  a short candidate list before revealing.
- **advanced** — you may reference the key point tersely and note the alternative
  that fails. Still lead with the idea, not a move dump; compare candidates head to
  head.

## Tactical motifs worth naming

Fork / double attack; pin (absolute vs. relative); skewer; discovered attack and
discovered check; deflection / removing the defender; overloaded piece; back-rank
mate (and "luft"); smothered mate; underpromotion; interference; zwischenzug;
clearance; attraction.

When the engine's best move is a mate, say so plainly ("mate in one/two") — a
forced mate dominates any material count.

## Endgame methods worth naming

- **Opposition** — kings facing with one square between; having the opposition
  wins king-and-pawn races and key-square fights.
- **Square of the pawn** — the rule of the square tells you at a glance whether a
  lone king catches a passed pawn.
- **Lucena position** — the winning rook-endgame technique; "building a bridge"
  to shelter the king from checks and promote.
- **Philidor position** — the drawing rook-endgame defense; keep the rook on the
  third rank until the pawn advances, then check from behind.
- **Wrong bishop / rook-pawn** — a bishop that does not control the promotion
  square, with a rook's pawn, is only a draw against a king in the corner.
- **Opposite-colored bishops** — a strong drawing tendency even a pawn or two down.
- **Réti idea** — the king takes a diagonal path to chase a pawn and support its
  own at once; geometry beats intuition.

## Assessment buckets

`winning` (decisive, roughly +3 or more / a forced mate), `better` (a clear edge,
about +1 to +3), `equal` (within about a pawn either way), `worse`, `losing` —
mirror images from the side to move. Trust the engine's bucket; explain the
imbalance that produces it.

## Reading move verdicts

`evaluate_move` grades a move by how much it gives up versus the best: `best` (the
engine's choice), `good` (a hair behind), `inaccuracy`, `mistake`, `blunder`. Use the
verdict to engage with the student's idea honestly — praise a `good` move, and when a
move is a `mistake` or `blunder`, show *what it allows* rather than just labeling it.
