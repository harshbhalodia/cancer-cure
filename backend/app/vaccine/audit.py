"""Local-model review of the synthetic cohort (uses LM Studio).

The 10,000-scenario run itself is arithmetic on the binding predictor and does not need a language model. This stage is
where the local model does the judging the pipeline cannot do with fixed rules, and where it is *scored against known
answers* rather than trusted:

1. Reviewer audit. For a sample of simulated tumours WITHOUT a matched normal, the model reads the ranked shortlist and
   says which candidates look like inherited (germline) variants rather than tumour-specific ones. Because the tumour
   was simulated, we know which picks really were inherited, so the model's flags are scored (precision, recall) and
   compared with a one-line rule (VAF >= 0.40). If the model is no better than the rule, the app says so.
2. Cohort memo. The model writes a plain-language memo of the cohort results; every number in it must appear in the facts
   it was given, and it must pass the safety lint, otherwise it is rejected.

The model never changes a score or a selection. Run:  python -m app.vaccine.audit --n 60
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.vaccine import cohort, pipeline
from app.vaccine.pipeline import Params

RULE_VAF = 0.40

SYSTEM = (
    "/no_think\nYou are a careful bioinformatics reviewer checking a ranked research shortlist of tumour mutation candidates produced by a "
    "personalised-cancer-vaccine pipeline. ALL data is SYNTHETIC test data. Use ONLY the facts given.\n"
    "There is NO matched normal (blood) sample for this tumour, so the pipeline could not remove inherited (germline) variants. "
    "Inherited heterozygous variants appear in about half of all reads (VAF near 0.5), while tumour-specific variants usually have a lower VAF "
    "because the sample also contains normal cells.\n"
    "Decide which ranked candidates may be inherited or otherwise unreliable. Return ONLY a JSON object: "
    '{"flag_ranks": [integers, the # of each candidate you flag, possibly empty], "concerns": ["short strings"], "overall": "acceptable" or "needs_review"}. '
    "Do not claim that any vaccine will work or recommend any treatment."
)

MEMO_SYSTEM = (
    "/no_think\nYou explain results of a software stress-test to a worried family member and their oncologist, in plain language, in under 180 words. "
    "ALL data is synthetic: invented tumours, not the patient. Use ONLY the numbers in the facts, copied exactly. Say what the results suggest about which "
    "tests to ask for. Do NOT say a vaccine will work or recommend any treatment, drug or dose. End with: 'This is a software test on invented tumours, not advice about treatment.'"
)


def _paths() -> dict[str, Path]:
    d = cohort.cohort_dir()
    return {"status": d / "audit_status.json", "rows": d / "audit.jsonl", "summary": d / "audit_summary.json", "stop": d / "AUDIT_STOP", "table": d / "table.pkl"}


def cohort_facts(s: dict) -> str:
    lines = [f"Scenarios simulated: {s['scenarios']}", "Yield = mutations with at least one strongly presented peptide (median, 10th to 90th percentile):"]
    for v in s["views"].values():
        lines.append(f"- {v['label']}: median {v['strong_median']:g} ({v['strong_p10']:g} to {v['strong_p90']:g}); at least 3 candidates in {v['p_strong_ge']['3'] * 100:.0f}% of scenarios; none usable in {v['p_none'] * 100:.0f}%; "
                     f"inherited variants wrongly selected per shortlist {v['germline_selected_mean']:g}")
    lines.append("By number of mutations found (exome):")
    lines += [f"- {b['label']} mutations: median yield {b['full_strong_median']:g}; a small panel gives at least one candidate in {b['p_panel_strong_ge1'] * 100:.0f}%" for b in s["burden_bins"]]
    return "\n".join(lines)


def _numbers(text: str) -> set[str]:
    return {n.rstrip(".") for n in re.findall(r"\d[\d,]*\.?\d*", text)}


def check_memo(memo: str, facts: str) -> list[str]:
    from app.services import safety  # noqa: PLC0415

    allowed = {n.replace(",", "") for n in _numbers(facts)}
    problems = [f"number {n} is not in the facts" for n in sorted(_numbers(memo)) if n.replace(",", "") not in allowed and float(n.replace(",", "") or 0) > 10]
    if safety.lint(memo):
        problems.append("fails the safety lint")
    if "not advice about treatment" not in memo.lower():
        problems.append("missing the closing disclaimer")
    return problems


def make_memo(s: dict) -> dict:
    from app.services import llm  # noqa: PLC0415

    facts = cohort_facts(s)
    text, problems = "", ["not attempted"]
    for attempt in range(2):
        text = llm.chat(MEMO_SYSTEM, facts + ("" if attempt == 0 else "\n\nYour previous draft had these problems, fix them: " + "; ".join(problems)), timeout=300)
        problems = check_memo(text, facts)
        if not problems:
            break
    return {"text": text if not problems else "", "rejected_draft": text if problems else "", "problems": problems, "passed": not problems}


# ------------------------------------------------------------------------------------------------ audit
def _case(args: tuple) -> dict:
    """Regenerate scenario i without a matched normal, run the pipeline, ask the model, score against the planted truth."""
    i, seed, profile, table_path = args
    from app.services import llm, vaccine as vsvc  # noqa: PLC0415

    if "look" not in _C:
        with _LOCK:
            if "look" not in _C:
                with open(table_path, "rb") as f:
                    table = pickle.load(f)
                _C.update(look=cohort.Lookup(table, "lookup"), alleles=sorted(table), pool=cohort.make_pool())
    sc = cohort.make_scenario(i, seed, _C["pool"], profile, _C["alleles"])
    res = pipeline.execute(sc["views"]["no_normal"], sc["hla"], Params(), _C["look"], dataset="synthetic")
    sel = res["selected"]
    truth = [r for r, c in enumerate(sel, 1) if sc["germline"].get(c["variant_id"])]
    rule = [r for r, c in enumerate(sel, 1) if (c["vaf"] or 0) >= RULE_VAF]
    out = {"i": i, "n_selected": len(sel), "truth": truth, "rule": rule, "flags": [], "concerns": [], "overall": "", "error": "", "secs": 0.0}
    if not sel:
        return out
    t0 = time.time()
    try:
        got = llm.chat_json(SYSTEM, vsvc.facts_for(res, "synthetic"), timeout=300)
        flags = got.get("flag_ranks") or []
        out["flags"] = sorted({int(x) for x in flags if str(x).lstrip("-").isdigit() and 1 <= int(x) <= len(sel)})
        out["concerns"] = [str(c)[:200] for c in (got.get("concerns") or [])][:4]
        out["overall"] = str(got.get("overall", ""))[:20]
    except Exception as exc:  # noqa: BLE001 - recorded per case, the audit continues
        out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    out["secs"] = round(time.time() - t0, 1)
    return out


_C: dict = {}
_LOCK = threading.Lock()


def _score(cases: list[dict], key: str) -> dict:
    tp = fp = fn = 0
    pos = [c for c in cases if c["truth"]]
    neg = [c for c in cases if not c["truth"]]
    for c in cases:
        t, f = set(c["truth"]), set(c[key])
        tp, fp, fn = tp + len(t & f), fp + len(f - t), fn + len(t - f)
    prec, rec = tp / (tp + fp) if tp + fp else 0.0, tp / (tp + fn) if tp + fn else 0.0
    return {"true_flags": tp, "false_flags": fp, "missed": fn, "precision": round(prec, 3), "recall": round(rec, 3),
            "f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0,
            "cases_with_inherited_caught": round(sum(1 for c in pos if set(c["truth"]) & set(c[key])) / max(len(pos), 1), 3),
            "clean_cases_with_false_alarm": round(sum(1 for c in neg if c[key]) / max(len(neg), 1), 3)}


def summarize_audit(cases: list[dict]) -> dict:
    ok = [c for c in cases if not c["error"] and c["n_selected"]]
    model, rule = _score(ok, "flags"), _score(ok, "rule")
    better = model["f1"] > rule["f1"] + 0.02
    return {"cases": len(cases), "answered": len(ok), "failed": sum(1 for c in cases if c["error"]), "with_inherited": sum(1 for c in ok if c["truth"]),
            "model": model, "rule": rule, "median_secs": sorted(c["secs"] for c in ok)[len(ok) // 2] if ok else 0, "model_better_than_rule": better,
            "needs_review_rate": round(sum(1 for c in ok if c["overall"] == "needs_review") / max(len(ok), 1), 3),
            "verdict": ("The model's flags beat the simple VAF rule on this test." if better else
                        "The model was no better than the simple rule (VAF at least 0.40) on this test, so it adds no reliable value for this job." if ok else "No cases were answered.")}


def _write(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj), encoding="utf-8")
    os.replace(tmp, path)


def run(n: int, seed: int, parallel: int) -> None:
    p = _paths()
    p["stop"].unlink(missing_ok=True)
    started = time.time()

    def st(state: str, **kw) -> None:
        _write(p["status"], {"state": state, "pid": os.getpid(), "heartbeat": time.time(), "started": started, "target": n + 1, **kw})

    try:
        cstat = json.loads((cohort.cohort_dir() / "status.json").read_text(encoding="utf-8"))
        profile = cstat["profile"]
        rows = cohort.history(cohort.cohort_dir() / "scenarios.jsonl")
        if not rows or not p["table"].exists():
            st("failed", message="Run the 10K cohort first.", done=0)
            return
        cfg_key = f"{cstat['key']}:{n}:{seed}"
        prev = json.loads(p["status"].read_text(encoding="utf-8")) if p["status"].exists() else {}
        resume = prev.get("cfg") == cfg_key and p["rows"].exists()
        if not resume:
            p["rows"].unlink(missing_ok=True)
        rng = random.Random(seed)
        pos = [r["i"] for r in rows if r["views"]["no_normal"]["germline_selected"] > 0]
        neg = [r["i"] for r in rows if r["views"]["no_normal"]["germline_selected"] == 0 and r["views"]["no_normal"]["selected"] > 0]
        pick = sorted(rng.sample(pos, min(n // 2, len(pos))) + rng.sample(neg, min(n - n // 2, len(neg))))
        done_ids = {c["i"] for c in cohort.history(p["rows"])}
        todo = [i for i in pick if i not in done_ids]
        st("running", message="Asking the local model to review shortlists", done=len(done_ids), cfg=cfg_key)
        last = time.time()
        with ThreadPoolExecutor(parallel) as ex, open(p["rows"], "a", encoding="utf-8") as out:
            for case in ex.map(_case, [(i, seed, profile, str(p["table"])) for i in todo]):
                out.write(json.dumps(case) + "\n")
                out.flush()
                done_ids.add(case["i"])
                if time.time() - last > 3:
                    last = time.time()
                    st("running", message="Asking the local model to review shortlists", done=len(done_ids), cfg=cfg_key)
                if p["stop"].exists():
                    ex.shutdown(wait=False, cancel_futures=True)
                    break
        cases = cohort.history(p["rows"])
        summ = summarize_audit(cases)
        st("running", message="Writing the cohort memo with the local model", done=len(cases), cfg=cfg_key)
        try:
            summ["memo"] = make_memo(json.loads((cohort.cohort_dir() / "summary.json").read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            summ["memo"] = {"text": "", "problems": [f"{type(exc).__name__}: {str(exc)[:160]}"], "passed": False}
        summ["target"] = len(pick)
        _write(p["summary"], summ)
        st("stopped" if p["stop"].exists() else "done", message=f"Reviewed {len(cases)} shortlists", done=len(cases), cfg=cfg_key)
    except Exception as exc:  # noqa: BLE001
        st("failed", message=f"{type(exc).__name__}: {exc}", done=0)
        raise


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--parallel", type=int, default=2)
    a = ap.parse_args()
    run(a.n, a.seed, a.parallel)


if __name__ == "__main__":
    main()
