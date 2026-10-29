"""
job_status.py — สถานะของงานนี้ทั้ง 16 ขั้น (เปิดงาน → ODI → go-live) คำนวณจากไฟล์หลักฐานเท่านั้น

Usage:
    python scripts/ws/job_status.py            # ตารางทุกขั้น (เหมือน /status)
    python scripts/ws/job_status.py --box      # กล่องสถานะสั้น (แสดงท้ายข้อความทุกครั้งที่จบขั้น)
    python scripts/ws/job_status.py --json     # สำหรับ workspace.py status / report
    python scripts/ws/job_status.py --root <โฟลเดอร์งาน> [--pushed]   # อ่านจาก snapshot ของ branch อื่น

สัญลักษณ์: ✓ ทำแล้ว · ▶ กำลังทำ (คนทำงานต้องทำต่อ) · ⏳ รอคน (ผู้อนุมัติ / ข้อมูลจากคน) · ○ ยังไม่ทำ · ⛔ ติด / สถานะไม่ตรง
หลัก: ขั้นที่คนทำนอกแชท (DDL · Smart Import · go-live) ขึ้น ✓ เมื่อมีหลักฐานเท่านั้น · ไฟล์ขัดกัน = ⛔ ไม่เดาแทน
อ่านอย่างเดียว ไม่แก้ไฟล์ใด ๆ
"""
from __future__ import annotations

import argparse
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
DONE, CUR, WAIT, TODO, BLOCK = "✓", "▶", "⏳", "○", "⛔"


