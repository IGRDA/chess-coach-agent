"""Interactive Textual TUI: an editable board and a live coaching panel.

The interface-layer front-end shaped like the product mockup — a click-editable
chess board in the centre and a coaching panel that drives the same
:class:`~chess_coach.application.use_cases.coach_position.CoachPosition` use case
the CLI uses. All board editing, move play and request-mapping logic lives in
pure, synchronously testable modules (:mod:`board_state`, :mod:`coaching`,
:mod:`rendering`); the Textual widgets and app stay a thin shell over them.
"""
