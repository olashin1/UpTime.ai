"""Offline eval: run one assessor mode over every case and save predictions.

    backend/.venv/Scripts/python eval/run_eval.py --mode rules
    backend/.venv/Scripts/python eval/run_eval.py --mode llm
    backend/.venv/Scripts/python eval/run_eval.py --mode llm_repo --ref <commit-sha>

Writes eval/results/<mode>.json. Gemini calls are counted in eval/results/gemini_calls.log.
"""

import argparse
import json
import os
import time

from common import REPO, RESULTS_DIR, SOURCE_ROOT, calls_used, configure_budget, incident_message, load_cases, score_row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["rules", "llm", "llm_repo"], required=True)
    parser.add_argument("--ref", default="oncall-improvements", help="git ref to read the fixture from")
    parser.add_argument("--min-interval", type=float, default=4.5, help="seconds between LLM cases")
    parser.add_argument("--budget", type=int, default=170)
    args = parser.parse_args()

    configure_budget(args.mode, args.budget)
    os.environ["REPO_SOURCE_ROOT"] = SOURCE_ROOT

    from app.config import settings

    settings.repo_source_root = SOURCE_ROOT
    from app.services.severity_service import assess

    cases = load_cases()
    rows = []
    before = calls_used()

    for case in cases:
        started = time.perf_counter()
        result = assess(incident_message(case, REPO, args.ref), args.mode)
        rows.append({
            "id": case["id"],
            "label": case["label"],
            "predicted": {"severity": result.severity, "escalate": result.escalate},
            **score_row(case, result.severity, result.escalate),
            "reason": result.reason,
            "assessor": result.assessor,
            "model": result.model,
            "context_files": result.context_files,
            "wall_ms": int((time.perf_counter() - started) * 1000),
        })
        mark = "ok " if rows[-1]["severity_correct"] and rows[-1]["escalate_correct"] else "ERR"
        print(f"{mark} {case['id']} label={case['label']} got={rows[-1]['predicted']} [{result.assessor}]", flush=True)

        if args.mode != "rules":
            time.sleep(max(0.0, args.min_interval - (time.perf_counter() - started)))

    out = {
        "mode": args.mode,
        "ref": args.ref,
        "repo": REPO if args.mode == "llm_repo" else None,
        "source_root": SOURCE_ROOT if args.mode == "llm_repo" else None,
        "model": settings.gemini_model if args.mode != "rules" else None,
        "gemini_calls": calls_used() - before,
        "fallbacks": sum(row["assessor"].endswith("fallback_rules") for row in rows),
        "rows": rows,
    }
    (RESULTS_DIR / f"{args.mode}.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    sev = sum(r["severity_correct"] for r in rows)
    esc = sum(r["escalate_correct"] for r in rows)
    print(f"{args.mode}: severity {sev}/{len(rows)}, escalation {esc}/{len(rows)}, "
          f"gemini calls {out['gemini_calls']}, fallbacks {out['fallbacks']}")


if __name__ == "__main__":
    main()