def rd(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def jread(rel: str, default=None):
    t = rd(rel)
    try:
        return json.loads(t) if t.strip() else ({} if default is None else default)
    except json.JSONDecodeError:
        return {} if default is None else default


def load_gates():
    """ใช้ evaluate() ของ check_gate.py ตัวเดียวกับ /gate (ไม่รัน verify ใหม่ — อ่าน verify.json ล่าสุด)"""
    p = ROOT / "scripts" / "checks" / "check_gate.py"
    if not p.exists():
        return None
    sys.path.insert(0, str(p.parent))
    try:
        spec = importlib.util.spec_from_file_location("ws_check_gate", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        vj = m.verify_json()
        out = {}
        for g in m.GATES:
            st, a, man, w = m.evaluate(g, vj)
            out[g] = {"status": st, "auto": [(bool(x), t) for x, t in a], "manual": [(bool(x), t) for x, t in man], "waivers": len(w)}
        return out
    except Exception as e:  # สคริปต์ของ kit เปลี่ยน / ไฟล์เสีย — ไม่เดา
        return {"_error": str(e)}
    finally:
        sys.path.pop(0)


def git(*a) -> str:
    try:
        return subprocess.run(["git", *a], cwd=str(ROOT), capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def intake_state():
    rows = re.findall(r"^\|\s*(I\d+)\s*\|.*\|\s*([^|]*?)\s*\|\s*$", rd("status/INTAKE.md"), re.M)
    if not rows:
        return None, 0, 0
    todo = [i for i, st in rows if "⬜" in st]
    return todo, len(rows) - len(todo), len(rows)


def open_questions():
    s = rd("status/OPEN_DECISIONS.md")
    out = []
    for m in re.finditer(r"^### (Q\d+)\.\s*(.*?)$(.*?)(?=^### Q\d+\.|^## |\Z)", s, re.S | re.M):
        body = m.group(3)
        if not re.search(r"^\s*-\s*\[[xX]\]", body, re.M):
            out.append((m.group(1), m.group(2).strip()))
    return out


def log_rows(rel: str, key: str):
    """แถวในตาราง log (DEPLOY_LOG / IMPORT_LOG) ที่คอลัมน์แรกตรง key"""
    out = []
    for l in rd(rel).splitlines():
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0].upper().startswith(key.upper()):
            out.append(cells)
    return out


def sql_review_counts():
    m = re.search(r"✅\s*(\d+)\s*·\s*🟡\s*(\d+)\s*·\s*⛔\s*(\d+)", rd("status/SQL_REVIEW.md"))
    return tuple(int(x) for x in m.groups()) if m else None


def gate_step(gates, g):
    """(state, note, waiting_for)"""
    if not gates or "_error" in gates:
        return TODO, "อ่านผล gate ไม่ได้: " + (gates or {}).get("_error", "ไม่พบ check_gate.py"), ""
    r = gates[g]
    if r["status"] in ("PASS", "WAIVED"):
        return DONE, ("ผ่านแบบมี waiver" if r["status"] == "WAIVED" else "ผ่าน"), ""
    auto_miss = [t for x, t in r["auto"] if not x]
    man_miss = [t for x, t in r["manual"] if not x]
    if not auto_miss and man_miss:
        return WAIT, "รอยืนยัน " + ", ".join(t.split()[0] for t in man_miss), "ผู้อนุมัติ"
    return CUR, (auto_miss or man_miss or ["ยังไม่ผ่าน"])[0][:90], "เจ้าของงาน"


def compute(pushed: bool = False) -> dict:
    meta = jread("job.json")
    cfg = jread("config/config.json")
    gates = load_gates()
    S = []

    def add(phase, key, label, state, note="", who="", gate=""):
        S.append({"phase": phase, "key": key, "label": label, "state": state, "note": note, "who": who, "gate": gate})

    # ---- เปิดงาน
    iss = meta.get("issue")
    if not meta:
        add("เปิดงาน", "new", "สร้างงาน", BLOCK, "ไม่พบ job.json — งานนี้ไม่ได้สร้างด้วย workspace.py new-job (ใช้ import-job)", "เจ้าของงาน")
    elif meta.get("issue_unconfirmed"):
        add("เปิดงาน", "new", f"สร้างงาน · เลข #{iss} (ยังไม่ยืนยัน)", WAIT, "เลขคำนวณในเครื่อง — ยืนยันด้วยใบงานจริงก่อน import (workspace.py confirm-id)", "เจ้าของงาน")
    else:
        add("เปิดงาน", "new", f"สร้างงาน · ใบงาน #{iss}", DONE, meta.get("created_at", ""))
    exp = (cfg.get("paths") or {}).get("input_export_workflow", "input/blendata/export_workflow.json")
    if (ROOT / exp).exists() and meta.get("files_answered", True):
        add("เปิดงาน", "files", "วางไฟล์ · ตอบ 5 ข้อ", DONE, exp)
    else:
        add("เปิดงาน", "files", "วางไฟล์ · ตอบ 5 ข้อ", CUR, f"ยังไม่มี {exp}", "เจ้าของงาน")
    br = meta.get("branch", "")
    if pushed:
        add("เปิดงาน", "branch", "เปิด branch · push", DONE, br)
    elif br and git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{br}"):
        add("เปิดงาน", "branch", "เปิด branch · push", DONE, f"origin/{br}")
    elif br and git("rev-parse", "--verify", "-q", f"refs/heads/{br}"):
        add("เปิดงาน", "branch", "เปิด branch · push", CUR, f"มี {br} ในเครื่อง ยังไม่ push", "เจ้าของงาน")
    else:
        add("เปิดงาน", "branch", "เปิด branch · push", CUR, f"git switch -c {br or 'job/<P>/<job>/R01'}", "เจ้าของงาน")

    # ---- 6 ขั้นในแชท
    ref = [p for p in (ROOT / "input/odi_reference").glob("*") if p.suffix.lower() in (".xml", ".zip")] if (ROOT / "input/odi_reference").exists() else []
    ddl = list((ROOT / "input/oracle_ddl").glob("*.csv")) if (ROOT / "input/oracle_ddl").exists() else []
    lock = meta.get("target_lock") or {}
    ref = ref or bool(lock.get("smart_export"))      # สำเนา _shared_* ไม่ขึ้น Git — snapshot ของ branch อื่นดูจาก sha ที่ล็อก
    ddl = ddl or bool(lock.get("columns"))
    miss = [n for n, ok in (("export Blendata", (ROOT / exp).exists()), ("Smart Export", bool(ref)), ("คอลัมน์ปลายทาง (.csv)", bool(ddl))) if not ok]
    add("แชท", "01", "01 ตรวจไฟล์", DONE if not miss else CUR, "ครบ" if not miss else "ขาด " + ", ".join(miss), "" if not miss else "เจ้าของงาน")
    todo, n_ok, n_all = intake_state()
    if todo is None:
        add("แชท", "02", "02 ถาม–ตอบ", TODO, "ไม่พบ status/INTAKE.md")
    elif not todo:
        add("แชท", "02", "02 ถาม–ตอบ", DONE, f"I {n_ok}/{n_all}")
    else:
        add("แชท", "02", "02 ถาม–ตอบ", CUR, f"I {n_ok}/{n_all} · ค้าง {', '.join(todo[:4])}{' …' if len(todo) > 4 else ''} → /intake", "เจ้าของงาน")
    for key, label, g in (("03.1", "03.1 preflight", "G0"), ("03.2", "03.2 แปลง SQL", "G1"), ("03.3", "03.3 รีวิว", "G2")):
        st, note, who = gate_step(gates, g)
        add("แชท", key, f"{label} · {g}", st, note, who, g)
    st, note, who = gate_step(gates, "G3")
    grade = jread("output/verify/grade.json")
    if st == DONE and grade.get("grade") == "F":
        st, note, who = BLOCK, "เกรด F — ห้ามส่ง (ดู status/SUMMARY_04_PACKAGE.md)", "เจ้าของงาน"
    elif st == DONE and grade.get("grade"):
        note = f"เกรด {grade['grade']}"
    add("แชท", "04", "04 แพ็กเกจ · G3", st, note, who, "G3")

    # ---- ODI (คนทำในระบบจริง — ✓ เมื่อมีหลักฐาน)
    d = log_rows("status/DEPLOY_LOG.md", "DDL")
    if d and all(c for c in d[-1][:3]):
        add("ODI", "05.1", "05.1 รัน DDL", DONE, f"{d[-1][1]} · หลักฐาน {d[-1][2][:40]}")
    else:
        add("ODI", "05.1", "05.1 รัน DDL", TODO, "บันทึกใน status/DEPLOY_LOG.md พร้อมผล SELECT ที่ยืนยันตาราง", "เจ้าของงาน")
    imp = log_rows("status/IMPORT_LOG.md", "IMPORT")
    st, note, who = gate_step(gates, "G4")
    if st != DONE and not imp:
        st, note, who = TODO, "import-lock → Smart Import → import-unlock", "เจ้าของงาน"
    elif st == DONE and not imp:
        st, note, who = BLOCK, "สถานะไม่ตรง: G4 ผ่าน แต่ไม่มีบันทึก import ใน status/IMPORT_LOG.md", "เจ้าของงาน"
    add("ODI", "05.2", "05.2 Smart Import · G4", st, note, who, "G4")
    g5 = (gates or {}).get("G5") if gates and "_error" not in gates else None
    if g5:
        auto_ok = all(x for x, _ in g5["auto"])
        add("ODI", "05.3", "05.3 ทดสอบ · ความเร็ว", DONE if auto_ok else TODO,
            "assertions ผ่าน" + (" · " + rd("status/SUMMARY_05_PERFORMANCE.md").split("ระดับ:")[1].split("\n")[0].strip() if "ระดับ:" in rd("status/SUMMARY_05_PERFORMANCE.md") else "")
            if auto_ok else next((t for x, t in g5["auto"] if not x), "")[:90], "" if auto_ok else "เจ้าของงาน")
        man = {t.split()[0]: x for x, t in g5["manual"]}
        cmp_ok = man.get("G5.M2") and man.get("G5.M3")
        st6 = DONE if (cmp_ok and g5["status"] in ("PASS", "WAIVED")) else (WAIT if auto_ok and not cmp_ok else TODO)
        add("ODI", "06", "06 เทียบผล · G5", st6, "D2 diff = 0 · L1–L3 ตรง" if st6 == DONE else "รอผู้อนุมัติรับรองผลเทียบ (G5.M2 · M3)" if st6 == WAIT else "", "ผู้อนุมัติ" if st6 == WAIT else "", "G5")
    else:
        add("ODI", "05.3", "05.3 ทดสอบ · ความเร็ว", TODO)
        add("ODI", "06", "06 เทียบผล · G5", TODO)

    # ---- ส่งมอบ
    ho = [p for p in ROOT.glob("**/HAND*_*.md")] + [p for p in ROOT.glob("**/HANDOVER*.md") if "knowledge" not in p.parts and "templates" not in p.parts]
    add("ส่งมอบ", "handoff", "handoff · PR", DONE if ho else TODO, ho[0].name if ho else "/handoff")
    for key, label, g in (("cutover", "cutover · G6", "G6"), ("golive", "go-live · G7", "G7")):
        st, note, who = gate_step(gates, g)
        add("ส่งมอบ", key, label, st, note, who, g)

    # ---- ขั้นหลังขั้นแรกที่ยังไม่เสร็จ: แสดง ○ (ยกเว้น ✓ ที่ทำคู่ขนานไปแล้ว และ ⛔)
    first = next((i for i, s in enumerate(S) if s["state"] != DONE), None)
    parallel_left = 1 if first is not None and S[first]["state"] in (WAIT, BLOCK) else 0   # รอคนอยู่ → ทำขั้นถัดไปคู่ขนานได้ 1 ขั้น
    if first is not None:
        for s in S[first + 1:]:
            if s["state"] == CUR and parallel_left:
                parallel_left -= 1
                s["note"] = "ทำคู่ขนานได้ · " + s["note"]
                continue
            if s["state"] in (CUR, WAIT):
                s["state"], s["who"] = TODO, ""

    # ---- สถานะไม่ตรง: MIGRATION_STATUS บอกจบ แต่หลักฐานไม่ครบ
    ms = rd("status/MIGRATION_STATUS.md")
    if re.search(r"^\|\s*5\s*\|[^|]*\|\s*✅", ms, re.M) and not (ROOT / "output/verify/grade.json").exists():
        S[8]["state"], S[8]["note"] = BLOCK, "สถานะไม่ตรง: MIGRATION_STATUS บอก Phase 5 ✅ แต่ไม่มี output/verify/grade.json"

    n_done = sum(1 for s in S if s["state"] == DONE)
    cur = next((s for s in S if s["state"] != DONE), None)
    last = None
    for s in S:
        if s["state"] == DONE:
            last = s
    qs = open_questions()
    return {
        "job": ROOT.name, "project": meta.get("project", ""), "round": meta.get("round", "R01"), "branch": br,
        "owner": meta.get("owner", ""), "issue": iss, "id_base": (cfg.get("odi") or {}).get("id_base"),
        "steps": S, "done": n_done, "total": len(S), "current": cur, "last": last,
        "blocked": [s for s in S if s["state"] == BLOCK], "open_q": qs,
        "sql": sql_review_counts(), "grade": grade.get("grade"),
    }


HINT = {"01": "/next-step", "02": "/intake", "03.1": "/preflight", "03.2": "/convert", "03.3": "/review-sql → /review-report",
        "04": "/inputs → /gen-export → /verify", "05.1": "รัน output/ddl ด้วย run_sql.py (ขออนุญาตก่อน) หรือคนรันใน DBeaver · บันทึก DEPLOY_LOG",
        "05.2": "workspace.py import-lock", "05.3": "/run-pack", "06": "/validation → /compare-d2", "handoff": "/handoff",
        "cutover": "/cutover", "golive": "/gate G7", "branch": "git push -u origin HEAD (ถามก่อน)", "files": "วางไฟล์ตามที่ new-job บอก",
        "new": "workspace.py new-job"}


def box(r: dict) -> str:
    cur, last = r["current"], r["last"]
    sql = r["sql"]
    who = cur["who"] if cur else ""
    lines = [
        f"┌ สถานะ · {r['job']} · {r['round']}",
        f"│ ทำล่าสุด     : {last['label'] if last else '-'}",
        f"│ ความคืบหน้า : {r['done']} / {r['total']} ขั้น",
        f"│ ถัดไป       : {cur['label'] + ' — ' + HINT.get(cur['key'], '') if cur else 'ครบทุกขั้น'}",
        f"│ รอใคร       : {(who + ' · ' + cur['note']) if cur and who else '-'}",
        f"│ ติด         : {', '.join(b['label'] + ' (' + b['note'][:50] + ')' for b in r['blocked']) or 'ไม่มี'}",
    ]
    if sql:
        lines.append(f"│ ผลรีวิว SQL : ✅ {sql[0]} · 🟡 {sql[1]} · ⛔ {sql[2]}")
    if r["open_q"]:
        lines.append(f"│ คำถามเปิด   : {len(r['open_q'])} ข้อ ({', '.join(q for q, _ in r['open_q'][:5])}{' …' if len(r['open_q']) > 5 else ''})")
    lines.append("└")
    return "\n".join(lines)


def table(r: dict) -> str:
    out = [f"**{r['job']} · {r['round']} · branch {r['branch'] or '-'}** · ความคืบหน้า {r['done']} / {r['total']}",
           "✓ ทำแล้ว · ▶ กำลังทำ · ⏳ รอคน · ○ ยังไม่ทำ · ⛔ ติด", "",
           "| ช่วง | ขั้น | สถานะ | รายละเอียด / หลักฐาน |", "|---|---|---|---|"]
    prev = None
    for s in r["steps"]:
        ph = s["phase"] if s["phase"] != prev else ""
        prev = s["phase"]
        out.append(f"| {ph} | {s['label']} | {s['state']} | {s['note']}{' · รอ ' + s['who'] if s['state'] in (WAIT,) and s['who'] else ''} |")
    cur = r["current"]
    now = next((s for s in r["steps"] if s["state"] == CUR), None)
    out.append("")
    out.append(f"**ทำต่อได้เลย:** {now['label'] + ' — ' + HINT.get(now['key'], '') if now else 'ไม่มี (รอคน)' if cur else 'ครบทุกขั้น'}")
    if cur and cur["state"] in (WAIT, BLOCK):
        out.append(f"**รอ / ติด:** {cur['label']} — {cur['who'] or '-'} · {cur['note']}")
    if r["open_q"]:
        out.append(f"**คำถามเปิด:** " + " · ".join(f"{q} {t[:40]}" for q, t in r["open_q"][:6]))
    return "\n".join(out)


def modes() -> dict:
    """โหมดของงาน: github a/b/c · db auto/ask/human (job.json ชนะค่าทีม) — ให้ AI ใช้ตัดสินว่าใครรัน query / ใครแตะ GitHub"""
    try:
        jm = json.loads(rd("job.json") or "{}")
    except Exception:
        jm = {}
    t = {}
    for p in [ROOT, *ROOT.parents]:
        if (p / "workspace.json").exists():
            try:
                t = json.loads((p / "shared/team.json").read_text(encoding="utf-8"))
            except Exception:
                t = {}
            break
    db = t.get("db") or {}
    sel = db.get("select_mode") or ("auto" if db.get("default_mode") == "auto" else "ask")
    dbm = "human" if db.get("ai_access") != "ai" else (jm.get("db_mode") or sel)
    return {"github": jm.get("github_mode") or (t.get("github") or {}).get("mode", "a"), "db": dbm,
            "users": db.get("users", "split"), "read_odi_log": bool(db.get("read_odi_log"))}


def main():
    global ROOT
    ap = argparse.ArgumentParser()
    ap.add_argument("--box", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--modes", action="store_true", help="แสดงโหมด github / db ของงานนี้")
    ap.add_argument("--root")
    ap.add_argument("--pushed", action="store_true", help="snapshot มาจาก origin แล้ว (นับว่า push แล้ว)")
    a = ap.parse_args()
    if a.root:
        ROOT = Path(a.root).resolve()
    if a.modes:
        m = modes()
        print(json.dumps(m, ensure_ascii=False))
        print({"auto": "db=auto: AI รันได้ทุกคำสั่ง · SELECT รันต่อเนื่อง (run_sql.py --run-read) · คำสั่งที่เขียน / แก้โครงสร้างต้องถามคนก่อน (--plan → ถาม → --execute)",
               "ask": "db=ask: AI รันได้ทุกคำสั่ง แต่ต้องถามคนก่อนทุกครั้งรวม SELECT (run_sql.py --plan → ถาม 1 ให้ AI รัน / 2 ฉันรันเอง → --execute)",
               "human": "db=human: คนรันทั้งหมด — AI เตรียมไฟล์ + บอกขั้นตอนทีละไฟล์ (run_sql.py --plan)"}.get(m["db"], ""))
        return
    r = compute(pushed=a.pushed)
    if a.json:
        r2 = dict(r)
        r2["modes"] = modes()
        print(json.dumps(r2, ensure_ascii=False))
    elif a.box:
        print(box(r))
    else:
        print(table(r))


if __name__ == "__main__":
    main()
