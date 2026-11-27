"""Score a themis report.json against the golden list of planted defects.

Usage: python eval/score.py <report.json> [--golden eval/golden.toml] [--md out.md]
"""
import argparse
import json
import sys
import tomllib
from pathlib import Path

SEVERITIES = ("критично", "важно", "мелочь")
DEFAULT_GOLDEN = Path(__file__).with_name("golden.toml")
LINE_SLACK = 1


def load_golden(path) -> list[dict]:
    with open(path, "rb") as f:
        return tomllib.load(f)["defect"]


def _quote_ranges(quotes) -> list[tuple[int, int]]:
    out = []
    for q in quotes or []:
        start = q.get("start")
        if not isinstance(start, int) or start <= 0:
            continue
        end = q.get("end")
        if not isinstance(end, int) or end < start:
            end = start
        out.append((start, end))
    return out


def lines_overlap(quotes, defect) -> bool:
    for start, end in _quote_ranges(quotes):
        for line in defect["lines"]:
            if start - LINE_SLACK <= line <= end + LINE_SLACK:
                return True
    return False


def keywords_match(blob: str, defect) -> bool:
    blob = blob.lower()
    return all(any(stem.lower() in blob for stem in group) for group in defect.get("keywords", []))


def _blob(parts, quotes) -> str:
    texts = [p or "" for p in parts] + [(q.get("text") or "") for q in quotes or []]
    return "\n".join(texts).lower()


def covers(parts, quotes, defect) -> bool:
    return lines_overlap(quotes, defect) and keywords_match(_blob(parts, quotes), defect)


def _ratio(num, den):
    return num / den if den else None


def score(report: dict, golden: list[dict]) -> dict:
    findings = report.get("findings") or []
    questions = report.get("questions") or []

    found_by = {d["id"]: [] for d in golden}
    sev_of = {}
    asked_by = {d["id"]: [] for d in golden}
    unmatched = []

    for f in findings:
        parts = (f.get("problem"), f.get("impact"), f.get("fix"))
        hit = False
        for d in golden:
            if covers(parts, f.get("quotes"), d):
                found_by[d["id"]].append(f.get("id", "?"))
                sev_of.setdefault(d["id"], []).append(f.get("severity", ""))
                hit = True
        if not hit:
            unmatched.append({"id": f.get("id", "?"), "severity": f.get("severity", ""),
                              "problem": f.get("problem", "")})

    for q in questions:
        for d in golden:
            if covers((q.get("text"),), q.get("quotes"), d):
                asked_by[d["id"]].append(q.get("id", "?"))

    found_ids = {d["id"] for d in golden if found_by[d["id"]]}
    asked_ids = {d["id"] for d in golden if asked_by[d["id"]]}

    by_sev = {}
    for sev in SEVERITIES:
        ids = [d["id"] for d in golden if d["severity"] == sev]
        hits = [i for i in ids if i in found_ids]
        by_sev[sev] = {"found": len(hits), "total": len(ids), "recall": _ratio(len(hits), len(ids))}

    crit_ids = [d["id"] for d in golden if d["severity"] == "критично"]
    crit_as_crit = [i for i in crit_ids if "критично" in sev_of.get(i, [])]

    must = [d["id"] for d in golden if d.get("must_find")]
    must_missed = [i for i in must if i not in found_ids]

    n_matched = len(findings) - len(unmatched)
    return {
        "golden_total": len(golden),
        "found": len(found_ids),
        "recall": _ratio(len(found_ids), len(golden)),
        "by_severity": by_sev,
        "critical_as_critical": len(crit_as_crit),
        "critical_wrong_severity": [i for i in crit_ids if i in found_ids and i not in crit_as_crit],
        "must_total": len(must),
        "must_found": len(must) - len(must_missed),
        "must_recall": _ratio(len(must) - len(must_missed), len(must)),
        "must_missed": must_missed,
        "findings_total": len(findings),
        "findings_matched": n_matched,
        "precision": _ratio(n_matched, len(findings)),
        "unmatched": unmatched,
        "questions_total": len(questions),
        "asked": len(asked_ids),
        "asked_only": sorted(asked_ids - found_ids),
        "found_or_asked": len(found_ids | asked_ids),
        "coverage": _ratio(len(found_ids | asked_ids), len(golden)),
        "defects": [
            {"id": d["id"], "severity": d["severity"], "must_find": bool(d.get("must_find")),
             "title": d.get("title", ""), "found_by": found_by[d["id"]], "asked_by": asked_by[d["id"]]}
            for d in golden
        ],
    }


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def _summary_rows(r: dict) -> list[tuple[str, str]]:
    rows = [("Recall (all)", f"{r['found']}/{r['golden_total']} = {_pct(r['recall'])}")]
    for sev, s in r["by_severity"].items():
        rows.append((f"Recall {sev}", f"{s['found']}/{s['total']} = {_pct(s['recall'])}"))
    crit_total = r["by_severity"]["критично"]["total"]
    rows.append(("Critical found as critical", f"{r['critical_as_critical']}/{crit_total}"
                 + (f" (lower severity: {', '.join(r['critical_wrong_severity'])})" if r["critical_wrong_severity"] else "")))
    rows.append(("Must-find recall", f"{r['must_found']}/{r['must_total']} = {_pct(r['must_recall'])}"))
    rows.append(("Must-find missed", ", ".join(r["must_missed"]) or "none"))
    rows.append(("Precision", f"{r['findings_matched']}/{r['findings_total']} = {_pct(r['precision'])}"))
    rows.append(("Questions asked on golden", f"{r['asked']} (asked, not found: {', '.join(r['asked_only']) or 'none'})"))
    rows.append(("Found or asked", f"{r['found_or_asked']}/{r['golden_total']} = {_pct(r['coverage'])}"))
    return rows


