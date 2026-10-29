"""
check_gate.py  (P2, 2026-09-29) — ประเมิน gate ตาม status/GATES.md

Usage:
    python scripts/checks/check_gate.py G3          # ประเมิน gate เดียว (รัน verify_all.py ก่อนอัตโนมัติ)
    python scripts/checks/check_gate.py --all       # ตารางสรุปทุก gate
    python scripts/checks/check_gate.py G5 --no-verify
kit K4 (2026-09-30): G2 +review log +Q Spark config · G4 auto (Studio = DML, GlobalId) · G5 +V7/V8 · G6 +V6 · G7 auto (V9 + Q retention)
Exit code: 0 = PASS/WAIVED, 1 = BLOCKED
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Windows: pipe ของ hook ใช้ code page ของเครื่อง -> บังคับ UTF-8 ไม่งั้นข้อความภาษาไทยทำ hook พัง
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_all import decisions, preflight, adrs, read  # noqa: E402

GATES = ["G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7"]


def verify_json():
    p = ROOT / "output" / "verify" / "verify.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"levels": {}}


def lv(vj, name):
    return (vj["levels"].get(name) or {}).get("status", "MISSING")


def item(vj, level, needle):
    for it in (vj["levels"].get(level) or {}).get("items", []):
        if needle in it["msg"]:
            return it
    return None


def auto_checks(g, vj):
    """คืน list ของ (ok: bool, ข้อความ)"""
    out = []
    if g == "G0":
        ok, n, _ = preflight()
        out.append((ok == n and n > 0, f"PREFLIGHT {ok}/{n}"))
    elif g == "G1":
        man = json.loads(read("output/sql/raw/_manifest.json") or "[]")
        conv = " ".join(p.name for p in (ROOT / "output" / "sql" / "converted").glob("*.sql"))
        dml = " ".join(p.name for p in (ROOT / "output" / "dml").glob("*.sql"))
        cfg = json.loads(read("config/config.json") or "{}")
        excl = " ".join((cfg.get("scope") or {}).get("excluded_tasks") or [])
        # K12: task ที่แทนด้วย ODI variable (odi.variables[].replaces_tasks) นับว่าจัดการแล้ว
        excl += " " + " ".join(t for v in ((cfg.get("odi") or {}).get("variables") or []) for t in (v.get("replaces_tasks") or []))
        answered = " ".join(t for q, t, a in decisions() if a) + read("status/OPEN_DECISIONS.md")
        decided = " ".join(t for q, t, a in decisions() if a)   # K13: Q ที่ปิดแล้วและหัวข้อระบุ code ของ task = มีการตัดสินใจ
        miss = []
        for t in man:
            code = t["task_name"][:6]
            if t.get("kind") == "non_sql":
                if not (code in dml or code in excl or code in decided
                        or re.search(rf"exclude[^\n]*{code}|{code}[^\n]*exclude", answered, re.I)):
                    miss.append(t["task_name"][:40])
            elif code not in conv:
                miss.append(t["task_name"][:40])
        # K4: manifest ว่าง (ยังไม่ extract) เดิมได้ PASS เท็จ 0/0
        out.append((bool(man) and not miss, (f"task ครบ {len(man) - len(miss)}/{len(man)}" + (f" — ขาด: {', '.join(miss)}" if miss else ""))
                    if man else "ยังไม่มี output/sql/raw/_manifest.json (Phase 1 — /convert)"))
    elif g == "G2":
        it = item(vj, "V4", "REVIEW_FLAGS")
        out.append((bool(it) and it["status"] == "PASS", it["msg"] if it else "ไม่มีผล V4"))
        logs = items(vj, "V4", "PHASE4_REVIEW_LOG")
        out.append((bool(logs) and all(x["status"] == "PASS" for x in logs),
                    "; ".join(x["msg"] for x in logs) if logs else "PHASE4_REVIEW_LOG: ยังไม่ได้ตรวจ (ต้องมี REVIEW_FLAGS ก่อน)"))
        out.append(decision_closed(r"Spark config", "Spark config ของ Blendata (CLAUDE.md §4 — ต้องยืนยันก่อนปิด Phase 4)"))
        out.append((lv(vj, "V1") == "PASS", f"V1 Static = {lv(vj, 'V1')}"))
    elif g == "G3":
        out.append((lv(vj, "V1") == "PASS", f"V1 Static = {lv(vj, 'V1')}"))
        out.append((lv(vj, "V2") == "PASS", f"V2 Build = {lv(vj, 'V2')}"))
    elif g == "G4":
        for needle, miss in (("Studio (", "ยังไม่มี Smart Export จาก Studio หลัง import (input/odi_reference/)"),
                             ("GlobalId map", "ยังไม่ได้เทียบ GlobalId กับ Studio")):
            it = item(vj, "V2", needle)
            out.append((bool(it) and it["status"] == "PASS", it["msg"] if it else miss))
    elif g == "G5":
        it = item(vj, "V5", "assertions PASS")
        out.append((bool(it) and it["status"] == "PASS", it["msg"] if it else "ยังไม่มีผล assertions"))
        stale = item(vj, "V5", "ใหม่กว่า REPORT")
        out.append((not stale, "REPORT.md เป็นปัจจุบัน" if not stale else stale["msg"]))
        for lvl in ("V7", "V8"):
            out.append((lv(vj, lvl) in ("PASS", "WARN"), f"{lvl} = {lv(vj, lvl)}"))
    elif g == "G6":
        open_q = [q for q, _, a in decisions() if not a]
        out.append((not open_q, "OPEN_DECISIONS เปิด " + (", ".join(open_q) if open_q else "0")))
        notacc = [a for a, s in adrs() if not re.match(r"(Accepted|Superseded)", s, re.I)]
        out.append((not notacc, "ADR ที่ยังไม่ Accepted: " + (", ".join(a[:7] for a in notacc) if notacc else "ไม่มี")))
        it = item(vj, "V3", "hardcode")
        out.append((bool(it) and it["status"] == "PASS", it["msg"] if it else "ไม่มีผล V3"))
        it = item(vj, "V6", "DDL fallback")
        out.append((bool(it) and it["status"] == "PASS", it["msg"] if it else "ยังไม่มี DDL (Phase 6 — /gen-ddl)"))
        out.append((lv(vj, "V6") in ("PASS", "WARN") and lv(vj, "V6") != "MISSING", f"V6 Schema / data contract = {lv(vj, 'V6')}"))
    elif g == "G7":
        g6 = auto_checks("G6", vj)
        out.append((all(x for x, _ in g6), "G6 auto ผ่านครบ" if all(x for x, _ in g6) else f"G6 auto ยังขาด {sum(1 for x, _ in g6 if not x)} ข้อ"))
        for needle, miss in (("backfill pack", "ไม่มีผล V9 backfill"), ("CUTOVER_RUNBOOK", "ไม่มีผล V9 runbook"), ("validation", "ไม่มีผล V9 validation")):
            its = items(vj, "V9", needle)
            out.append((bool(its) and all(x["status"] == "PASS" for x in its), "; ".join(x["msg"] for x in its) if its else miss))
        out.append(decision_closed(r"retention", "retention ของ backfill (G7.M1)"))
    return out


def items(vj, level, needle):
    return [it for it in (vj["levels"].get(level) or {}).get("items", []) if needle in it["msg"]]


def decision_closed(title_re, label):
    """(ok, msg) — Q ใน OPEN_DECISIONS ที่หัวข้อ match title_re ต้องปิดแล้ว (kit K4)"""
    qs = [(q, t, a) for q, t, a in decisions() if re.search(title_re, t, re.I)]
    if not qs:
        return (False, f"ไม่มี Q เรื่อง {label} ใน status/OPEN_DECISIONS.md — เปิดด้วย /decide")
    open_q = [q for q, _, a in qs if not a]
    return (not open_q, f"{label}: " + (f"{', '.join(open_q)} ยังเปิด" if open_q else f"{', '.join(q for q, _, _ in qs)} ปิดแล้ว"))


def manual_checks(g):
    s = read("status/GATES.md")
    out = []
    for m in re.finditer(rf"^\s*-\s*\[([ xX])\]\s*({g}\.M\d+)\s*(.*)$", s, re.M):
        out.append((m.group(1).lower() == "x", f"{m.group(2)} {m.group(3).strip()[:110]}"))
    return out


def waivers(g):
    s = read("status/GATES.md")
    return [l for l in s.splitlines() if re.match(rf"^\|\s*W\d+\s*\|\s*{g}\s*\|", l) and "| open |" in l]


def waived_items(w):
    """ข้อความในคอลัมน์ 'ข้อที่ยกเว้น' ของ waiver ที่ยัง open (kit K11)"""
    out = []
    for l in w:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[2]:
            out.append(cells[2].lower())
    return out


def evaluate(g, vj):
    """K11: waiver ยกเว้นเฉพาะข้อที่ระบุ (ข้อความในคอลัมน์ 'ข้อที่ยกเว้น' อยู่ในข้อความของข้อที่ไม่ผ่าน)
    เดิม waiver ใด ๆ ของ gate ทำให้ทั้ง gate = WAIVED แม้ข้ออื่นยังไม่ผ่าน"""
    a, m, w = auto_checks(g, vj), manual_checks(g), waivers(g)
    failed = [t for x, t in a + m if not x]
    if not failed:
        return "PASS", a, m, w
    keys = waived_items(w)
    uncovered = [t for t in failed if not any(k in t.lower() for k in keys)]
    return ("WAIVED" if keys and not uncovered else "BLOCKED"), a, m, w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gate", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()
    if not args.no_verify:
        subprocess.run([sys.executable, "scripts/checks/verify_all.py", "--quiet"], cwd=ROOT)
    vj = verify_json()
    icon = {"PASS": "✅", "BLOCKED": "⛔", "WAIVED": "🟡"}
    if args.all or not args.gate:
        print("| Gate | ผล | ข้อที่ขาด |\n|---|---|---|")
        for g in GATES:
            st, a, m, w = evaluate(g, vj)
            miss = [t for x, t in a + m if not x]
            print(f"| {g} | {icon[st]} {st} | {len(miss)} ข้อ" + (f" (เช่น {miss[0][:60]})" if miss else "") + " |")
        sys.exit(0)
    g = args.gate.upper()
    st, a, m, w = evaluate(g, vj)
    print(f"{icon[st]} {g}: {st}")
    for x, t in a:
        print(f"  {'✅' if x else '❌'} [auto]   {t}")
    for x, t in m:
        print(f"  {'✅' if x else '⬜'} [manual] {t}")
    for l in w:
        print(f"  🟡 waiver: {l.strip()[:150]}")
    sys.exit(0 if st in ("PASS", "WAIVED") else 1)


if __name__ == "__main__":
    main()
