"""Chainlit session state (FR-12) — pure logic, testable without a server.

``app.py`` is a thin shell over this module. The rules it enforces:

- **Built once per session**: :meth:`DeskSession.build` validates config,
  performs the process-wide wiring ONCE (FR-11 runner, FR-13 tracing), and
  assembles the Desk agent + ``StudentProfile``. The per-message handler only
  calls :meth:`DeskSession.send` — nothing is rebuilt per message.
- **Memory**: ``send`` replaces ``history`` with ``result.to_input_list()``
  after every run, so a second message referring to the first is understood.
  Two ``DeskSession`` objects never share state — two browser windows don't
  share history.
- **Failure modes** (NFR-1, FR-12): every failure maps to a friendly sentence
  from :mod:`desk.errors`; the traceback goes to the server-side logger only.

Branded-UX helpers (:func:`welcome_message`, :func:`ticket_card`,
:data:`STARTER_CHIPS`) produce the markdown the app renders.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agents import (
    Agent,
    InputGuardrailTripwireTriggered,
    MaxTurnsExceeded,
    RunHooks,
    Runner,
)
from agents.exceptions import ModelBehaviorError

from desk.agents import build_desk_agent
from desk.courses import CourseDataError, repo
from desk.config import load_config
from desk.errors import (
    MODEL_FAILURE_MESSAGE,
    TICKET_PARSE_FAILURE_MESSAGE,
    TURN_CEILING_MESSAGE,
    ConfigError,
    log_exception,
)
from desk.guardrails import OFF_TOPIC_REFUSAL
from desk.profile import StudentProfile
from desk.ticket import Ticket
from desk.tracing import install_jsonl_tracing

# FR-9c: the same defended ceiling as the CLI (desk.cli.MAX_TURNS).
MAX_TURNS = 10

# T15 starter chips: (label shown on the chip, message it sends).
STARTER_CHIPS: list[tuple[str, str]] = [
    ("📅 Assignment deadlines", "When is my A3 due?"),
    ("⏰ Late policy", "What if I submit late?"),
    ("🚀 Career roadmap", "Career roadmap after this bootcamp?"),
]

_PROCESS_SETUP_DONE = False


def _register_stamping_runner() -> None:
    """FR-11: register the custom runner once, via the SDK's startup hook."""
    from agents.run import set_default_agent_runner

    from desk.runner import StampingRunner

    set_default_agent_runner(StampingRunner())


def ensure_process_setup() -> None:
    """Process-wide wiring that must happen exactly once (FR-11 + FR-13)."""
    global _PROCESS_SETUP_DONE
    if _PROCESS_SETUP_DONE:
        return
    install_jsonl_tracing()
    _register_stamping_runner()
    _PROCESS_SETUP_DONE = True


@dataclass
class DeskSession:
    """One browser session: the agent, the student, and the conversation."""

    agent: Agent[StudentProfile]
    profile: StudentProfile
    history: list = field(default_factory=list)
    run_hooks: RunHooks | None = None

    @classmethod
    def build(
        cls,
        model=None,
        assignments_hooks=None,
        run_hooks: RunHooks | None = None,
        name: str = "Student",
        roll_no: str = "S-2026-001",
        course_id: str = "agentic-ai-w4",
        tier: str = "regular",
        open_tickets: int = 0,
    ) -> "DeskSession":
        """Build the session state ONCE (per browser session).

        ``model`` is the test seam (ScriptedModel); ``assignments_hooks`` and
        ``run_hooks`` are the FR-10 audit layers the app wires in explicitly.
        Raises ``ConfigError`` on a missing/blank key — before anything else.
        """
        load_config()  # NFR-1: fail fast, friendly error, before any build.
        ensure_process_setup()

        agent = build_desk_agent(model, assignments_hooks=assignments_hooks)
        profile = StudentProfile(
            name=name,
            roll_no=roll_no,
            course_id=course_id,
            tier=tier,
            open_tickets=open_tickets,
        )
        return cls(agent=agent, profile=profile, run_hooks=run_hooks)

    async def send(self, text: str) -> Ticket | str:
        """One conversation turn: run, keep the grown history, map failures.

        Returns a typed ``Ticket`` for resolved conversations; refusals and
        failures come back as friendly sentences, never exceptions.
        """
        self.history.append({"role": "user", "content": text})
        try:
            result = await Runner.run(
                self.agent,
                self.history,
                context=self.profile,
                max_turns=MAX_TURNS,
                hooks=self.run_hooks,
            )
        except InputGuardrailTripwireTriggered:
            # FR-8: refused before the Desk's model was billed a token.
            return OFF_TOPIC_REFUSAL
        except MaxTurnsExceeded:
            # FR-9c: the deliberate ceiling, reported in plain language.
            return TURN_CEILING_MESSAGE
        except ModelBehaviorError as exc:
            # FR-7's pinned parse-failure path — no half-filled object.
            log_exception(exc)
            return TICKET_PARSE_FAILURE_MESSAGE
        except Exception as exc:
            # Model/auth/rate-limit errors: concise message, server-side log.
            log_exception(exc)
            return MODEL_FAILURE_MESSAGE
        self.history[:] = result.to_input_list()
        return result.final_output


def welcome_message(profile: StudentProfile) -> str:
    """The branded welcome card, personalised from the profile (FR-4 style)."""
    try:
        course_title = str(repo.get_course(profile.course_id)["title"])
    except (KeyError, CourseDataError):
        course_title = "your Saylani bootcamp course"
    return (
        f"Welcome to the **Student Ops Desk**, {profile.name}! 👋\n\n"
        f"You're enrolled in **{course_title}**. Ask me about class "
        "schedules, assignments, late policies or your career roadmap — "
        "or pick one of the suggestions below."
    )


def ticket_card(ticket: Ticket) -> str:
    """Render the final ``Ticket`` as a structured card (FR-7 + FR-12)."""
    if ticket.escalate:
        status = "⚠️ Escalated — a human colleague will pick this up"
    elif ticket.resolved:
        status = "✅ Resolved"
    else:
        status = "◻️ Not resolved yet"
    return (
        f"### 🎫 Ticket filed — {ticket.category} queue\n\n"
        f"**Summary:** {ticket.summary}\n\n"
        f"**Next step:** {ticket.next_step}\n\n"
        f"**Status:** {status}"
    )
