"""Care advisor packs: declarative YAML that turns the patient's record into a plan, run the LocalAgents way.

A pack is data, never code: a manifest plus scenario questions, executed by one trusted runner.

  id, name, publisher, version        identity (a higher version replaces a lower one with the same id)
  kind        plan | checklist | packet
  summary     one plain sentence shown to the user
  triggers / examples                 phrases and ready-made questions (shown as suggestions)
  inputs      the data scopes the pack may read (see SCOPES) — nothing else is sent to the model
  scenarios   [{id, description}] each answered by a narrow specialist call from the facts, then combined
  guardrails  rules added to every call
  output      {sections: [{id, name}]} the layout of the lead's answer
  specialist_system_prompt / lead_system_prompt / disclaimer / follow_ups     optional overrides

Same principles as Loonie's advisor packs: facts come from deterministic code; the model only writes wording;
a validator checks the result (no treatment advice, no invented figures, no invented [R#] references) and
a deterministic fallback is used instead of anything that fails the checks.

Two places are read: `app/advisor_packs/` (bundled) and `<data dir>/advisors/` (yours; overrides a bundled pack
with the same id). Invalid packs are skipped and listed by `load_problems()`.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CaseEntry, ClinicalEvent, Document, Fact, Plan, Recommendation, Scan
from app.services import casefile, llm, readiness, recommendations, safety, wellness
from app.services.prompts import PROMPT_VERSION

log = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).resolve().parents[1] / "advisor_packs"
KINDS = ("plan", "checklist", "packet")
_ID = re.compile(r"^[a-z0-9][a-z0-9_.\-]{2,79}$")
MAX_SCENARIOS = 6
SCOPE_CHARS = 5000

DEFAULT_SPECIALIST = (
    "You are a specialist within a cancer-care companion. Answer ONLY from the verified facts you are given. "
    "Never invent a date, number, test, result or recommendation, and say plainly when something is not in the record. "
    "Treat missing information as unknown, not as negative."
)
DEFAULT_LEAD = (
    "You are the lead advisor writing one clear plan for a patient and their caregiver. You have verified facts and "
    "specialist notes. Use only what they contain. Write in plain language with short sentences. "
    "End with exactly this line: {disclaimer}"
)
DEFAULT_DISCLAIMER = (
    "Information to help you prepare for conversations with your care team, built from your own records. "
    "It is not medical advice; treatment decisions belong to your oncologist."
)
UNIVERSAL_RULES = (
    "Never recommend starting, stopping, delaying, changing or dosing any treatment or medicine, and never diagnose. "
    "Phrase every suggested step as something to ask or confirm with the care team. "
    "Advisor recommendations are listed with a [R#] tag: cite them with exactly that tag and never invent a tag. "
    "Keep the records' own hedging words ('appears', 'could be'). Give the date whenever you mention a past event."
)


class PackError(ValueError):
    pass


@dataclass
class Pack:
    id: str
    name: str
    publisher: str
    version: str
    kind: str
    summary: str
    triggers: list[str]
    examples: list[str]
    inputs: list[str]
    scenarios: list[dict]
    guardrails: list[str]
    sections: list[dict]
    specialist_system_prompt: str
    lead_system_prompt: str
    disclaimer: str
    follow_ups: list[str]
    source: str = "bundled"
    allow_figures: bool = False  # lifestyle packs may use general figures such as "5 minutes"; clinical packs may not
    extra: dict = field(default_factory=dict)


# ------------------------------------------------------------------------------------ scopes
def _today() -> str:
    return date.today().isoformat()


def scope_today(db: Session) -> str:
    return f"Today's date: {_today()}"


def scope_case_now(db: Session) -> str:
    values, meta = casefile.derive(db)
    lines = []
    for f in casefile.ORDER:
        if values.get(f):
            when = meta[f].get("as_of") or "date unknown"
            lines.append(f"- {casefile.LABELS[f]} (as of {when}): {values[f]}")
    return "\n".join(lines) or "(the case file is empty)"


def scope_journey(db: Session) -> str:
    return casefile.journey_text(db) or "(no dated events recorded yet)"


def scope_progress(db: Session) -> str:
    prog = readiness.progress(db)
    if not prog["scans"]:
        return "(no scan measurements confirmed yet)"
    lines = []
    for s in prog["scans"]:
        head = f"- {s['modality'] or 'Scan'} {s['date'] or '(date unknown)'}"
        if s["comparator_date"]:
            head += f" compared with {s['comparator_modality'] or 'previous study'} {s['comparator_date']}"
        lines.append(head)
        if s["reported"]["label"]:
            lines.append(f"  report states: {s['reported']['label']}")
        if s["computed"]:
            c = s["computed"]
            lines.append(f"  app-computed target sum: {c['sum_prior']} mm -> {c['sum_now']} mm ({c['pct_change']:+g}%), {c['category_label']}")
        for f in s["findings"]:
            lines.append(f"  finding ({f['certainty']}): {f['text']}")
    return "\n".join(lines)


def scope_recommendations(db: Session) -> str:
    return recommendations.context_lines(db) or "(no open advisor recommendations recorded)"


def scope_readiness(db: Session) -> str:
    r = readiness.readiness(db)
    lines = []
    for d in r["decisions"]:
        if d["status"] != "ready":
            lines.append(f"- {d['title']}: {d['status']}; missing {', '.join(u['label'] for u in d['unmet'])}")
    for g in r["gaps"][:8]:
        lines.append(f"- gap: {g['label']} — {g['why']}" + (f" Ask: {g['ask']}" if g["ask"] else ""))
    return "\n".join(lines) or "(nothing missing from the checklist)"


def scope_insights(db: Session) -> str:
    items = readiness.insights(db)[:10]
    return "\n".join(f"- [{i['severity']}] {i['title']}: {i['detail']}" for i in items) or "(nothing flagged)"


def scope_documents(db: Session) -> str:
    docs = db.query(Document).order_by(Document.doc_date.desc(), Document.id.desc()).all()
    lines = []
    for d in docs:
        ai = " (AI-read scan)" if d.text_source == "vision_ocr" else ""
        lines.append(f"- D{d.id}: {d.filename} — {d.doc_type}, {d.doc_date or 'date unknown'}{ai}")
    return "\n".join(lines[:40]) or "(no documents)"


def scope_wellbeing(db: Session) -> str:
    return wellness.strategy_facts(db)


SCOPES: dict[str, Callable[[Session], str]] = {
    "today": scope_today, "case_now": scope_case_now, "journey": scope_journey, "progress": scope_progress,
    "recommendations": scope_recommendations, "readiness": scope_readiness, "insights": scope_insights,
    "documents": scope_documents, "wellbeing": scope_wellbeing,
}


def gather(db: Session, inputs: list[str]) -> dict[str, str]:
    """Only the declared scopes are read, each capped; an unknown scope refuses the run (fail closed)."""
    unknown = [s for s in inputs if s not in SCOPES]
    if unknown:
        raise PackError(f"Unknown data scope(s): {', '.join(unknown)}")
    return {s: SCOPES[s](db)[:SCOPE_CHARS] for s in dict.fromkeys(["today", *inputs])}


def facts_text(facts: dict[str, str]) -> str:
    return "\n\n".join(f"## {name}\n{body}" for name, body in facts.items())


# ------------------------------------------------------------------------------------ loading
def validate_pack(raw: object, source: str = "bundled") -> Pack:
    if not isinstance(raw, dict):
        raise PackError("A pack must be a YAML mapping.")
    pid = str(raw.get("id") or "").strip()
    if not _ID.match(pid):
        raise PackError("id must be 3-80 characters: lowercase letters, digits, '.', '_' or '-'.")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise PackError("A pack needs a name.")
    kind = str(raw.get("kind") or "plan")
    if kind not in KINDS:
        raise PackError(f"kind must be one of {', '.join(KINDS)}.")
    inputs = [str(i) for i in raw.get("inputs") or []]
    bad = [i for i in inputs if i not in SCOPES or i == "today"]
    if not inputs or bad:
        raise PackError(f"inputs must be a non-empty list of: {', '.join(s for s in SCOPES if s != 'today')}." + (f" Unknown: {', '.join(bad)}." if bad else ""))
    scenarios = raw.get("scenarios") or []
    if not isinstance(scenarios, list) or len(scenarios) > MAX_SCENARIOS:
        raise PackError(f"scenarios must be a list of at most {MAX_SCENARIOS}.")
    clean_scen = []
    for s in scenarios:
        if not isinstance(s, dict) or not s.get("id") or not s.get("description"):
            raise PackError("Each scenario needs an id and a description.")
        clean_scen.append({"id": str(s["id"]), "description": str(s["description"]).strip()})
    sections = ((raw.get("output") or {}).get("sections")) or []
    clean_sections = [{"id": str(s.get("id") or i), "name": str(s["name"])} for i, s in enumerate(sections) if isinstance(s, dict) and s.get("name")]
    disclaimer = str(raw.get("disclaimer") or DEFAULT_DISCLAIMER).strip()
    return Pack(
        id=pid, name=name[:100], publisher=str(raw.get("publisher") or "")[:100], version=str(raw.get("version") or "0"),
        kind=kind, summary=str(raw.get("summary") or "").strip()[:400],
        triggers=[str(t) for t in raw.get("triggers") or []], examples=[str(e) for e in raw.get("examples") or []],
        inputs=inputs, scenarios=clean_scen, guardrails=[str(g) for g in raw.get("guardrails") or []],
        sections=clean_sections,
        specialist_system_prompt=str(raw.get("specialist_system_prompt") or DEFAULT_SPECIALIST).strip(),
        lead_system_prompt=str(raw.get("lead_system_prompt") or DEFAULT_LEAD).strip(),
        disclaimer=disclaimer, follow_ups=[str(f) for f in raw.get("follow_ups") or []], source=source,
        allow_figures=bool(raw.get("allow_general_figures", False)),
    )


_problems: list[dict] = []


def load_packs() -> dict[str, Pack]:
    """Bundled packs, then yours; the higher version wins, yours on a tie."""
    global _problems
    _problems = []
    found: dict[str, Pack] = {}
    for source, folder in (("bundled", BUILTIN_DIR), ("yours", get_settings().data_dir / "advisors")):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.y*ml")):
            try:
                pack = validate_pack(yaml.safe_load(path.read_text(encoding="utf-8")), source)
            except (PackError, yaml.YAMLError, OSError) as exc:
                _problems.append({"file": path.name, "problem": str(exc)})
                log.warning("skipping advisor pack %s: %s", path.name, exc)
                continue
            current = found.get(pack.id)
            if current is None or _version_key(pack.version) >= _version_key(current.version):
                found[pack.id] = pack
    return found


def load_problems() -> list[dict]:
    load_packs()
    return list(_problems)


def _version_key(v: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.\-]", v))


# ------------------------------------------------------------------------------------ checks
_NUM = re.compile(r"\d+(?:[.,/\-:]\d+)*")


def _number_parts(text: str) -> set[str]:
    parts: set[str] = set()
    for tok in _NUM.findall(text):
        parts.add(tok)
        parts.update(p for p in re.split(r"[.,/\-:]", tok) if p)
    return parts


def validate_output(text: str, facts: str, known_rec_ids: set[int], allow_figures: bool = False) -> tuple[str, list[str]]:
    """Returns (text with unknown [R#] tags removed, violations). A non-empty list means the answer is not acceptable."""
    violations = list(safety.lint(text))

    def keep_tag(m: re.Match[str]) -> str:
        return m.group(0) if int(m.group(1)) in known_rec_ids else ""

    cleaned = re.sub(r"\[R(\d+)\]", keep_tag, text)
    if cleaned != text:
        violations.append("invented-reference")
    body = re.sub(r"(?m)^\s*\d+[.)]\s+", "", cleaned)  # list numbering is not a figure
    body = re.sub(r"\[R\d+\]", "", body)
    allowed = _number_parts(facts)
    invented = [] if allow_figures else sorted({tok for tok in _NUM.findall(body) if tok not in allowed and not all(p in allowed for p in re.split(r"[.,/\-:]", tok) if p)})
    if invented:
        violations.append("invented-figure: " + ", ".join(invented[:6]))
    return cleaned, violations


def fallback_markdown(pack: Pack, facts: dict[str, str]) -> str:
    """The plan assembled directly from the facts, with no model: used when the model is unavailable or its answer fails the checks."""
    parts = [f"## {pack.name}", ""]
    labels = {
        "case_now": "Where things stand now", "journey": "The journey so far", "progress": "What the scans show",
        "recommendations": "What your advisors recommended (still open)", "readiness": "Checks and gaps",
        "insights": "Points to raise with your care team", "documents": "Documents on file", "wellbeing": "Your daily plan and how it is going",
    }
    for scope in pack.inputs:
        body = facts.get(scope, "").strip()
        if body and not body.startswith("("):
            parts += [f"### {labels.get(scope, scope)}", body, ""]
    parts += [pack.disclaimer]
    return "\n".join(parts).strip()


def fingerprint(db: Session, inputs: list[str] | None = None) -> str:
    """Changes whenever anything a plan could be built from changes (daily-life data only counts for packs that read it)."""
    def last(model):
        row = db.query(model.id).order_by(model.id.desc()).first()
        return f"{row[0] if row else 0}:{db.query(model).count()}"

    open_recs = db.query(Recommendation).filter_by(status="open").count()
    done_recs = db.query(Recommendation).filter(Recommendation.status != "open").count()
    parts = [last(CaseEntry), last(ClinicalEvent), last(Recommendation), last(Scan), last(Document), last(Fact), f"{open_recs}/{done_recs}"]
    if inputs and "wellbeing" in inputs:
        parts.append(wellness.fingerprint_part(db))
    return "|".join(parts)


# ------------------------------------------------------------------------------------ running
@dataclass
class PackRun:
    markdown: str
    notes: list[dict]
    scopes: list[str]
    flags: list[str]
    used_fallback: bool


def _rules(pack: Pack) -> str:
    rules = [UNIVERSAL_RULES, *pack.guardrails]
    return "\n\nRules you must follow:\n" + "\n".join(f"- {r}" for r in rules)


def _lead_prompt(pack: Pack) -> str:
    prompt = pack.lead_system_prompt.replace("{disclaimer}", pack.disclaimer)
    if pack.sections:
        layout = "\n".join(f"## {s['name']}" for s in pack.sections)
        prompt += f"\n\nLay the answer out with exactly these headings, in this order, skipping a section only if it truly has nothing:\n{layout}"
    return prompt + _rules(pack)


def run_pack(db: Session, pack: Pack, progress: Callable[[int, int, str], None] | None = None,
             wait: Callable[[], None] | None = None) -> PackRun:
    facts = gather(db, pack.inputs)
    text = facts_text(facts)
    known_ids = {row.id for row in db.query(Recommendation.id)} if "recommendations" in pack.inputs else set()
    total = len(pack.scenarios) + 1
    flags: list[str] = []
    notes: list[dict] = []
    wait = wait or (lambda: None)
    try:
        for n, scenario in enumerate(pack.scenarios, start=1):
            wait()
            if progress:
                progress(n - 1, total, scenario["id"])
            note = llm.chat(
                "/no_think\n" + pack.specialist_system_prompt + _rules(pack),
                f"Question: {scenario['description']}\n\nVerified facts:\n{text}",
            ).strip()
            notes.append({"id": scenario["id"], "description": scenario["description"], "note": note})
        wait()
        if progress:
            progress(total - 1, total, "lead")
        lead_input = f"Verified facts:\n{text}\n\n" + "\n\n".join(f"[{n['id']}] {n['description']}\n{n['note']}" for n in notes)
        answer = llm.chat(_lead_prompt(pack), lead_input).strip()
        cleaned, violations = validate_output(answer, text + "\n" + "\n".join(n["note"] for n in notes), known_ids, pack.allow_figures)
        if violations:
            flags.append("first draft changed: " + "; ".join(violations))
            retry = (
                f"{lead_input}\n\nYour previous draft broke these rules: {'; '.join(violations)}. Rewrite it using only figures, "
                "dates and [R#] tags that appear in the facts, with no treatment advice and no diagnosis."
            )
            answer = llm.chat(_lead_prompt(pack), retry).strip()
            cleaned, violations = validate_output(answer, text + "\n" + "\n".join(n["note"] for n in notes), known_ids, pack.allow_figures)
        if violations:
            flags.append("fallback used: " + "; ".join(violations))
            return PackRun(fallback_markdown(pack, facts), notes, list(facts), flags, True)
        if pack.disclaimer not in cleaned:
            cleaned = f"{cleaned}\n\n{pack.disclaimer}"
        return PackRun(cleaned, notes, list(facts), flags, False)
    except llm.LLMError as exc:
        flags.append(f"fallback used: {exc}")
        return PackRun(fallback_markdown(pack, facts), notes, list(facts), flags, True)


def save_plan(db: Session, pack: Pack, run: PackRun) -> Plan:
    from app.config import get_settings as _s

    plan = Plan(pack_id=pack.id, title=pack.name, markdown=run.markdown, notes=run.notes, scopes=run.scopes, flags=run.flags,
                fingerprint=fingerprint(db, pack.inputs), used_fallback=run.used_fallback, model=_s().lm_model + " / " + PROMPT_VERSION)
    db.add(plan)
    db.commit()
    return plan


def latest_plan(db: Session, pack_id: str) -> dict | None:
    plan = db.query(Plan).filter_by(pack_id=pack_id).order_by(Plan.id.desc()).first()
    if plan is None:
        return None
    pack = load_packs().get(pack_id)
    return {
        "id": plan.id, "pack_id": plan.pack_id, "title": plan.title, "markdown": plan.markdown, "notes": plan.notes,
        "flags": plan.flags, "used_fallback": plan.used_fallback, "created_at": plan.created_at.isoformat(),
        "stale": plan.fingerprint != fingerprint(db, pack.inputs if pack else None), "model": plan.model,
    }


def describe(db: Session, pack: Pack) -> dict:
    return {
        "id": pack.id, "name": pack.name, "publisher": pack.publisher, "version": pack.version, "kind": pack.kind,
        "summary": pack.summary, "examples": pack.examples, "follow_ups": pack.follow_ups, "source": pack.source,
        "inputs": pack.inputs, "scenarios": [s["description"] for s in pack.scenarios], "latest": latest_plan(db, pack.id),
    }
