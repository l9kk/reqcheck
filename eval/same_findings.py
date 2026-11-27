"""Check that two report.json files have the same findings, ignoring the fix text.

python eval/same_findings.py eval/handcheck_v1.5_input.json report/report.json
"""
import json
import sys


def findings(path):
    data = json.load(open(path, encoding="utf-8"))
    return {f["id"]: {k: v for k, v in f.items() if k != "fix"} for f in data["findings"]}


def main(a, b):
    fa, fb = findings(a), findings(b)
    diff = sorted(i for i in fa.keys() | fb.keys() if fa.get(i) != fb.get(i))
    print(f"{a}: {len(fa)} findings; {b}: {len(fb)} findings")
    print("same apart from fix text" if not diff else f"differ: {', '.join(diff)}")
    return 1 if diff else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
