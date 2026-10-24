"""Run the clinic agent.

Usage:
    python -m clinic chat     # interactive REPL (Rich-rendered when on a TTY)
    python -m clinic smoke    # scripted multi-turn conversation (a quick live check)
    python -m clinic once "your message here"

Requires Google/Vertex env (see GETTING-STARTED.md): a service-account JSON in
GOOGLE_APPLICATION_CREDENTIALS. `adk web` also works — point it at src/clinic.

The interactive `chat` uses Rich (Markdown rendering + a "thinking" spinner) when
stdout is a terminal, and falls back to a plain stdin/stdout loop otherwise —
so piping, `smoke`, and `once` stay clean, capturable text.
"""

from __future__ import annotations

import asyncio
import sys

APP = "clinic"
USER = "cli-user"
SESSION = "cli-session"


async def _make_runner():
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    from clinic.agents.build import build_clinic_agent
    from clinic.env import init_google_env, require_google_env

    init_google_env()
    problems = require_google_env()
    if problems:
        print("Environment not ready:")
        for p in problems:
            print(f"  - {p}")
        print("See GETTING-STARTED.md.")
        raise SystemExit(2)

    agent = build_clinic_agent()
    session_service = InMemorySessionService()
    await session_service.create_session(app_name=APP, user_id=USER, session_id=SESSION)
    return Runner(agent=agent, app_name=APP, session_service=session_service)


async def _turn(runner, text: str) -> str:
    from google.genai import types

    message = types.Content(role="user", parts=[types.Part(text=text)])
    reply = ""
    async for event in runner.run_async(user_id=USER, session_id=SESSION, new_message=message):
        if event.is_final_response() and event.content and event.content.parts:
            reply = "".join(p.text or "" for p in event.content.parts)
    return reply


# ---- interactive chat ----
async def chat() -> None:
    runner = await _make_runner()
    if sys.stdout.isatty():
        await _chat_rich(runner)
    else:
        await _chat_plain(runner)


async def _chat_rich(runner) -> None:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.prompt import Prompt

    console = Console()
    console.print(
        "[bold]Clinic appointment agent[/]  [dim](type 'exit' to quit)[/]\n"
    )
    while True:
        try:
            text = await asyncio.to_thread(Prompt.ask, "[bold cyan]you[/]")
        except (EOFError, KeyboardInterrupt):
            break
        if text.strip().lower() in {"exit", "quit"}:
            break
        with console.status("[dim]thinking…[/]", spinner="dots"):
            reply = await _turn(runner, text)
        console.print("[bold green]clinic[/]")
        console.print(Markdown(reply))
        console.print()


async def _chat_plain(runner) -> None:
    print("Clinic appointment agent. Type 'exit' to quit.\n")
    while True:
        try:
            text = await asyncio.to_thread(input, "you> ")
        except (EOFError, KeyboardInterrupt):
            break
        if text.strip().lower() in {"exit", "quit"}:
            break
        print(f"clinic> {await _turn(runner, text)}\n")


# ---- scripted / one-shot (always plain text, so output is capturable) ----
async def once(text: str) -> None:
    runner = await _make_runner()
    print(await _turn(runner, text))


async def smoke() -> None:
    """A scripted conversation that exercises verify -> list -> book flow live."""
    runner = await _make_runner()
    turns = [
        "Hi! I'm Ada Lovelace, date of birth 1990-01-01.",
        "What appointments do I currently have?",
        "I'd like to book a dermatology visit with Dr. Chen. What's open?",
    ]
    for t in turns:
        print(f"\n>>> {t}")
        print(f"<<< {await _turn(runner, t)}")


# A scripted conversation for recording a Rich-rendered demo (e.g. with asciinema).
# The arc walks the gates: identity -> list -> eligibility refusal/self-pay ->
# pivot to a covered service -> confirmation gate -> booked.
_DEMO_TURNS = [
    "Hi! I'm Ada Lovelace, date of birth 1990-01-01.",
    "What appointments do I currently have?",
    "I'd like to see Dr. Patel for a cardiology check-up.",
    "No thanks on self-pay — let's book a dermatology visit with Dr. Chen instead. What's open?",
    "Tuesday, July 7th at 9 AM sounds great — please book it.",
]


async def demo() -> None:
    """Auto-play the scripted scenario through the Rich renderer (for recording)."""
    from rich.console import Console
    from rich.markdown import Markdown

    runner = await _make_runner()
    console = Console()
    console.print("[bold]Clinic appointment agent[/]  [dim](demo)[/]\n")
    for text in _DEMO_TURNS:
        console.print(f"[bold cyan]you[/]: {text}")
        with console.status("[dim]thinking…[/]", spinner="dots"):
            reply = await _turn(runner, text)
        console.print("[bold green]clinic[/]")
        console.print(Markdown(reply))
        console.print()
        await asyncio.sleep(1.2)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "chat"
    if mode == "smoke":
        asyncio.run(smoke())
    elif mode == "demo":
        asyncio.run(demo())
    elif mode == "once":
        asyncio.run(once(" ".join(sys.argv[2:]) or "hello"))
    else:
        asyncio.run(chat())


if __name__ == "__main__":
    main()
