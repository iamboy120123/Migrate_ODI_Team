"""
grade.py — ใบเกรดแพ็กเกจ (ท้ายขั้น 04) → output/verify/grade.json + status/SUMMARY_04_PACKAGE.md

เกรด (ไม่เอาคะแนนมาเฉลี่ย · ข้อเดียวไม่ผ่านก็คือไม่ผ่าน · กติกาเต็ม: knowledge/reference/grading-rules.md ของ kit กลาง):
  A ส่งได้            ทุกด่านผ่าน ไม่มี waiver · SQL ทุก task ✅
  B ส่งได้ มีเงื่อนไข  มี waiver ที่อนุมัติแล้ว หรือ task ที่ 🟡 — ใบเกรดบอกเงื่อนไขทุกข้อ
  F ห้ามส่ง            มี ⛔ / FAIL / BLOCKED แม้ข้อเดียว — ใบเกรดบอกว่าต้องแก้อะไรที่ไหน
ด่านที่ใช้: G1 · G2 · G3 (check_gate.py) · pre_delivery_gate P1–P6 · status/SQL_REVIEW.md · verify V1–V9
อ่านอย่างเดียว (ยกเว้นไฟล์ผลสองไฟล์ด้านบน)

Usage:  python scripts/checks/grade.py [--no-verify]
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
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


def rd(rel):
    p = ROOT / rel
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def gates():
    p = ROOT / "scripts/checks/check_gate.py"
    sys.path.insert(0, str(p.parent))
    spec = importlib.util.spec_from_file_location("g_check_gate", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    vj = m.verify_json()
    out = {}
    for g in ("G1", "G2", "G3"):
        st, a, man, w = m.evaluate(g, vj)
        out[g] = {"status": st, "missing": [t for x, t in a + man if not x]}
    return out, vj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-verify", action="store_true")
    a = ap.parse_args()
    if not a.no_verify:
        subprocess.run([sys.executable, "scripts/checks/verify_all.py", "--quiet"], cwd=str(ROOT))
        subprocess.run([sys.executable, "scripts/checks/pre_delivery_gate.py"], cwd=str(ROOT), capture_output=True)
    g, vj = gates()
    pdg = rd("output/verify/pre_delivery_gate.txt")
    p_fail = re.findall(r"^\[FAIL\]\s+(P\d)\s+(.*)$", pdg, re.M)
    p_warn = re.findall(r"^\[WARN\]\s+(P\d)\s+(.*)$", pdg, re.M)
    m = re.search(r"✅\s*(\d+)\s*·\s*🟡\s*(\d+)\s*·\s*⛔\s*(\d+)", rd("status/SQL_REVIEW.md"))
    sql = tuple(int(x) for x in m.groups()) if m else None
    vfail = [k for k, v in (vj.get("levels") or {}).items() if v.get("status") == "FAIL"]
    must, cond = [], []
    for k, v in g.items():
        if v["status"] == "BLOCKED":
            must += [f"{k}: {t}" for t in v["missing"][:4]]
        elif v["status"] == "WAIVED":
            cond.append(f"{k} ผ่านด้วย waiver (ดู Waiver log ใน status/GATES.md)")
    must += [f"ก่อนส่ง {p}: {t[:120]}" for p, t in p_fail]
    cond += [f"ก่อนส่ง {p}: {t[:120]}" for p, t in p_warn]
    if sql is None:
        must.append("ยังไม่มี status/SQL_REVIEW.md — รัน /review-report")
    else:
        if sql[2]:
            must.append(f"SQL ⛔ {sql[2]} task (ดู status/SQL_REVIEW.md)")
        if sql[1]:
            cond.append(f"SQL 🟡 {sql[1]} task — ต้องมีเหตุผลบันทึก (NO_CHANGE) ทุกข้อ")
    must += [f"verify {v} FAIL" for v in vfail if f"verify {v}" not in " ".join(must)]
    grade = "F" if must else ("B" if cond else "A")
    slow = len(re.findall(r"🟡 ความเร็ว", rd("status/SQL_REVIEW.md")))
    speed = "ต้องดู" if slow else "ดี"
    cfg = json.loads(rd("config/config.json") or "{}")
    o = cfg.get("odi") or {}
    excl = (cfg.get("scope") or {}).get("excluded_tasks") or []
    reasons = (cfg.get("scope") or {}).get("excluded_reason") or {}
    zips = sorted((ROOT / "output/odi_export").glob("*.zip")) + sorted((ROOT / "output/odi_export").glob("PROJ_EXPORT.xml"))
    res = {"grade": grade, "date": dt.datetime.now().isoformat(timespec="seconds"), "gates": {k: v["status"] for k, v in g.items()},
           "pre_delivery": {"fail": len(p_fail), "warn": len(p_warn)}, "sql": sql, "must_fix": must, "conditions": cond, "speed_pre_run": speed,
           "package": zips[-1].name if zips else None, "odi_code": o.get("project_code"), "id_base": o.get("id_base")}
    vp = ROOT / "output/verify/grade.json"
    vp.parent.mkdir(parents=True, exist_ok=True)
    vp.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ph = [k for k in ("logical_schema", "context_code", "work_user") if not o.get(k)]
    word = {"A": "ส่งได้", "B": "ส่งได้ มีเงื่อนไข", "F": "ห้ามส่ง"}[grade]
    L = [f"# สรุปขั้น 04 · แพ็กเกจ — {cfg.get('project_name', ROOT.name)}", "",
         f"อัปเดต {dt.datetime.now():%Y-%m-%d %H:%M} · สร้างโดย `scripts/checks/grade.py` · ห้ามแก้มือ", "",
         f"## เกรด: **{grade} · {word}**", "",
         f"แพ็กเกจ `{res['package'] or '(ยังไม่มี)'}` · ODI code `{o.get('project_code')}` · id_base `{o.get('id_base')}` · ความเร็วก่อนรันจริง: {speed}", "",
         "| ด่าน | ผล |", "|---|---|"]
    for k, v in g.items():
        L.append(f"| {k} | {'✅' if v['status'] == 'PASS' else '🟡' if v['status'] == 'WAIVED' else '⛔'} {v['status']} |")
    L.append(f"| ก่อนส่ง P1–P6 | {'✅' if not p_fail else '⛔'} FAIL {len(p_fail)} · WARN {len(p_warn)} |")
    L.append(f"| SQL ต่อ task | {('✅ %d · 🟡 %d · ⛔ %d' % sql) if sql else '⬜ ยังไม่มี'} |")
    if must:
        L += ["", "## ต้องแก้ก่อนส่ง (F)", ""] + [f"- {x}" for x in must]
    if cond:
        L += ["", "## เงื่อนไข (B)", ""] + [f"- {x}" for x in cond]
    L += ["", "## สรุปการส่งมอบ", "",
          f"- **ทาสก์ที่ตัดออก:** " + (", ".join(f"{t} ({reasons.get(t, 'ไม่ระบุเหตุผล')})" for t in excl) if excl else "ไม่มี"),
          f"- **placeholder ที่เหลือ:** " + (", ".join(f"odi.{k}" for k in ph) if ph else "ไม่มีในค่า ODI หลัก (ตรวจ <...> ใน output/ อีกครั้งก่อนส่ง)"),
          "- **Topology ที่คนต้องตั้งเอง:** JDBC URL + user/password ของ data server ใน ODI Studio (ไม่มีรหัสผ่านในไฟล์) · logical schema / context ถ้ายังไม่มี",
          "- **Scenario ที่ต้อง generate เอง:** ทุก Procedure / Package หลัง import (kit ไม่สร้าง Scenario ที่ compile แล้ว)",
          "- **ยังไม่ยืนยัน:** แพ็กเกจนี้ import และรันได้จริงตั้งแต่ต้นจนจบ — ยืนยันที่ G4 / G5",
          "", "## ต้องทำต่อ", "",
          "- รัน output/ddl/ (`run_sql.py output/ddl/<ไฟล์> --plan` → ขออนุญาต → AI รัน หรือคนรันเอง · ตารางที่มีอยู่แล้วห้ามรันทับ) → บันทึก status/DEPLOY_LOG.md",
          "- import-lock (ใบงานล็อก) → Smart Import (Overwrite) → Topology → Generate Scenario → export Smart Export หลัง import (หลักฐาน G4) → import-unlock"]
    (ROOT / "status/SUMMARY_04_PACKAGE.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    if grade in ("A", "B") and (ROOT / "job.json").exists():   # หลัง G3 ล็อกรุ่นของกลางที่ใช้ build (เปลี่ยน = new-round)
        jm = json.loads(rd("job.json") or "{}")
        tl = jm.setdefault("target_lock", {})
        if not tl.get("locked_at_g3"):
            tl["locked_at_g3"] = dt.date.today().isoformat()
            (ROOT / "job.json").write_text(json.dumps(jm, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"เกรด {grade} · {word} → status/SUMMARY_04_PACKAGE.md · output/verify/grade.json")
    for x in must:
        print(f"  ⛔ {x}")
    for x in cond:
        print(f"  🟡 {x}")
    sys.exit(1 if grade == "F" else 0)


if __name__ == "__main__":
    main()
