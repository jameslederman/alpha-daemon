from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from activities import (
    get_price_history_activity,
    search_company_news_activity,
    search_sec_filings_activity,
)
from models import FundamentalAnalysis, ResearchScope


@dataclass(frozen=True)
class ResearchToolSpec:
    activity: Callable[..., Any]
    start_to_close_timeout: timedelta


@dataclass(frozen=True)
class ResearchSkill:
    name: str
    description: str
    instructions: str
    output_model: type[BaseModel]
    tools: tuple[ResearchToolSpec, ...]
    default_objective_template: str
    allowed_scope_kinds: tuple[str, ...] = ()
    required_scope_attributes: tuple[str, ...] = ()

    def validate_scope(self, scope: ResearchScope) -> None:
        if self.allowed_scope_kinds and scope.kind not in self.allowed_scope_kinds:
            allowed = ", ".join(self.allowed_scope_kinds)
            raise ValueError(
                f"Research skill {self.name!r} does not support scope kind "
                f"{scope.kind!r}. Allowed scope kinds: {allowed}"
            )

        for attribute in self.required_scope_attributes:
            value = scope.attributes.get(attribute)
            if value is None or not value.strip():
                raise ValueError(
                    f"Research skill {self.name!r} requires non-empty scope "
                    f"attribute {attribute!r}"
                )

    def build_default_objective(self, scope: ResearchScope) -> str:
        self.validate_scope(scope)
        return self.default_objective_template.format(**scope.attributes)


_SKILLS_DIR = Path(__file__).with_name("skills")


def _load_skill_instructions(skill_name: str) -> str:
    path = _SKILLS_DIR / skill_name / "SKILL.md"
    return path.read_text(encoding="utf-8").strip()


FUNDAMENTAL_ANALYSIS_SKILL = ResearchSkill(
    name="fundamental_analysis",
    description=(
        "Assess the operating and financial fundamentals of a public company "
        "using evidence from SEC filings, company news, and market data."
    ),
    instructions=_load_skill_instructions("fundamental_analysis"),
    output_model=FundamentalAnalysis,
    tools=(
        ResearchToolSpec(
            activity=get_price_history_activity,
            start_to_close_timeout=timedelta(seconds=30),
        ),
        ResearchToolSpec(
            activity=search_company_news_activity,
            start_to_close_timeout=timedelta(seconds=30),
        ),
        ResearchToolSpec(
            activity=search_sec_filings_activity,
            start_to_close_timeout=timedelta(minutes=15),
        ),
    ),
    default_objective_template=(
        "Assess the fundamentals of {symbol}, including operating performance, "
        "financial strength, management guidance, capital allocation, material "
        "company-specific developments, and risks that could affect future "
        "fundamentals."
    ),
    allowed_scope_kinds=("security",),
    required_scope_attributes=("symbol",),
)


_RESEARCH_SKILLS = {
    FUNDAMENTAL_ANALYSIS_SKILL.name: FUNDAMENTAL_ANALYSIS_SKILL,
}


def get_research_skill(name: str) -> ResearchSkill:
    try:
        return _RESEARCH_SKILLS[name]
    except KeyError as exc:
        available = ", ".join(sorted(_RESEARCH_SKILLS))
        raise ValueError(
            f"Unknown research skill {name!r}. Available skills: {available}"
        ) from exc


def list_research_skills() -> tuple[ResearchSkill, ...]:
    return tuple(_RESEARCH_SKILLS.values())
