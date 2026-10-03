"""Pydantic models: portfolio content schema and playground request/response shapes."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["swe", "backend", "ai", "qa"]
Status = Literal["live", "completed", "in-development", "resume"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- portfolio content ----------
class Profile(Strict):
    name: str
    headline: str
    value_prop: str
    summary: str
    email: str
    location: str
    github: str
    linkedin: str
    languages: list[str]
    resume_file: Optional[str] = None


class Claim(Strict):
    id: str
    title: str
    text: str
    roles: list[Role]
    project: str
    demo: Optional[Literal["rag", "tickets", "flaky"]] = None


class Project(Strict):
    id: str
    title: str
    short: str
    status: Status
    featured: bool
    url: Optional[str] = None
    github: Optional[str] = None
    art: str
    roles: list[Role]
    problem: Optional[str] = None
    approach: str
    decisions: list[str]
    stack: list[str]
    reported: list[str] = []
    evidence: str


class Experience(Strict):
    role: str
    company: str
    place: str
    start: str
    end: str
    points: list[str] = []


class SkillItem(Strict):
    name: str
    project: Optional[str] = None


class SkillGroup(Strict):
    group: str
    items: list[SkillItem]


class Education(Strict):
    degree: str
    school: str
    years: str
    cgpa: str


class RoleDef(Strict):
    id: Role
    label: str


class Portfolio(Strict):
    profile: Profile
    status_labels: dict[str, str]
    roles: list[RoleDef]
    claims: list[Claim]
    projects: list[Project]
    experience: list[Experience]
    skills: list[SkillGroup]
    education: Education
    certifications: list[str]

    @model_validator(mode="after")
    def _refs_resolve(self) -> "Portfolio":
        ids = {p.id for p in self.projects}
        refs = [c.project for c in self.claims]
        refs += [i.project for g in self.skills for i in g.items if i.project]
        missing = sorted(set(refs) - ids)
        if missing:
            raise ValueError(f"unknown project ids referenced: {missing}")
        return self


# ---------- RAG demo ----------
class RagRequest(Strict):
    question: str = Field(min_length=3, max_length=200)


class RagStep(Strict):
    name: str
    detail: str
    data: dict = {}


class RagResponse(Strict):
    illustrative: bool = True
    steps: list[RagStep]
    answer: str
    citations: list[str]


# ---------- Ticket hold demo ----------
class TicketAction(Strict):
    at: int = Field(ge=0, le=100_000, description="virtual clock, seconds")
    op: Literal["hold", "confirm", "release"]
    user: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9 _-]{1,20}$")
    qty: int = Field(default=1, ge=1, le=4)
    hold_id: Optional[str] = Field(default=None, pattern=r"^H[0-9]{1,3}$")

    @model_validator(mode="after")
    def _shape(self) -> "TicketAction":
        if self.op == "hold" and not self.user:
            raise ValueError("hold requires user")
        if self.op != "hold" and not self.hold_id:
            raise ValueError(f"{self.op} requires hold_id")
        return self


class TicketRequest(Strict):
    capacity: int = Field(ge=1, le=20)
    ttl: int = Field(ge=5, le=600, description="hold lifetime, seconds")
    now: int = Field(ge=0, le=100_000, description="settle expiries up to this time")
    actions: list[TicketAction] = Field(max_length=60)

    @model_validator(mode="after")
    def _ordered(self) -> "TicketRequest":
        times = [a.at for a in self.actions]
        if times != sorted(times):
            raise ValueError("actions must be in non-decreasing time order")
        if times and self.now < times[-1]:
            raise ValueError("now must be >= the last action time")
        return self


class LedgerEntry(Strict):
    seq: int
    at: int
    kind: str
    ref: str
    debit: str
    credit: str
    qty: int


class TicketOutcome(Strict):
    seq: int
    at: int
    text: str
    ok: bool


class TicketResponse(Strict):
    illustrative: bool = True
    ledger: list[LedgerEntry]
    outcomes: list[TicketOutcome]
    balances: dict[str, int]
    active_holds: list[dict]
    balanced: bool


# ---------- Flaky analyzer ----------
class TestRun(Strict):
    __test__ = False  # not a pytest class
    test: str = Field(min_length=1, max_length=80)
    commit: str = Field(min_length=1, max_length=40)
    outcome: Literal["pass", "fail"]


class FlakyRequest(Strict):
    runs: list[TestRun] = Field(min_length=1, max_length=500)


class FlakyVerdict(Strict):
    test: str
    verdict: Literal["flaky", "consistently failing", "likely regression", "stable"]
    runs: int
    failures: int
    mixed_commits: list[str]
    reason: str


class FlakyResponse(Strict):
    illustrative: bool = True
    rule: list[str]
    verdicts: list[FlakyVerdict]
    summary: dict[str, int]
