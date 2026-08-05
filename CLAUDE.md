## Engineering Practices

- Apply ETC: make changes easier to change later, but avoid speculative
  abstractions.
- Keep logic DRY when duplication hides a decision, not when two lines merely
  look similar.
- Preserve orthogonality: data fetching, feature creation, training, and
  reporting should not know unnecessary details about each other.
- Prefer small functions with clear contracts. Validate important preconditions
  near boundaries and keep invariants obvious in tests.
- Pull complexity downward into helpers so the notebook and training script read
  like the story of the solution.
- Make modules deep enough to be useful: simple interface, contained
  implementation details.
- Prevent software entropy. Fix small broken-window issues while nearby, but do
  not wander into unrelated refactors.
- Use tracing bullets before prototypes here: build the narrow end-to-end path
  first, then improve it.
- Test behavior, edge cases, and invariants. Keep tests fast and network-free.
- Prefer actionable options over defensive explanations when something is
  blocked or weak.
