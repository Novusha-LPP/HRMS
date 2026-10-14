"""
Check docs/database-hardening-plan.md for gaps: every audit finding, concept, operation and edge
case names a plan item that exists and a test or guard; every rule is defined; nothing dangles.

    python scripts/check_database_plan.py      # exit 1 if anything is missing
"""

import re
import sys
from pathlib import Path

PLAN = Path(__file__).resolve().parents[2] / "docs" / "database-hardening-plan.md"


def main() -> int:
    s = PLAN.read_text(encoding="utf-8")

    def section(start, end=None):
        a = s.index(start)
        return s[a : s.index(end, a) if end else len(s)]

    def cells(line):
        return [c.strip() for c in line.strip().strip("|").split("|")]

    work = section("## 6. Workstreams", "## 7. Schema rules")
    items = set(re.findall(r"^\| (W\d+(?:\.\d+)?|D2\.\d) \|", work, re.M))
    for m in re.finditer(r"^\| (W2[2-6]) \|(.*)$", work, re.M):
        family = re.escape(m.group(1))
        items |= set(re.findall(rf"\b({family}\.\d+)\b", m.group(2)))
    families = {i.split(".")[0] for i in items}

    def refs(text):
        out = set(re.findall(r"\bW\d+\.\d+\b", text))
        for w, a, b in re.findall(r"\bW(\d+)\.(\d+)[–-]W\d+\.(\d+)", text):
            out |= {f"W{w}.{i}" for i in range(int(a), int(b) + 1)}
        out |= set(re.findall(r"\b(W\d+)\b(?!\.\d)", text))
        return out

    problems, used = [], set()

    def check(where, text):
        for r in refs(text):
            if r not in items and r not in families:
                problems.append(f"{where}: references undefined {r}")
            used.update(i for i in items if i == r or i.split(".")[0] == r)

    trace = section("### 9.1", "### 9.2")
    fids = []
    for line in trace.splitlines():
        if re.match(r"^\| F-\d+ \|", line):
            c = cells(line)
            fids.append(c[0])
            check(c[0], c[2])
    closes = set(re.findall(r"F-\d+", work))
    problems += [f"{f} is closed by no workstream" for f in fids if f not in closes]
    problems += [f"{f} is closed but not traced" for f in closes if f not in fids]

    concepts = []
    for line in section("## 4. Concept catalogue", "## 5. Case catalogue").splitlines():
        if re.match(r"^\| C-\d+ \|", line):
            c = cells(line)
            concepts.append(c[0])
            if not c[4] or not c[5]:
                problems.append(f"{c[0]} lacks a plan item or a guard")
            check(c[0], c[4])

    cases = 0
    for line in section("### 5.1", "### 5.2").splitlines():
        if re.match(r"^\| [A-Z]{1,2}\d+ \|", line):
            c = cells(line)
            cases += 1
            if not c[3] or not c[5]:
                problems.append(f"case {c[0]} lacks a mechanism or a test")
            check(c[0], c[3] + " " + c[4])
    edges = 0
    for line in section("### 5.2", "## 6. Workstreams").splitlines():
        if re.match(r"^\| EC-\d+ \|", line):
            c = cells(line)
            edges += 1
            if not c[2] or not c[3]:
                problems.append(f"{c[0]} lacks handling or a test")
            check(c[0], c[2] + " " + c[3])

    rules = {}
    for line in section("## 7. Schema rules", "## 8. PR checklist").splitlines():
        if re.match(r"^\| L\d+ \|", line):
            c = cells(line)
            rules[c[0]] = c[2]
    problems += [f"rule L{n} undefined" for n in range(1, 21) if f"L{n}" not in rules]
    for rule, state in rules.items():
        if state != "built":
            check(rule, state)

    decisions = set(re.findall(r"\*\*(DB-D\d+)\*\*", section("## 3. Decisions", "## 4. Concept")))
    problems += [f"{d} used but not defined" for d in set(re.findall(r"DB-D\d+", s)) - decisions]
    orphans = sorted(i for i in items if i not in used and not i.startswith("D2"))
    problems += [f"{i} is owned by no finding, concept, case or rule" for i in orphans]

    print(
        f"items={len(items)} findings={len(fids)} concepts={len(concepts)} cases={cases} "
        f"edge_cases={edges} rules={len(rules)} decisions={len(decisions)}"
    )
    for p in problems:
        print("  PROBLEM:", p)
    print("no problems" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
