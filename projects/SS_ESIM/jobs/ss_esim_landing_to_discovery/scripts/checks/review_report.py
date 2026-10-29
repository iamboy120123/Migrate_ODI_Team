"""
review_report.py — รวมผลตรวจ SQL ทุกชั้นเป็นไฟล์เดียว status/SQL_REVIEW.md (คำสั่ง /review-report)

ต่อ task:  ①–③ รีวิว (REVIEW_FLAGS · PHASE4_REVIEW_LOG · semantic-verifier) · ④ check_sql (D-R1–D-R8)
           · ⑤ DML / XML ครบ · ⑥ คอมไพล์กับฐานจริง (WHERE 1=0) · ⑦ sandbox (รอตัดสินใจ) · ความเร็ว (รูปแบบ SQL ที่ช้า)
ผลต่อ task: ✅ ผ่าน · 🟡 ต้องมีคนดูและบันทึกเหตุผล (NO_CHANGE) · ⛔ ห้าม build
ไม่แก้ SQL — อ่าน / รัน check_sql แล้วเขียนรายงานเท่านั้น

Usage:
    python scripts/checks/review_report.py                     # เขียน status/SQL_REVIEW.md + output/verify/sql_check_converted.txt
    python scripts/checks/review_report.py --make-compile-pack # สร้าง run_packs/rp_compile/ (SELECT … WHERE 1=0) สำหรับชั้น ⑥
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
CONV = ROOT / "output" / "sql" / "converted"

SLOW = [
    (re.compile(r"\bwhere\b[^;]*?\b(upper|lower|trunc|to_char|substr|nvl|coalesce|trim)\s*\(\s*\w+(\.\w+)?\s*\)\s*(=|<|>|in\b|like\b)", re.I | re.S), "ฟังก์ชันครอบคอลัมน์ใน WHERE (ใช้ index ไม่ได้)"),
    (re.compile(r"\bnot\s+in\s*\(\s*select\b", re.I), "NOT IN กับ subquery (ถ้าคอลัมน์มี NULL ผลผิด + ช้า) → NOT EXISTS"),
    (re.compile(r"\bunion\b(?!\s+all\b)", re.I), "UNION ที่อาจควรเป็น UNION ALL (ต้องเรียง + ตัดซ้ำ)"),
    (re.compile(r"\bcross\s+join\b", re.I), "CROSS JOIN (ตรวจว่าตั้งใจ)"),
    (re.compile(r"\bfrom\s+[\w.]+\s+\w*\s*,\s*[\w.]+\s+\w*\s*(?:where|$)", re.I), "join แบบคอมมา — ตรวจว่ามีเงื่อนไข join"),
    (re.compile(r"\bselect\s+distinct\b", re.I), "DISTINCT (ตรวจว่าจำเป็น)"),
]


def rd(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def table_rows(text: str):
    for l in text.splitlines():
        if l.startswith("|") and not re.match(r"^\|\s*-", l):
            yield [c.strip() for c in l.strip().strip("|").split("|")]


def run_check_sql() -> str:
    args = [sys.executable, "scripts/checks/check_sql.py", "output/sql/converted"]
    ddl = sorted((ROOT / "input/oracle_ddl").glob("*.csv"))
    if ddl:
        args += ["--ddl", str(ddl[-1].relative_to(ROOT))]
    if (ROOT / "config/partitions_check.csv").exists():
        args += ["--partitions", "config/partitions_check.csv"]
    r = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    vp = ROOT / "output" / "verify" / "sql_check_converted.txt"
    vp.parent.mkdir(parents=True, exist_ok=True)
    vp.write_text(out, encoding="utf-8")
    return out


def compile_pack():
    d = ROOT / "run_packs" / "rp_compile"
    d.mkdir(parents=True, exist_ok=True)
    n = skipped = 0
    for f in sorted(CONV.glob("*.sql")):
        sql = rd(f).strip().rstrip(";")
        m = re.search(r"^\s*insert\b.*?\)\s*(select\b|with\b)", sql, re.I | re.S)
        body = sql[m.start(1):] if m else (sql if re.match(r"^\s*(select|with)\b", sql, re.I) else None)
        if body is None:
            skipped += 1
            continue
        (d / f.name).write_text(f"-- คอมไพล์ {f.name} กับฐานจริงแบบไม่ดึงข้อมูล (WHERE 1=0) · SELECT อย่างเดียว\n"
                                f"SELECT * FROM (\n{body}\n) WHERE 1=0\n", encoding="utf-8")
        n += 1
    print(f"✅ run_packs/rp_compile/: {n} ไฟล์{f' · ข้าม {skipped} (MERGE / ไม่มี SELECT)' if skipped else ''}")
    print("ต่อไป: python scripts/runpack/run_pack.py rp_compile --compile  (หรือคนรันใน DBeaver แล้ววางผล error ที่ input/run_results/rp_compile/)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-compile-pack", action="store_true")
    a = ap.parse_args()
    if a.make_compile_pack:
        return compile_pack()
    files = sorted(CONV.glob("*.sql"))
    if not files:
        print("[ERROR] ยังไม่มี output/sql/converted/*.sql — /convert ก่อน")
        sys.exit(2)
    chk = run_check_sql()
    flags = list(table_rows(rd(ROOT / "status/REVIEW_FLAGS.md")))
    log = list(table_rows(rd(ROOT / "status/PHASE4_REVIEW_LOG.md")))
    comp = {}
    for l in rd(ROOT / "output/verify/sql_compile.txt").splitlines():
        p = l.split("\t")
        if len(p) >= 2:
            comp[Path(p[0]).stem] = (p[1], p[2] if len(p) > 2 else "")
    dml = ROOT / "output/dml"
    xml = rd(ROOT / "output/odi_export/PROJ_EXPORT.xml")
    rows, todo, totals = [], [], {"✅": 0, "🟡": 0, "⛔": 0}
    for f in files:
        stem, tid = f.stem, f.stem.split("_")[0]
        mine = lambda cells: cells and (cells[0] == stem or cells[0] == tid or cells[0].startswith(tid + "_"))
        fl = [c for c in flags if mine(c) and c[0] != "Task ID"]
        lg = [c for c in log if mine(c) and c[0] != "Task"]
        # ①–③
        bad13, warn13 = [], []
        for c in fl:
            if c[-1].upper() not in ("RESOLVED", "WAIVED"):
                (bad13 if "CRITICAL" in c[1] else warn13).append("flag: " + c[1][:60])
        for c in lg:
            st = c[-1].upper()
            if st == "OPEN":
                bad13.append("review OPEN: " + c[1][:50])
            if len(c) >= 6 and c[5].upper().startswith("FAIL") and st != "ACCEPTED":
                bad13.append("semantic FAIL: " + c[5][:50])
        s13 = "⛔" if bad13 else ("🟡" if warn13 else ("✅" if fl or lg else "–"))
        # ④
        errs = [l for l in chk.splitlines() if l.startswith("[ERROR]") and f.name in l]
        warns = [l for l in chk.splitlines() if l.startswith("[WARN]") and f.name in l]
        nochg = [c for c in lg if c[-1].upper() == "NO_CHANGE"]
        open_w = warns if len(nochg) < len(warns) else []
        s4 = "⛔" if errs else ("🟡" if open_w else "✅")
        # ⑤
        dml_f = list(dml.glob(f"{tid}*.sql")) if dml.exists() else []
        s5 = "–" if not dml_f else ("✅" if (not xml or tid in xml or stem in xml) else "⛔")
        # ⑥ ⑦
        c6 = comp.get(stem)
        s6 = "–" if not c6 else ("✅" if c6[0] == "OK" else "⛔")
        s7 = "–"
        # ความเร็ว
        sq = rd(f)
        slow = [why for rx, why in SLOW if rx.search(sq)]
        sp = "ดี" if not slow else f"🟡 {len(slow)}"
        res = "⛔" if "⛔" in (s13, s4, s5, s6) else ("🟡" if "🟡" in (s13, s4) or slow else "✅")
        totals[res] += 1
        rows.append(f"| {stem} | {s13} | {s4} | {s5} | {s6} | {s7} | {sp} | **{res}** |")
        for e in bad13 + [x.split("  ", 1)[-1][:120] for x in errs] + ([f"compile: {c6[1][:80]}"] if c6 and c6[0] != "OK" else []):
            todo.append(f"- ⛔ `{stem}` {e}")
        for w in warn13 + [x.split("  ", 1)[-1][:120] for x in open_w]:
            todo.append(f"- 🟡 `{stem}` {w} — ถามผู้ใช้: ไม่ต้องแก้ใช่ไหม → บันทึก NO_CHANGE พร้อมเหตุผลใน PHASE4_REVIEW_LOG")
        for w in slow:
            todo.append(f"- 🟡 ความเร็ว `{stem}`: {w}")
    out = [f"# SQL_REVIEW — ผลตรวจ SQL ต่อ task", "",
           f"อัปเดต {dt.datetime.now():%Y-%m-%d %H:%M} · สร้างโดย `scripts/checks/review_report.py` (/review-report) · ห้ามแก้มือ", "",
           f"**สรุป: ✅ {totals['✅']} · 🟡 {totals['🟡']} · ⛔ {totals['⛔']}**  {'— มี ⛔ = ห้าม build' if totals['⛔'] else ''}", "",
           "| task | ①–③ รีวิว | ④ check_sql | ⑤ DML/XML | ⑥ คอมไพล์ | ⑦ sandbox | ความเร็ว | ผล |", "|---|---|---|---|---|---|---|---|", *rows, "",
           "## ต้องทำต่อ (⛔ ก่อน)", "", *(sorted(todo, key=lambda x: 0 if "⛔" in x else 1) or ["- ไม่มี"]), "",
           "## ความหมาย", "",
           "- ✅ ผ่าน · 🟡 ต้องมีคนดูและบันทึกเหตุผล · ⛔ ห้าม build · – ยังไม่ได้ตรวจชั้นนี้",
           "- ⑥ สร้าง pack ด้วย `--make-compile-pack` แล้วรัน `run_pack.py rp_compile --compile` (ตามโหมดการเช็กฐานของงาน)",
           "- ⑦ sandbox ยังรอทีมตัดสิน (ฐานชั่วคราวบนเครื่อง ไม่นับเป็นฐานของงาน)",
           "- ความเร็ว: เตือนเท่านั้น · บล็อกการส่งเฉพาะเมื่อเกินกรอบเวลา batch (ขั้น 05.3)"]
    (ROOT / "status").mkdir(exist_ok=True)
    (ROOT / "status/SQL_REVIEW.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"✅ {totals['✅']} · 🟡 {totals['🟡']} · ⛔ {totals['⛔']}  → status/SQL_REVIEW.md")
    sys.exit(1 if totals["⛔"] else 0)


if __name__ == "__main__":
    main()
