from dataclasses import asdict, dataclass, field

SEVERITIES = ("критично", "важно", "мелочь")


@dataclass
class Quote:
    text: str
    start: int
    end: int
    loc: str = ""


@dataclass
class Requirement:
    id: str
    doc_id: str
    type: str
    short: str
    section: str
    quote: Quote
    candidate_ids: list[str] = field(default_factory=list)


@dataclass
class Finding:
    id: str
    scope: str
    req_ids: list[str]
    criterion: str
    severity: str
    quotes: list[Quote]
    problem: str
    impact: str = ""
    fix: str = ""
    test_hint: str = ""
    role: str = ""
    edge: str = ""


@dataclass
class Question:
    id: str
    text: str
    quotes: list[Quote]
    blocks: str
    options: list[str]
    default: str
    addressee: str
    finding_ids: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class ChecklistRow:
    item: str
    value: str
    evidence: str


@dataclass
class Diagnostic:
    level: str
    code: str
    message: str
    hint: str = ""


@dataclass
class Report:
    passport: dict
    requirements: list[Requirement] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    checklist: list[ChecklistRow] = field(default_factory=list)
    verdict: dict = field(default_factory=dict)
    set_summary: list[dict] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    req_checks: dict = field(default_factory=dict)
    drops: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
