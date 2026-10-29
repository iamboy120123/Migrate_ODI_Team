"""
workspace.py — Migration Workspace (Blendata → ODI 14c) สำหรับทีม · รันที่ root ของ workspace

ตั้งทีม (ครั้งเดียว)
  init                       ตั้งทีม 12 ข้อ (ของกลาง DEV · ผู้อนุมัติ · โหมด AI กับ GitHub / ฐานข้อมูล)
  init-github                CODEOWNERS · PR template · CI 4 ตัว · labels · ใบงานปักหมุด "ODI_DEV กำลังใช้งาน"
งาน
  new-job                    เปิดงานใหม่ (3 ข้อ + วางไฟล์ 5 ข้อ) · ขอเลขจากใบงาน GitHub ตามที่เลือก
  confirm-id --job J         ยืนยันเลขที่คำนวณในเครื่อง (แบบคำนวณในเครื่อง) ด้วยเลขใบงานจริง
  import-job PATH --project P [--job J]   ย้ายงานเก่าเข้า workspace + จองเลขย้อนหลัง
  new-round --job J          รอบใหม่ (ROUNDS.md · branch · GlobalId เดิม)
  release --job J            ยกเลิกงาน (ปิดใบงาน พร้อมเหตุผล · เลขไม่ถูกใช้ซ้ำ)
  set-mode --job J [--github a|b|c] [--db auto|ask|human]   เปลี่ยนโหมดของงาน (ขั้น 02)
ODI_DEV
  import-lock --job J        ตรวจเลข + ใส่ชื่อในใบงานล็อกก่อน Smart Import
  import-unlock [--job J] [--force --reason "…"]   เอาชื่อออก + บันทึก IMPORT_LOG
  lock-status · jobs-board   ใครใช้ ODI_DEV · ใบงานที่จองไปแล้ว (อ่านอย่างเดียว)
ของกลาง / kit
  db-connect [--env SIT]     เพิ่ม / แก้การเชื่อมต่อฐาน (ไม่มีรหัสผ่านในไฟล์) แล้วทดสอบ
  update-target [--fetch-columns]  รับไฟล์ใหม่จาก shared/target/_incoming/ (ตรวจ → diff → archive → บอกงานที่กระทบ) · --fetch-columns = ดึงคอลัมน์จากฐานเอง
  sync-kit [--job J | --all] [--force]   วาง kit + ของกลางลงงาน (หยุดถ้ามีการแก้ kit ค้าง)
  link-shared · slim-job · unslim --job J · fix-mtime
  kit-promote --job J        ส่งการแก้ kit ในงานกลับเข้า kit/ (PR แยก)
  extract-kit SETUP.ps1      เปลี่ยน kit/setup_migrate.ps1 เป็นรุ่นใหม่ (ต้อง backport CHANGES-ws ก่อน)
ดูสถานะ / ตรวจ
  status [--job J] [--all] [--pick N] [--no-fetch]   ตารางบนจอ · เลือกเลขเพื่อดูงานนั้นทุกขั้น
  report [--no-fetch]        STATUS.md + registry/ จาก main + ทุก origin/job/*
  check [--ci]               ตรวจก่อน commit / import

ตัวเลือกร่วม: --yes = คุณยืนยันเองล่วงหน้า (ใช้กับคำสั่งที่ถามก่อนเขียน GitHub) — AI ห้ามใส่ --yes แทนคน
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wscore import common as C  # noqa: E402


def build() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="workspace.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)
    sp = ap.add_subparsers(dest="cmd")
    p = sp.add_parser("init"); p.add_argument("--reconfigure", action="store_true")
    p = sp.add_parser("init-github"); p.add_argument("--force", action="store_true")
    p = sp.add_parser("new-job"); p.add_argument("--project"); p.add_argument("--job"); p.add_argument("--id-source", choices=["ก", "ข", "ค", "a", "b", "c"]); p.add_argument("--issue")
    p = sp.add_parser("confirm-id"); p.add_argument("--job", required=True); p.add_argument("--issue")
    p = sp.add_parser("import-job"); p.add_argument("path"); p.add_argument("--project", required=True); p.add_argument("--job"); p.add_argument("--issue")
    p = sp.add_parser("new-round"); p.add_argument("--job", required=True); p.add_argument("--reason"); p.add_argument("--kind", choices=["remigrate", "fix", "target"])
    p = sp.add_parser("release"); p.add_argument("--job", required=True); p.add_argument("--reason")
    p = sp.add_parser("set-mode"); p.add_argument("--job", required=True); p.add_argument("--github"); p.add_argument("--db")
    p = sp.add_parser("import-lock"); p.add_argument("--job", required=True); p.add_argument("--skip-odi-check", action="store_true")
    p = sp.add_parser("import-unlock"); p.add_argument("--job"); p.add_argument("--force", action="store_true"); p.add_argument("--reason"); p.add_argument("--result", choices=["ok", "fail"])
    sp.add_parser("lock-status"); sp.add_parser("jobs-board")
    p = sp.add_parser("db-connect"); p.add_argument("--env", help="DEV / SIT / PROD …")
    p = sp.add_parser("update-target"); p.add_argument("--reason"); p.add_argument("--fetch-columns", action="store_true", help="ดึงคอลัมน์จากฐานเอง (ทีมอนุญาต AI ต่อฐาน)")
    for name in ("sync-kit", "link-shared", "slim-job"):
        p = sp.add_parser(name); p.add_argument("--job"); p.add_argument("--all", action="store_true"); p.add_argument("--force", action="store_true")
    p = sp.add_parser("unslim"); p.add_argument("--job", required=True)
    sp.add_parser("fix-mtime")
    p = sp.add_parser("kit-promote"); p.add_argument("--job", required=True); p.add_argument("--k"); p.add_argument("--reason")
    p = sp.add_parser("extract-kit"); p.add_argument("setup"); p.add_argument("--force", action="store_true")
    p = sp.add_parser("status"); p.add_argument("--job"); p.add_argument("--all", action="store_true"); p.add_argument("--pick"); p.add_argument("--no-fetch", action="store_true")
    p = sp.add_parser("report"); p.add_argument("--no-fetch", action="store_true")
    p = sp.add_parser("check"); p.add_argument("--ci", action="store_true")
    return ap


def main(argv=None):
    ap = build()
    a = ap.parse_args(argv)
    C.ASSUME_YES = bool(a.yes)
    if not a.cmd:
        ap.print_help()
        return 0
    from wscore import check, init, jobs, lock, status, target
    table = {
        "init": init.run_init, "init-github": init.run_init_github,
        "new-job": jobs.run_new_job, "confirm-id": jobs.run_confirm_id, "import-job": jobs.run_import_job,
        "new-round": jobs.run_new_round, "release": jobs.run_release, "set-mode": jobs.run_set_mode,
        "import-lock": lock.run_import_lock, "import-unlock": lock.run_import_unlock,
        "lock-status": lock.run_lock_status, "jobs-board": lock.run_jobs_board,
        "db-connect": lambda x: __import__("wscore.db", fromlist=["db"]).run_db_connect(x),
        "update-target": lambda x: (C.require_workspace(), target.run_update_target(x)),
        "sync-kit": jobs.run_sync_kit, "link-shared": jobs.run_link_shared, "slim-job": jobs.run_slim, "unslim": jobs.run_unslim,
        "fix-mtime": jobs.run_fix_mtime, "kit-promote": jobs.run_kit_promote, "extract-kit": jobs.run_extract_kit,
        "status": status.run_status, "report": status.run_report, "check": check.run_check,
    }
    try:
        table[a.cmd](a)
        return 0
    except C.Stop as e:
        print()
        C.fail(str(e))
        return 1
    except KeyboardInterrupt:
        print()
        C.info("หยุดตามที่สั่ง — คำตอบที่ตอบแล้วถูกบันทึกไว้ (ถ้ามี)")
        return 130


if __name__ == "__main__":
    sys.exit(main())
