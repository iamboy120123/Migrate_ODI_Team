"""
Stop hook — warn (systemMessage) ถ้ามีไฟล์งานถูกแก้หลัง status/MIGRATION_STATUS.md แต่ rev ยังไม่ขยับ  (P2 2026-09-29)
ไม่ block การจบ turn (ตามที่ตกลง: remind = warn)
"""
import json
import sys

from _common import ROOT, read_event

WATCH = ["output/sql/converted", "output/dml", "output/odi_export", "run_packs", "scripts", ".design",
         "status/OPEN_DECISIONS.md", "status/PREFLIGHT_CHECKLIST.md", "status/PHASE4_REVIEW_LOG.md", "status/GATES.md", "config/config.json", "knowledge"]


def main():
    ev = read_event()
    if ev.get("stop_hook_active"):
        sys.exit(0)
    st = ROOT / "status/MIGRATION_STATUS.md"
    if not st.exists():
        sys.exit(0)
    t0 = st.stat().st_mtime
    changed = []
    for w in WATCH:
        p = ROOT / w
        files = [p] if p.is_file() else (list(p.rglob("*")) if p.is_dir() else [])
        for f in files:
            if f.is_file() and ".bak-" not in f.name and "__pycache__" not in f.parts and f.stat().st_mtime > t0 + 2:
                changed.append(f.relative_to(ROOT).as_posix())
    if changed:
        print(json.dumps({"systemMessage": f"[remind_status] มี {len(changed)} ไฟล์ถูกแก้หลัง status/MIGRATION_STATUS.md "
                          f"(เช่น {', '.join(changed[:3])}) — รัน /update-status ก่อนจบงาน"}, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
