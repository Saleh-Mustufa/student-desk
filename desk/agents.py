"""Desk agent assembly (FR-1, FR-5) — the front desk and its specialists.

The model is declared AT the agent (``Agent(model=...)``): there is
deliberately no process-global OpenAI client and no run-level model override
(``RunConfig.model``) anywhere in this project. Tests inject a scripted model
through the ``model`` parameter of every build function — the only supported
seam.

FR-5 lives here: one base specialist is cloned twice via ``Agent.clone()``;
only ``name``, ``instructions`` and ``model_settings`` differ (the fields the
graded brief allows). Neither clone restates ``model=`` — ``clone()`` carries
it over. The clones receive FRESH tool lists: ``clone()`` performs a shallow
copy, so passing ``tools=base.tools`` would make both specialists share one
list and grow each other's tools (plan.md §2). The Desk hands conversations to
whichever specialist fits via ``handoffs``, and carries the shared typed
output (``output_type=Ticket``, FR-7), which the clones inherit.

The FR-8 off-topic input guardrail (zero model calls) is wired below from
:mod:`desk.guardrails` with ``run_in_parallel=False``. FR-6 lives here too:
the Summariser is exposed to the Desk **as a tool** (``Agent.as_tool``), not a
handoff — summarisation is a sub-task the Desk borrows mid-answer and then
speaks in its own voice, where assignment/career questions are jobs that pass
to an owner. Deliberately NOT built here (later tasks add them; nothing is
pre-built): ``close_ticket``/tool gating (FR-9), hooks (FR-10).
"""

from __future__ import annotations

from agents import (
    Agent,
    AgentHooks,
    FunctionTool,
    ModelSettings,
    RunContextWrapper,
    StopAtTools,
)

from desk.config import build_model, load_config
from desk.guardrails import off_topic_guardrail
from desk.profile import StudentProfile
from desk.prompt_builder import (
    AGENT_NAME,
    ASSIGNMENTS_SPECIALIST_NAME,
    CAREERS_SPECIALIST_NAME,
    build_system_prompt,
)
from desk.ticket import Ticket
from desk.tools import (
    close_ticket,
    get_assignment,
    get_course_details,
    list_courses,
    scholarship_benefits,
)

DESK_AGENT_NAME = AGENT_NAME

# Cost ceiling for the Desk (NFR-2): low temperature for consistent policy
# wording, 1000 max tokens for the structured ticket + routing behaviour.
DESK_MODEL_SETTINGS = ModelSettings(temperature=0.2, max_tokens=1000)

# FR-5 model settings, all deliberate and defensible at the viva:
# base template — mildly conservative defaults for a specialist;
BASE_SPECIALIST_MODEL_SETTINGS = ModelSettings(
    temperature=0.3, max_tokens=800, tool_choice="auto"
)
# assignments — cold and factual: determinism beats charm for deadlines and
# verbatim policy text (low temperature), same cost ceiling as the base.
ASSIGNMENTS_MODEL_SETTINGS = ModelSettings(temperature=0.1, max_tokens=800)
# careers — warmer: encouraging guidance needs some variability, still
# grounded in the catalogue's career data, same ceiling.
CAREERS_MODEL_SETTINGS = ModelSettings(temperature=0.7, max_tokens=800)

BASE_SPECIALIST_INSTRUCTIONS = (
    "You are a specialist at the Saylani Student Ops Desk. Ground every fact "
    "in the course catalogue tools and never invent schedules, deadlines, or "
    "policies. Answer the student's actual question first — look the facts "
    "up with the tools and state the answer; only when the question is "
    "resolved, end with the structured ticket, and its summary must carry "
    "the actual answer. That final structured output must be a single raw "
    "JSON object — no markdown fences, no commentary around it."
)
ASSIGNMENTS_INSTRUCTIONS = (
    "You are the assignments specialist for the Saylani bootcamp. Answer "
    "assignment questions — deadlines, requirements, late policy — with "
    "cold, factual precision: short declarative sentences, citing the policy "
    "text exactly as the catalogue tools return it, no pleasantries. Look up "
    "the facts with the tools FIRST and answer the question; only when it is "
    "resolved, end with the structured ticket whose summary carries the "
    "actual answer (the due date or policy itself, not a transfer note). "
    "That final structured output must be a single raw JSON object — no "
    "markdown fences, no commentary around it."
)
CAREERS_INSTRUCTIONS = (
    "You are the careers specialist for the Saylani bootcamp. Answer career "
    "questions — career paths, the roadmap after the bootcamp, placement — "
    "with a warm, encouraging tone, grounded in the career data the "
    "catalogue tools return; encouragement is welcome but every fact still "
    "comes from the catalogue. Look up the facts FIRST and answer the "
    "question; only when it is resolved, end with the structured ticket "
    "whose summary carries the actual answer. That final structured output "
    "must be a single raw JSON object — no markdown fences, no commentary "
    "around it."
)

# The reference tool list the base template is built with; each clone passes
# its own fresh list (the shallow-copy trap), chosen per specialism.
BASE_SPECIALIST_TOOLS = [list_courses, get_course_details, get_assignment]

# FR-6: a tiny ceiling on purpose — summarisation is cheap or it is pointless.
SUMMARISER_MODEL_SETTINGS = ModelSettings(temperature=0.1, max_tokens=200)
SUMMARISER_INSTRUCTIONS = (
    "You are the Summariser at the Saylani Student Ops Desk. Compress the "
    "input answer to at most three lines, keep every fact, and output no "
    "preamble or commentary."
)
# NFR-4: the summariser tool never raises into the runner — any failure
# becomes a sentence the Desk can act on in its own voice.
SUMMARISATION_FAILURE_SENTENCE = (
    "Summarisation failed. Give the student the key facts from the original "
    "answer yourself."
)


