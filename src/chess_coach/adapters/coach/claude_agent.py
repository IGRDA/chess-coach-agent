"""Claude agent adapter: CoachPort backed by the Claude Agent SDK.

Implements CoachPort using a Claude agent as the coaching brain. A deep module:
its interface is the small set of CoachPort operations, while it hides model
selection and configuration, system-prompt assembly, registration of the agent's
tools/skills (including the `engine` CLI so the agent can consult Stockfish),
the request/response and streaming loop, and the parsing of model output back
into domain Lesson objects.

Implements
    CoachPort.

Collaborators
    Configured with the model id, credentials and enabled skills by the
    composition root. Draws its templates from prompts.py and its skill
    definitions from the top-level `skills/` tree.

Hidden complexity
    All Claude Agent SDK types, tool wiring, retries and streaming stay inside
    this module; callers see only domain Lessons and domain errors.
"""
