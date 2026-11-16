"""App side of the synthetic cohort: shape it to the case, start/stop the background process, read results, compare.

The cohort runs in its own process (see app/vaccine/cohort.py) so the app stays responsive during the long run.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR
from app.models import Document
from app.services import fasttrack, priorities, vaccine
from app.vaccine import cohort as core

ALIVE_S = 45  # a run whose heartbeat is older than this is treated as not running


def profile_for_case(db: Session) -> tuple[dict, list[str]]:
    """Cohort settings derived from the records, with a plain-language reason for each. Everything else stays at the stated default."""
    p = dict(core.DEFAULT_PROFILE)
    why: list[str] = []
    texts = " ".join(fasttrack._doc_text(db, d.id) for d in db.query(Document).filter(Document.status == "indexed"))
    hist = next((f["text"] for f in fasttrack.findings(db) if f["key"] == "histology"), "")
    p["label"] = (hist or "squamous cell carcinoma, head and neck")[:120]
    why.append(f"Tumour type: {p['label']} (from the pathology report). Mutation counts are drawn from a wide spread around an assumed median of {p['median_burden']}, because no sequencing is on file.")
    if re.search(r"Sample Type\s*:\s*FFPE", texts, re.I):
        p["depth_median"] = 70
        why.append("Samples are FFPE blocks (from the Core report): lower and noisier sequencing depth is simulated.")
    scan = priorities.latest_scan(db)
    if scan is not None:
        p["purity"] = [0.15, 0.7]
        why.append(f"The latest scan ({scan.scan_date}) shows a small residual lesion after treatment: lower tumour purity is simulated, so variant allele fractions are lower.")
    why.append("HLA types are drawn from a panel of common alleles with equal weight (not population-calibrated). The patient's own HLA type is not on file.")
    why.append("Four data situations are tested on every simulated tumour: full exome + RNA + matched normal; no RNA; no matched normal; and a small gene panel only.")
    return p, why


def _status() -> dict:
    path = core.cohort_dir() / "status.json"
    if not path.exists():
        return {"state": "none"}
    st = json.loads(path.read_text(encoding="utf-8"))
    if st.get("state") in ("running", "building") and time.time() - st.get("heartbeat", 0) > ALIVE_S:
        st["state"] = "interrupted"
        st["message"] = "The run stopped unexpectedly. Start it again to resume where it left off."
    st["elapsed_s"] = round(max((st.get("heartbeat") or time.time()) - st.get("started", time.time()), 0))
    return st


def start(db: Session, n: int = 10000, workers: int = 10) -> dict:
    st = _status()
    if st["state"] in ("running", "building"):
        raise ValueError("A cohort run is already in progress.")
    if not core_available():
        raise ValueError("The binding predictor (MHCflurry) is not installed, so the cohort cannot be run.")
    n = max(100, min(int(n), 50000))
    profile, _ = profile_for_case(db)
    d = core.cohort_dir()
    pf = d / "profile.json"
    pf.write_text(json.dumps(profile), encoding="utf-8")
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0  # detached, so it survives an app reload
    log = open(d / "run.log", "ab")  # noqa: SIM115 - handed to the child
    subprocess.Popen([sys.executable, "-m", "app.vaccine.cohort", "run", "--n", str(n), "--workers", str(max(2, min(workers, 24))), "--profile", str(pf)],
                     stdout=log, stderr=log, creationflags=flags, cwd=str(BACKEND_DIR))
    return {"started": True, "n": n}


def core_available() -> bool:
    from app.vaccine import predictor  # noqa: PLC0415

    return predictor.available()


def stop() -> dict:
    (core.cohort_dir() / "STOP").write_text("stop", encoding="utf-8")
    (core.cohort_dir() / "AUDIT_STOP").write_text("stop", encoding="utf-8")
    return {"stopping": True}


def _audit_status() -> dict:
    path = core.cohort_dir() / "audit_status.json"
    if not path.exists():
        return {"state": "none"}
    st = json.loads(path.read_text(encoding="utf-8"))
    if st.get("state") == "running" and time.time() - st.get("heartbeat", 0) > ALIVE_S + 300:  # one model call can take minutes
        st["state"], st["message"] = "interrupted", "The review stopped unexpectedly. Start it again to resume."
    return st


def start_audit(n: int = 60, parallel: int = 2) -> dict:
    if (core.cohort_dir() / "summary.json").exists() is False:
        raise ValueError("Run the synthetic cohort first.")
    if _audit_status()["state"] == "running":
        raise ValueError("A model review is already in progress.")
    from app.services import llm  # noqa: PLC0415

    if not llm.status()["model_available"]:
        raise ValueError("LM Studio is not reachable or the model is not loaded.")
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0
    log = open(core.cohort_dir() / "audit.log", "ab")  # noqa: SIM115
    subprocess.Popen([sys.executable, "-m", "app.vaccine.audit", "--n", str(max(10, min(n, 400))), "--parallel", str(max(1, min(parallel, 4)))],
                     stdout=log, stderr=log, creationflags=flags, cwd=str(BACKEND_DIR))
    return {"started": True}


def _rows() -> list[dict]:
    return core.history(core.cohort_dir() / "scenarios.jsonl")


def compare(db: Session, rows: list[dict]) -> dict | None:
    """Where the patient's own result sits among similar synthetic tumours. Only when real mutations and HLA are loaded."""
    run = vaccine.latest(db, "patient")
    if run is None or not rows:
        return None
    res = run.result
    vars_ = res["inputs"]["variants_all"]
    n_in = len(vars_)
    has_rna, has_normal = any(v.get("tpm") is not None for v in vars_), any(v.get("normal_vaf") is not None for v in vars_)
    view = "full" if has_rna and has_normal else "no_rna" if has_normal else "no_normal" if has_rna else "panel_only"
    strong = len({c["variant_id"] for c in res["candidates"] if c["presentation_pct"] <= res["params"]["strong_pct"]})
    lo, hi = n_in * 0.7, n_in * 1.3
    sim = [r["views"][view]["strong_v"] for r in rows if lo <= r["views"][view]["in"] <= hi]
    if len(sim) < 30:
        sim = [r["views"][view]["strong_v"] for r in rows]
        basis = f"all {len(sim)} scenarios of the same data situation"
    else:
        basis = f"{len(sim)} synthetic tumours of similar size (about {int(lo)}–{int(hi)} mutations in the same data situation)"
    below = sum(1 for s in sim if s < strong) / len(sim)
    return {"view": view, "view_label": core.VIEW_LABEL[view], "mutations": n_in, "strong_variants": strong, "selected": len(res["selected"]), "percentile": round(below * 100),
            "median_similar": core._pct(sim, 0.5), "basis": basis}


def view(db: Session) -> dict:
    profile, why = profile_for_case(db)
    st = _status()
    path = core.cohort_dir() / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    rows: list[dict] = []
    if st["state"] != "none" and (summary is None or st["state"] in ("running", "interrupted")):
        rows = _rows()  # live view while the run is still going
        if len(rows) >= 100:
            summary = {"complete": False, **core.summarize(rows), "meta": st.get("meta")}
    if summary and not rows:
        rows = _rows()
    audit_path = core.cohort_dir() / "audit_summary.json"
    return {"status": st, "summary": summary, "situation": why, "profile": profile, "compare": compare(db, rows) if summary else None,
            "audit": {"status": _audit_status(), "summary": json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else None}}
