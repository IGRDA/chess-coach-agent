"""Prompt and tone assets for the Claude coach adapter.

Holds the system-prompt templates and coaching-tone/level presets that shape how
the agent teaches (e.g. beginner vs. advanced register, concise vs. detailed).
Kept separate from claude_agent.py so the wording — pure data — can be reviewed
and tuned without touching orchestration logic.

Exposes
    The system-prompt template(s) and the named tone/level presets consumed by the
    Claude agent adapter.

Collaborators
    Read exclusively by claude_agent.py.

Note
    Contains presentation data only, never behaviour or control flow.
"""
