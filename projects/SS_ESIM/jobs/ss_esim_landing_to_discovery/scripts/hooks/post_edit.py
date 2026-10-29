"""
PostToolUse hook (Edit|Write|MultiEdit) — warn เท่านั้น ไม่ block  (P2 2026-09-29)
  - แก้ output/sql/converted/*.sql → รัน static check (V1) ของไฟล์นั้นทันที + เตือนว่า XML stale ต้อง /gen-export
  - แก้ scripts/*.py → py_compile + เตือนให้บันทึกใน "Kit — สิ่งที่แก้"
ส่งข้อความกลับให้ agent ทาง hookSpecificOutput.additionalContext
"""
import json
import py_compile
import sys

from _common import ROOT, read_event, rel_path

for _d in ("pipeline", "checks"):
    sys.path.insert(0, str(ROOT / "scripts" / _d))


def say(msg):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}, ensure_ascii=False))
    sys.exit(0)


def main():
    ev = read_event()
    rp = rel_path(ev)
    if rp.startswith("output/sql/converted/") and rp.endswith(".sql"):
        from verify_all import static_check_sql
        issues = static_check_sql(ROOT / rp)
        msg = [f"[post_edit] แก้ {rp.split('/')[-1][:60]} → PROJ_EXPORT.xml stale: ต้อง /gen-export (gen_dml → build_odi_export → validate) ก่อนสร้าง Run Pack"
               ", บันทึกใน status/PHASE4_REVIEW_LOG.md และแจ้ง SA ให้ Smart Import แบบ Overwrite"]
        msg += [f"  {s}: {m}" for s, m in issues] or ["  V1 static: ผ่าน"]
        say("\n".join(msg))
    if rp.startswith("scripts/") and rp.endswith(".py") and ".bak-" not in rp:
        try:
            py_compile.compile(str(ROOT / rp), doraise=True, cfile=str(ROOT / "output" / "verify" / "_pyc" / "hook.pyc"))
            ok = "py_compile ผ่าน"
        except py_compile.PyCompileError as e:
            ok = "py_compile FAIL: " + str(e).splitlines()[-1][:200]
        say(f"[post_edit] แก้ kit script {rp} — {ok} · บันทึกใน status/MIGRATION_STATUS.md หัวข้อ 'Kit — สิ่งที่แก้/เพิ่ม' (K#) + backup .bak-YYYYMMDD")
    sys.exit(0)


if __name__ == "__main__":
    main()
