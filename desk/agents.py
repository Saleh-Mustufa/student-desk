"""Desk agent assembly (FR-1) — the front-desk agent on Gemini.

The model is declared AT the agent (``Agent(model=...)``): there is
deliberately no process-global OpenAI client and no run-level model override
(``RunConfig.model``) anywhere in this project. Tests inject a scripted model
through the ``model`` parameter of :func:`build_desk_agent` — the only
supported seam.

Deliberately NOT built here (later tasks add them; nothing is pre-built):
handoffs (FR-9), ``output_type`` (FR-7), guardrails (FR-10), AgentHooks
(FR-10).
"""

from __future__ import annotations

from agents import Agent, ModelSettings

from desk.config import build_model, load_config
from desk.profile import StudentProfile
from desk.prompt_builder import AGENT_NAME, build_system_prompt
from desk.tools import get_course_details, list_courses

DESK_AGENT_NAME = AGENT_NAME

# Cost ceiling for the Desk (NFR-2): low temperature for consistent policy
# wording, 1000 max tokens for the structured ticket + routing behaviour.
DESK_MODEL_SETTINGS = ModelSettings(temperature=0.2, max_tokens=1000)


def build_desk_agent(model=None) -> Agent[StudentProfile]:
    """Assemble the Desk agent, wiring ``model`` at the agent level.

    ``model`` defaults to the Gemini-backed chat-completions model built from
    configuration (:func:`desk.config.build_model(load_config())`). Passing a
    model object is how tests stay network-free.
    """
    if model is None:
        model = build_model(load_config())

    return Agent[StudentProfile](
        name=DESK_AGENT_NAME,
        # Dynamic instructions: the SDK calls build_system_prompt(wrapper, agent)
        # before every run, so the prompt is rebuilt from the profile per turn.
        instructions=build_system_prompt,
        # Assignment lookup joins with the specialist agent in a later task.
        tools=[list_courses, get_course_details],
        model=model,
        model_settings=DESK_MODEL_SETTINGS,
    )
