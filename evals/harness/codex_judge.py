"""A Codex-backed LLM judge, so the prose metrics run without an Anthropic key.

The teaching / conversation / diagnosis metrics are deepeval ``GEval`` judges that
default to Claude and need ``ANTHROPIC_API_KEY``. Their constructors, though, accept
any injected ``DeepEvalBaseLLM``. This module supplies one backed by the Codex CLI:
the *criteria and the whole GEval harness stay identical* — only the judge model
changes, which is a knob the metric already exposes, not a change to the evaluation.

GEval asks the model for a JSON object (evaluation steps, then a ``{score, reason}``);
Codex follows that prompt and deepeval parses the JSON out of the reply, so the judge
only has to implement ``generate``. Kept at low reasoning effort to stay cheap.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import anyio
from deepeval.models import DeepEvalBaseLLM


def codex_exec_text(
    prompt: str,
    *,
    model: str | None = None,
    reasoning_effort: str | None = "low",
    binary: str = "codex",
) -> str:
    """Run one ``codex exec`` turn non-interactively and return its final message."""
    with tempfile.TemporaryDirectory(prefix="chess-coach-judge-") as tmp:
        out = Path(tmp) / "answer.md"
        cmd = [
            binary,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--output-last-message",
            str(out),
        ]
        if model:
            cmd += ["--model", model]
        if reasoning_effort:
            cmd += ["-c", f"model_reasoning_effort={reasoning_effort}"]
        cmd.append("-")
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        if out.exists() and out.read_text(encoding="utf-8").strip():
            return out.read_text(encoding="utf-8")
        return result.stdout


class CodexJudge(DeepEvalBaseLLM):
    """A ``DeepEvalBaseLLM`` that answers judging prompts via the Codex CLI."""

    def __init__(
        self, *, model: str | None = None, reasoning_effort: str | None = "low"
    ) -> None:
        self._model = model
        self._effort = reasoning_effort

    def load_model(self) -> CodexJudge:
        return self

    def get_model_name(self) -> str:
        return f"codex-judge:{self._model or 'cli-default'}"

    def generate(self, prompt: str, schema: object | None = None, **_: object) -> str:
        # Accept and ignore `schema`: GEval instructs the JSON shape in the prompt and
        # parses the reply itself, so returning the raw text is exactly what it wants.
        return codex_exec_text(
            str(prompt), model=self._model, reasoning_effort=self._effort
        )

    async def a_generate(
        self, prompt: str, schema: object | None = None, **_: object
    ) -> str:
        return await anyio.to_thread.run_sync(self.generate, prompt)