def _summarisation_failure(ctx: RunContextWrapper, error: Exception) -> str:
    """Tool error function: failure becomes a model-actionable sentence."""
    return SUMMARISATION_FAILURE_SENTENCE


def build_summariser(model=None) -> Agent:
    """Build the Summariser agent — static instructions, no tools, no handoffs.

    ``model`` defaults to the Gemini-backed failover model; tests inject a
    scripted model so the whole desk (Desk, specialists, summariser) can run
    on one shared scripted instance.
    """
    if model is None:
        model = build_model(load_config())

    return Agent(
        name="Summariser",
        instructions=SUMMARISER_INSTRUCTIONS,
        model=model,
        model_settings=SUMMARISER_MODEL_SETTINGS,
    )


def build_summarise_answer_tool(model=None) -> FunctionTool:
    """Expose the Summariser to the Desk as the ``summarise_answer`` tool (FR-6).

    Deliberately a tool, not a handoff (FR-6): a handoff would transfer the
    conversation away from the Desk, but summarisation is a sub-task the Desk
    borrows and then weaves into its own reply. ``max_turns=2`` bounds the
    internal run; ``failure_error_function`` keeps it raise-free (NFR-4).
    """
    return build_summariser(model).as_tool(
        tool_name="summarise_answer",
        tool_description=(
            "Condense a long policy answer to at most three lines, keeping "
            "every fact. Pass the full answer as `input`."
        ),
        failure_error_function=_summarisation_failure,
        max_turns=2,
    )


def build_base_specialist(model=None) -> Agent[StudentProfile]:
    """Build the specialist template the two specialists clone.

    Never run directly — it exists so the clones are provably
    ``clone()``-derived and share one declared model object. ``model``
    defaults to the Gemini-backed failover model built from configuration.
    """
    if model is None:
        model = build_model(load_config())

    return Agent[StudentProfile](
        name="Specialist Base",
        instructions=BASE_SPECIALIST_INSTRUCTIONS,
        tools=list(BASE_SPECIALIST_TOOLS),
        model=model,
        model_settings=BASE_SPECIALIST_MODEL_SETTINGS,
        # Declared once here; the clones inherit it (FR-7 for specialists too).
        output_type=Ticket,
    )


def build_specialists(
    model=None, assignments_hooks: AgentHooks | None = None
) -> tuple[Agent[StudentProfile], Agent[StudentProfile]]:
    """Clone the two specialists from one base (FR-5).

    Only ``name``, ``instructions`` and ``model_settings`` differ — exactly
    the fields the brief allows. Neither clone restates ``model=``; each
    receives a FRESH tool list so specialists never grow each other's tools.

    ``assignments_hooks`` (FR-10) attaches agent-level hooks to EXACTLY ONE
    specialist — the assignments close-watch; the careers specialist never
    carries hooks, so agent-level events belong to their one agent only.
    """
    base = build_base_specialist(model)

    assignments = base.clone(
        name=ASSIGNMENTS_SPECIALIST_NAME,
        instructions=ASSIGNMENTS_INSTRUCTIONS,
        model_settings=ASSIGNMENTS_MODEL_SETTINGS,
        tools=[list_courses, get_course_details, get_assignment],
        hooks=assignments_hooks,
    )
    careers = base.clone(
        name=CAREERS_SPECIALIST_NAME,
        instructions=CAREERS_INSTRUCTIONS,
        model_settings=CAREERS_MODEL_SETTINGS,
        tools=[list_courses, get_course_details],
    )
    return assignments, careers


def build_desk_agent(
    model=None, assignments_hooks: AgentHooks | None = None
) -> Agent[StudentProfile]:
    """Assemble the Desk agent, wiring ``model`` at the agent level.

    ``model`` defaults to the Gemini-backed chat-completions model built from
    configuration (:func:`desk.config.build_model(load_config())`). Passing a
    model object is how tests stay network-free; the specialists share the
    same model object so one scripted instance drives the whole handoff.

    ``assignments_hooks`` (FR-10) passes through to the assignments clone, so
    the caller decides which single specialist carries the close-watch.
    """
    if model is None:
        model = build_model(load_config())

    assignments, careers = build_specialists(model, assignments_hooks=assignments_hooks)

    return Agent[StudentProfile](
        name=DESK_AGENT_NAME,
        # Dynamic instructions: the SDK calls build_system_prompt(wrapper, agent)
        # before every run, so the prompt is rebuilt from the profile per turn.
        instructions=build_system_prompt,
        # Admin questions (schedules, policies) the Desk answers itself;
        # FR-6: the Summariser rides along as a tool for long policy answers;
        # FR-9a: scholarship_benefits is offered ONLY to scholarship-tier
        # students (its is_enabled reads the tier from context — absent, not
        # refused, for regular tier); FR-9b: close_ticket is the stopping rule.
        tools=[
            list_courses,
            get_course_details,
            scholarship_benefits,
            build_summarise_answer_tool(model),
            close_ticket,
        ],
        # FR-9b: the run ends the moment close_ticket fires; the tool's raw
        # output — the Ticket instance — becomes result.final_output (FR-7).
        tool_use_behavior=StopAtTools(stop_at_tool_names=["close_ticket"]),
        # FR-5: assignment/career questions transfer to the cloned specialists.
        handoffs=[assignments, careers],
        # FR-8: zero-model-call off-topic tripwire, runs before the model
        # (run_in_parallel=False, see desk/guardrails.py).
        input_guardrails=[off_topic_guardrail],
        # FR-7: every resolved conversation ends in a typed Ticket.
        output_type=Ticket,
        model=model,
        model_settings=DESK_MODEL_SETTINGS,
    )
