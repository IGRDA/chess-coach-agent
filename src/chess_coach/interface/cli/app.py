"""CLI root: application entry point and command registry.

Assembles the terminal application: builds the Typer app, registers the verbs,
obtains the wired coach from the composition root, dispatches to the command, and
maps errors to process exit codes. It contains no coaching logic — only wiring,
argument parsing and top-level error translation.

Tracing-bullet slice: the ``coach`` verb (coach a position). Further verbs
(analyze, import, drill, progress, engine) register here the same way as their use
cases land. Exit codes: ``0`` success, ``2`` a domain error (bad FEN, unknown
task), ``3`` the engine is unavailable.
"""

from __future__ import annotations

import anyio
import typer

from chess_coach.adapters.coach.analysis import EngineUnavailableError
from chess_coach.application.dto import CoachingRequest
from chess_coach.composition.config import (
    ProviderName,
    Settings,
    load_settings,
    save_provider,
)
from chess_coach.composition.container import chat_service, coach_service
from chess_coach.composition.providers import (
    Check,
    auth_status,
    login_provider,
    selected_model,
    stockfish_status,
)
from chess_coach.domain.errors import CoachError
from chess_coach.interface.cli.commands import coach as coach_command

_START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
_PROVIDERS: tuple[ProviderName, ...] = ("claude", "codex")

app = typer.Typer(
    add_completion=False,
    help="Agentic chess coaching: provider narration grounded by Stockfish.",
    no_args_is_help=True,
)
provider_app = typer.Typer(help="Choose and inspect the active coach provider.")
app.add_typer(provider_app, name="provider")

_EXIT_DOMAIN_ERROR = 2
_EXIT_ENGINE_UNAVAILABLE = 3


@app.callback()
def _root() -> None:
    """Chess coach: engine-grounded coaching from the terminal.

    A no-op root callback so each verb (``coach`` today; analyze/import/drill/…
    as they land) stays an explicitly named subcommand rather than collapsing
    into the root when only one exists.
    """


@app.command()
def coach(
    fen: str = typer.Argument(..., help="Position to coach, as a FEN string."),
    task: str = typer.Option(
        "best_move",
        "--task",
        "-t",
        help="What to ask: best_move, eval_bucket, endgame, or deep_line.",
    ),
    level: str | None = typer.Option(
        None, "--level", "-l", help="Audience level, e.g. beginner (tunes the pitch)."
    ),
    move: str | None = typer.Option(
        None,
        "--move",
        "-m",
        help="A concrete move to evaluate (UCI or SAN), e.g. Nxe5 or f3f7.",
    ),
) -> None:
    """Coach a single position: the engine-grounded move, assessment and why."""
    request = CoachingRequest(fen=fen, task=task, level=level, candidate_move=move)
    try:
        with coach_service(load_settings()) as service:
            output = coach_command.run(service, request)
    except CoachError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(_EXIT_DOMAIN_ERROR) from exc
    except EngineUnavailableError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(_EXIT_ENGINE_UNAVAILABLE) from exc
    typer.echo(output)


@app.command()
def setup(
    provider: str | None = typer.Option(
        None,
        "--provider",
        "-p",
        help="Provider to configure: claude or codex.",
    ),
    login: bool = typer.Option(
        True,
        "--login/--no-login",
        help="Run the provider login command when auth is not ready.",
    ),
) -> None:
    """Guided first-run setup: choose provider, write config and check auth."""
    selected = _choose_provider(provider)
    path = save_provider(selected)
    typer.echo(f"Active provider: {selected}")
    typer.echo(f"Config: {path}")
    _report_check("Stockfish", stockfish_status(load_settings()))
    auth = auth_status(selected)
    _report_check("Provider auth", auth)
    if login and not auth.ok:
        typer.echo(f"Starting {selected} login...")
        result = login_provider(selected)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            typer.echo(f"Login failed: {detail}", err=True)
            raise typer.Exit(1)
        _report_check("Provider auth", auth_status(selected))


@provider_app.command("use")
def use_provider(provider: str = typer.Argument(..., help="claude or codex")) -> None:
    """Switch the active provider."""
    selected = _parse_provider(provider)
    path = save_provider(selected)
    typer.echo(f"Active provider: {selected}")
    typer.echo(f"Config: {path}")


