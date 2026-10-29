"""
run_sql.py — รัน SQL / Run Pack บนฐานข้อมูล แบบขออนุญาตก่อนทุกครั้ง (2.10.0) · ตัวรันเดียวของงาน

ใช้ได้ทั้งคนใน Terminal และ AI ใน Claude Code:

  คนใน Terminal (ถามเป็นเลขบนจอ):
    python scripts/runpack/run_sql.py rp01                 # แสดงแผน → 1 ให้ระบบรัน / 2 ฉันรันเอง
    python scripts/runpack/run_sql.py output/ddl/01_create_tables.sql --env DEV

  AI (ไม่มีจอให้ตอบ — ต้องถามคนในแชทก่อน):
    1) python scripts/runpack/run_sql.py <เป้าหมาย> --plan      # แสดงแผน + คำถาม → AI ถามคนในแชท (ตอบเป็นเลข)
    2) คนตอบ 1 → python scripts/runpack/run_sql.py --execute <แผน> --approved "<ชื่อคน> <วันที่>" [--confirm ตาราง1,ตาราง2]
       คนตอบ 2 → python scripts/runpack/run_sql.py --human <แผน>   # ขั้นตอนให้คนรัน ทีละไฟล์
                 รันเสร็จ → python scripts/runpack/run_sql.py --record-human <แผน> --result "<ผลที่คนบอก>"
    SELECT ล้วน + ทีมตั้ง select_mode = auto → python scripts/runpack/run_sql.py <เป้าหมาย> --run-read (ไม่ต้องถาม)

  ตัวเลือกอื่น: --env SIT (ฐานอื่นที่ตั้งด้วย workspace.py db-connect) · --only S2b,S2c (เฉพาะไฟล์ที่ขึ้นต้นตามนี้) · --compile (คอมไพล์ SELECT แบบ WHERE 1=0)

กติกา: ทีมตั้งให้คนรัน (init ข้อ 9) → ระบบไม่รันอะไรเลย แค่บอกขั้นตอน · คำสั่งที่เขียน / แก้โครงสร้างถามเสมอ ·
คำสั่งที่ลบแล้วกู้คืนไม่ได้ (DROP · TRUNCATE · DELETE / UPDATE ไม่มี WHERE · ALTER … DROP) ต้องยืนยันชื่อตาราง ·
ไฟล์ที่แก้หลังแสดงแผน = รันไม่ได้ (ต้องขออนุญาตใหม่) · ทุกครั้งที่รันบันทึกใน status/DB_RUN_LOG.md (+ DEPLOY_LOG.md เมื่อเขียน)
รายละเอียดกติกา: scripts/runpack/dbx.py · kit/CLAUDE.kit.md หัวข้อ "AI กับฐานข้อมูล"
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dbx  # noqa: E402

EXIT_NEED_APPROVAL = 3


def ai_hint(plan: dict):
    print()
    print("👉 สำหรับ AI: ถามคนในแชทด้วยข้อความ ❓ ด้านบน (ตอบเป็นเลข · ห้ามเลือกแทนคน)")
    conf = f" --confirm {','.join(plan['destructive'])}" if plan["destructive"] else ""
    print(f"   ตอบ 1 → python scripts/runpack/run_sql.py --execute {plan['id']} --approved \"<ชื่อคนที่อนุญาต> {dt.date.today()}\"{conf}")
    if plan["destructive"]:
        print(f"           (ต้องให้คนพิมพ์ชื่อตาราง {', '.join(plan['destructive'])} ในแชทก่อน แล้วใส่ใน --confirm ตามที่คนพิมพ์)")
    print(f"   ตอบ 2 → python scripts/runpack/run_sql.py --human {plan['id']} แล้วบอกคนทีละไฟล์")


def show_human(plan: dict):
    print(f"ขั้นตอนให้คนรันเอง — ฐาน {plan['env']} · แผน {plan['id']} (บอกคนทีละไฟล์ ไม่ส่งรวดเดียว)")
    for line in dbx.human_steps(plan):
        print(line)
    print(f"รันเสร็จแล้ว: python scripts/runpack/run_sql.py --record-human {plan['id']} --result \"<ผลที่คนบอก>\" แล้วตรวจผลด้วย SELECT")


def interactive_flow(plan: dict) -> int:
    print(dbx.render(plan))
    todo = dbx.write_todo(plan)
    if todo:
        print(f"  → รายการให้คนทำ: {dbx._rel(todo)}")
    if not plan["items"]:
        show_human(plan) if plan["ai_access"] != "ai" else None
        return 0
    if dbx.needs_question(plan):
        print()
        print(dbx.question_text(plan))
        print("   ถ้าไม่ตอบ    กด Enter = เลือก 1 · ? = อธิบายละเอียด")
        while True:
            a = input("   คำตอบ [Enter = 1]: ").strip() or "1"
            if a == "?":
                print("   ℹ️  1 = ระบบต่อฐานแล้วรันคำสั่งตามแผนด้านบนเท่านั้น (บันทึกทุกครั้ง) · 2 = ระบบบอกขั้นตอนให้คุณรันเองใน DBeaver ทีละไฟล์")
                continue
            if a in ("1", "2"):
                break
            print("   ⚠️  ตอบได้: 1 หรือ 2")
        if a == "2":
            show_human(plan)
            return 0
    confirm = []
    for t in plan["destructive"]:
        v = input(f"   ⚠️  พิมพ์ชื่อตาราง {t} เพื่อยืนยันว่าจะลบ / ล้าง (Enter เปล่า = ยกเลิก): ").strip()
        if not v:
            print("   ยกเลิก — ไม่ได้รันอะไร")
            return 0
        confirm.append(v)
    res = dbx.execute(plan, f"คนที่ Terminal ({dbx._who()})", confirm, interactive=True)
    print(f"ผลอยู่ที่ {plan['out']}/ · บันทึกใน status/DB_RUN_LOG.md")
    return 0 if res["ok"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="ชื่อ pack (rp01) · โฟลเดอร์ · ไฟล์ .sql")
    ap.add_argument("--env")
    ap.add_argument("--only")
    ap.add_argument("--compile", action="store_true")
    ap.add_argument("--plan", action="store_true", help="แสดงแผน + คำถาม ไม่ต่อฐาน")
    ap.add_argument("--run-read", action="store_true", help="SELECT ล้วน · รันได้เลยเฉพาะเมื่อทีมตั้ง select_mode = auto")
    ap.add_argument("--execute", metavar="PLAN", help="รันตามแผนที่คนอนุญาตแล้ว")
    ap.add_argument("--approved", help="ใครอนุญาต (ชื่อ + วันที่) — บังคับกับ --execute")
    ap.add_argument("--confirm", help="ชื่อตารางที่คนพิมพ์ยืนยัน (คำสั่งที่ลบแล้วกู้คืนไม่ได้)")
    ap.add_argument("--human", metavar="PLAN", help="แสดงขั้นตอนให้คนรันเอง")
    ap.add_argument("--record-human", metavar="PLAN", help="บันทึกว่าคนรันเองแล้ว")
    ap.add_argument("--result", help="ผลที่คนบอก (ใช้กับ --record-human)")
    a = ap.parse_args()

    if a.execute:
        if not (a.approved or "").strip():
            raise SystemExit("[ERROR] --execute ต้องมี --approved \"<ชื่อคนที่อนุญาต> <วันที่>\" — ถามคนก่อนเสมอ ห้ามอนุญาตแทนคน")
        plan = dbx.load_plan(a.execute)
        print(dbx.render(plan))
        res = dbx.execute(plan, a.approved.strip(), (a.confirm or "").split(","))
        print(f"ผลอยู่ที่ {plan['out']}/ · บันทึกใน status/DB_RUN_LOG.md" + (" · ต่อไป: /read-results" if any(i["kind"] == "read" for i in plan["items"]) else ""))
        return 0 if res["ok"] else 1
    if a.human:
        show_human(dbx.load_plan(a.human))
        return 0
    if a.record_human:
        plan = dbx.load_plan(a.record_human)
        ts = dt.datetime.now().isoformat(timespec="seconds")
        for it in plan["items"]:
            dbx._log(f"{ts} HUMAN-RAN {plan['env']} plan={plan['id']} {it['file']}: {a.result or ''}",
                     [ts, plan["env"], plan["id"], it["file"], "คนรันเอง", a.result or "-", "คน"],
                     dbx.deploy_row(it, ts, plan["env"], a.result or "-", "คนรันเอง") if it["kind"] != "read" else None)
        print(f"✅ บันทึกแล้ว ({len(plan['items'])} ไฟล์) — ต่อไป: ตรวจผลด้วย SELECT")
        return 0
    if not a.target:
        ap.error("ต้องระบุเป้าหมาย (pack / โฟลเดอร์ / ไฟล์ .sql) หรือ --execute / --human / --record-human")

    plan = dbx.make_plan(a.target, a.env, a.only, a.compile)
    if a.run_read:
        print(dbx.render(plan))
        dbx.write_todo(plan)
        if not plan["items"]:
            return 0
        if plan["has_write"] or plan["select_mode"] != "auto":
            print()
            print(dbx.question_text(plan))
            print("[ต้องขออนุญาต] " + ("แผนนี้มีคำสั่งที่เขียน / แก้โครงสร้าง" if plan["has_write"] else "ทีมตั้งให้ถามก่อนทุกครั้งรวม SELECT (select_mode = ask)"))
            ai_hint(plan)
            return EXIT_NEED_APPROVAL
        res = dbx.execute(plan, "select_mode=auto (ทีมอนุญาต SELECT ต่อเนื่อง)", read_only_call=True)
        print(f"ผลอยู่ที่ {plan['out']}/ · ต่อไป: /read-results {plan['target']}")
        return 0 if res["ok"] else 1
    if a.plan or not sys.stdin.isatty():
        print(dbx.render(plan))
        todo = dbx.write_todo(plan)
        if todo:
            print(f"  → รายการให้คนทำ: {dbx._rel(todo)} (บอกคนทีละไฟล์)")
        if plan["ai_access"] != "ai":
            print("\nทีมตั้งให้คนรันทั้งหมด (init ข้อ 9) — ระบบไม่รัน")
            show_human(plan)
            return 0
        if plan["items"]:
            print()
            print(dbx.question_text(plan))
            if dbx.needs_question(plan):
                ai_hint(plan)
                return EXIT_NEED_APPROVAL
            print(f"\nSELECT ล้วน + select_mode = auto → รันได้เลย: python scripts/runpack/run_sql.py {a.target} --run-read")
        return 0
    return interactive_flow(plan)


if __name__ == "__main__":
    sys.exit(main())
