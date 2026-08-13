"""Provider-neutral coaching skills and their runtime translations.

The checked-in skill library lives at ``.agents/skills``.  This module is the one
place that resolves those assets, selects the coaching method for a task, and adapts
the evidence contract to a provider.  Claude receives MCP-backed capability names;
Codex receives the same method with an explicit instruction to consume the engine
facts that its adapter computed before model execution.

Keeping this translation here prevents provider discovery conventions from leaking
into prompts, evaluation code, or the composition root.  It also makes skill use
deterministic: every coaching turn names and embeds the selected skill even when the
provider is launched from an unrelated working directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Provider = Literal["claude", "codex"]

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SKILLS_DIR = REPOSITORY_ROOT / ".agents" / "skills"


@dataclass(frozen=True)
class SkillDocument:
    """One validated Agent Skill with its optional supporting references."""

    name: str
    description: str
    body: str
    references: tuple[tuple[str, str], ...] = ()


# Logical capabilities belong to the coaching method.  Provider adapters decide how
# those capabilities are fulfilled: MCP tools for Claude, precomputed evidence for
# Codex.  They are deliberately not provider tool identifiers.
_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "assessment-coach": (
        "analyze_position",
        "position_features",
        "opening_lookup",
    ),
    "endgame-coach": (
        "analyze_position",
        "probe_tablebase",
        "position_features",
    ),
    "general-coach": (),
    "interactive-coach": (
        "analyze_position",
        "position_features",
        "compare_candidates",
        "evaluate_move",
        "opening_lookup",
        "probe_tablebase",
    ),
    "tactics-coach": (
        "analyze_position",
        "position_features",
        "compare_candidates",
        "evaluate_move",
    ),
}

_TASK_SKILLS: dict[str, str] = {
    "best_move": "tactics-coach",
    "conversation": "interactive-coach",
    "deep_line": "tactics-coach",
    "endgame": "endgame-coach",
    "eval_bucket": "assessment-coach",
    "explain": "interactive-coach",
    "general_chat": "general-coach",
    "mistake_diagnosis": "interactive-coach",
    "multi_turn_teaching": "interactive-coach",
    "teaching": "interactive-coach",
}


def skill_for_task(task_type: str) -> str:
    """Return the single coaching method selected for ``task_type``."""
    try:
        return _TASK_SKILLS[task_type]
    except KeyError as exc:
        message = f"no coaching skill configured for task {task_type!r}"
        raise ValueError(message) from exc


def capabilities_for(skills: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Return the stable union of logical capabilities required by ``skills``."""
    names = (skills,) if isinstance(skills, str) else tuple(skills)
    capabilities: list[str] = []
    for name in names:
        try:
            required = _CAPABILITIES[name]
        except KeyError as exc:
            raise ValueError(f"unknown coaching skill {name!r}") from exc
        capabilities.extend(required)
    return tuple(dict.fromkeys(capabilities))


def _frontmatter(text: str, path: Path) -> tuple[dict[str, str], str]:
    """Parse the small scalar YAML subset used by Agent Skill metadata."""
    if not text.startswith("---\n"):
        raise ValueError(f"{path} must start with YAML frontmatter")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise ValueError(f"{path} has unterminated YAML frontmatter")
    raw, body = text[4:marker], text[marker + 5 :]
    metadata: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or not value.strip():
            raise ValueError(f"{path} has unsupported frontmatter line {line!r}")
        metadata[key.strip()] = value.strip()
    return metadata, body.strip()


def load_skill(name: str) -> SkillDocument:
    """Load and validate a canonical skill by name."""
    path = SKILLS_DIR / name / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"coaching skill {name!r} is unavailable at {path}") from exc
    metadata, body = _frontmatter(text, path)
    skill_name = metadata.get("name", "")
    description = metadata.get("description", "")
    if skill_name != name:
        raise ValueError(
            f"coaching skill directory {name!r} declares name {skill_name!r}"
        )
    if not description:
        raise ValueError(f"coaching skill {name!r} needs a description")
    if not body:
        raise ValueError(f"coaching skill {name!r} needs instructions")
    references_dir = path.parent / "references"
    references = (
        tuple(
            (
                reference.relative_to(path.parent).as_posix(),
                reference.read_text(encoding="utf-8").strip(),
            )
            for reference in sorted(references_dir.rglob("*.md"))
        )
        if references_dir.exists()
        else ()
    )
    return SkillDocument(name, description, body, references)


def render_skill(name: str, provider: Provider) -> str:
    """Render ``name`` with the provider's evidence translation.

    The full body is embedded intentionally.  Codex is also explicitly invoked with
    ``$skill-name`` so its native skill mechanism is exercised when available, while
    the embedded copy keeps source checkouts and packaged callers deterministic.
    """
    skill = load_skill(name)
    capabilities = capabilities_for(name)
    if provider == "claude":
        evidence = (
            "Claude evidence adapter: the named capabilities below are in-process "
            "chess tools. Call the relevant tools before making concrete claims."
        )
    elif provider == "codex":
        evidence = (
            "Codex evidence adapter: Stockfish, position features, opening data, "
            "candidate evaluations, and tablebase results are precomputed by the "
            "application and supplied in the prompt. Treat those fields as the "
            "results of the matching capabilities. Do not call shell commands or "
            "claim that evidence is missing when it is present."
        )
    else:  # pragma: no cover - the Provider type prevents ordinary callers
        raise ValueError(f"unsupported skill provider {provider!r}")
    capability_text = ", ".join(capabilities) if capabilities else "none"
    sections = [
        f"# Active skill: {skill.name}",
        f"Description: {skill.description}",
        evidence,
        f"Available logical capabilities for this skill: {capability_text}.",
        skill.body,
    ]
    sections.extend(
        f"## Included skill reference: {path}\n\n{text}"
        for path, text in skill.references
    )
    return "\n\n".join(sections)


def codex_skill_prompt(name: str, prompt: str) -> str:
    """Activate and inline ``name`` around an application prompt for Codex."""
    return (
        f"Use ${name} for this coaching turn. The canonical skill is embedded "
        "below as a deterministic fallback.\n\n"
        f"{render_skill(name, 'codex')}\n\n"
        f"# Turn input\n\n{prompt}"
    )


def claude_system_prompt(name: str, system_prompt: str) -> str:
    """Append the selected canonical skill to a Claude system prompt."""
    return f"{system_prompt}\n\n{render_skill(name, 'claude')}"


def fingerprint_text() -> str:
    """Return all canonical skill markdown for evaluation-cache invalidation."""
    if not SKILLS_DIR.exists():
        return ""
    return "\x00".join(
        path.read_text(encoding="utf-8") for path in sorted(SKILLS_DIR.rglob("*.md"))
    )