@provider_app.command("login")
def login_active_provider() -> None:
    """Run the active provider's login command."""
    settings = load_settings()
    result = login_provider(settings.provider)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        typer.echo(f"Login failed: {detail}", err=True)
        raise typer.Exit(1)


@provider_app.command("status")
def provider_status() -> None:
    """Show the active provider, model and readiness checks."""
    settings = load_settings()
    typer.echo(f"Provider: {settings.provider}")
    typer.echo(f"Model: {selected_model(settings)}")
    _report_check("Provider auth", auth_status(settings.provider))
    _report_check("Stockfish", stockfish_status(settings))


@app.command()
def doctor() -> None:
    """Check provider auth and Stockfish availability."""
    settings = load_settings()
    typer.echo(f"Provider: {settings.provider}")
    typer.echo(f"Model: {selected_model(settings)}")
    checks = [
        ("Provider auth", auth_status(settings.provider)),
        ("Stockfish", stockfish_status(settings)),
    ]
    for label, check in checks:
        _report_check(label, check)
    if not all(check.ok for _, check in checks):
        raise typer.Exit(1)


async def _chat_repl(settings: Settings, fen: str, level: str | None) -> None:
    """Drive a terminal conversation with the coach until the student quits."""
    typer.echo(
        "Chess coach — chat. Talk to the coach; commands: :fen <FEN> to set the "
        "position, :eval to reveal the engine's assessment, :quit to exit.\n"
        f"Position: {fen}"
    )
    async with chat_service(settings) as coach:
        while True:
            line = (await anyio.to_thread.run_sync(_read_line)).strip()
            if not line:
                continue
            if line in (":quit", ":q", "exit"):
                return
            if line.startswith(":fen "):
                fen = line[len(":fen ") :].strip()
                typer.echo(f"Position set: {fen}")
                continue
            if line == ":eval":
                try:
                    typer.echo(f"[assessment: {coach.assess(fen)}]")
                except (ValueError, RuntimeError) as exc:
                    typer.echo(f"[error: {exc}]")
                continue
            typer.echo("coach> ", nl=False)
            async for chunk in coach.stream(fen, line, level):
                typer.echo(chunk, nl=False)
            typer.echo("")


def _read_line() -> str:
    try:
        return input("you> ")
    except EOFError:
        return ":quit"


@app.command()
def chat(
    fen: str = typer.Option(
        _START_FEN, "--fen", "-f", help="Position to start from, as a FEN string."
    ),
    level: str | None = typer.Option(
        None, "--level", "-l", help="Audience level, e.g. beginner (tunes the pitch)."
    ),
) -> None:
    """Talk to the coach: a live, engine-grounded conversation about a position."""
    settings = load_settings()
    try:
        anyio.run(_chat_repl, settings, fen, level)
    except EngineUnavailableError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(_EXIT_ENGINE_UNAVAILABLE) from exc


@app.command()
def tui() -> None:
    """Launch the interactive board: edit a position and coach it live.

    Opens a Textual full-screen app — a click-editable board on the left and a
    coaching panel on the right. Fails fast with exit code 3 if Stockfish is not
    available, so the engine problem is reported here rather than mid-session.
    """
    from chess_coach.interface.tui.app import run as run_tui

    settings = load_settings()
    try:
        # Prove the engine is reachable up front, then hand off to the app (which
        # opens its own coaching session for the length of the run).
        with coach_service(settings):
            pass
    except EngineUnavailableError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(_EXIT_ENGINE_UNAVAILABLE) from exc
    run_tui(settings_loader=load_settings)


def main() -> None:
    """Entry point for the console-script and ``python -m chess_coach``."""
    app()


def _choose_provider(provider: str | None) -> ProviderName:
    if provider is not None:
        return _parse_provider(provider)
    answer = typer.prompt(
        "Choose provider [claude/codex]",
        default="claude",
        show_default=True,
    )
    return _parse_provider(answer)


def _parse_provider(provider: str) -> ProviderName:
    value = provider.strip().lower()
    if value in _PROVIDERS:
        return value
    choices = ", ".join(_PROVIDERS)
    raise typer.BadParameter(f"unknown provider {provider!r}; use {choices}")


def _report_check(label: str, check: Check) -> None:
    marker = "OK" if check.ok else "FAIL"
    typer.echo(f"{label}: {marker} - {check.detail}")