def _short(s: str, n: int = 110) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def render_text(r: dict) -> str:
    out = ["== Summary =="]
    rows = _summary_rows(r)
    w = max(len(k) for k, _ in rows)
    out += [f"{k.ljust(w)}  {v}" for k, v in rows]
    out += ["", "== Golden defects =="]
    out.append(f"{'id':<4} {'sev':<9} {'must':<4} {'found by':<16} {'asked by':<12} title")
    for d in r["defects"]:
        out.append(f"{d['id']:<4} {d['severity']:<9} {'yes' if d['must_find'] else '':<4} "
                   f"{','.join(d['found_by']) or '-':<16} {','.join(d['asked_by']) or '-':<12} {_short(d['title'], 70)}")
    out += ["", f"== Unmatched findings ({len(r['unmatched'])}) - review by hand =="]
    for u in r["unmatched"]:
        out.append(f"{u['id']} [{u['severity']}] {_short(u['problem'])}")
    if not r["unmatched"]:
        out.append("none")
    return "\n".join(out) + "\n"


def _md_cell(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def render_md(r: dict) -> str:
    out = ["## Eval summary", "", "| Metric | Value |", "| :--- | :--- |"]
    out += [f"| {_md_cell(k)} | {_md_cell(v)} |" for k, v in _summary_rows(r)]
    out += ["", "## Golden defects", "", "| ID | Severity | Must | Found by | Asked by | Title |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"]
    for d in r["defects"]:
        out.append(f"| {d['id']} | {d['severity']} | {'yes' if d['must_find'] else ''} | "
                   f"{', '.join(d['found_by']) or '-'} | {', '.join(d['asked_by']) or '-'} | {_md_cell(d['title'])} |")
    out += ["", f"## Unmatched findings ({len(r['unmatched'])})", ""]
    if r["unmatched"]:
        out += ["| ID | Severity | Problem |", "| :--- | :--- | :--- |"]
        out += [f"| {u['id']} | {u['severity']} | {_md_cell(_short(u['problem'], 200))} |" for u in r["unmatched"]]
    else:
        out.append("None.")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Score report.json against golden defects.")
    ap.add_argument("report")
    ap.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    ap.add_argument("--md")
    args = ap.parse_args(argv)
    try:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
        golden = load_golden(args.golden)
    except (OSError, ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 0
    result = score(report, golden)
    print(render_text(result), end="")
    if args.md:
        Path(args.md).write_text(render_md(result), encoding="utf-8")
        print(f"\nmarkdown written to {args.md}")
    return 0


if __name__ == "__main__":
    main()
    sys.exit(0)
