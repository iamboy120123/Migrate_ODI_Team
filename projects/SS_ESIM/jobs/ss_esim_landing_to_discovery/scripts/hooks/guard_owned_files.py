"""
PreToolUse hook (Edit|Write|MultiEdit) — กันไม่ให้ agent ตัดสินใจแทน SA  (P2 2026-09-29)

Block (exit 2) เมื่อ:
  1. แก้ไฟล์ที่เป็นของ generator / ของจริงจากระบบต้นทาง: PROJ_EXPORT.xml, _guid_map.json,
     input/**/export_workflow.json, input/odi_reference/*.xml, knowledge/reference/** (อ้างอิงกลาง อ่านอย่างเดียว), input/blendata/** (ไฟล์เก่าจาก Blendata ทั้งโฟลเดอร์)
  2. ติ๊ก [X] ใน status/OPEN_DECISIONS.md หรือ status/GATES.md โดยบรรทัดนั้นไม่มี "✅ SA YYYY-MM-DD"
  3. เพิ่ม ✅ ใน status/PREFLIGHT_CHECKLIST.md โดยแถวนั้นไม่มี "SA" + วันที่
  4. เปลี่ยน ADR เป็น "Status: Accepted" (SA แก้เองเท่านั้น)
  5. เพิ่มแถว waiver ใน status/GATES.md โดยไม่มี "SA" + วันที่
agent บันทึกคำตอบที่ SA บอกในแชตได้ แต่ต้องใส่ "✅ SA <วันที่>" ในบรรทัดเดียวกันเสมอ (audit trail)
"""
import re
import sys

from _common import read_event, rel_path, before_after, added_lines

LOCKED = [r"^output/odi_export/PROJ_EXPORT\.xml$", r"^output/odi_export/_guid_(?:map|keys)\.json$",
          r"^input/.*export_workflow\.json$", r"^input/odi_reference/.*\.xml$",
          r"^knowledge/reference/", r"^input/blendata/"]
SA_MARK = re.compile(r"✅\s*SA\s*\d{4}-\d{2}-\d{2}")
SA_DATE = re.compile(r"\bSA\b.*\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}.*\bSA\b")


def block(msg):
    sys.stderr.write("[guard_owned_files] BLOCKED: " + msg +
                     "\nถ้า SA ตัดสินแล้วในแชต ให้ใส่ '✅ SA <YYYY-MM-DD>' ในบรรทัดเดียวกัน / ถ้าเป็นไฟล์ของ generator ให้แก้ที่ต้นทางแล้ว regenerate\n")
    sys.exit(2)


def main():
    ev = read_event()
    rp = rel_path(ev)
    if not rp:
        sys.exit(0)
    for rx in LOCKED:
        if re.search(rx, rp):
            block(f"`{rp}` เป็นไฟล์ที่ห้าม agent แก้ (CLAUDE.md §5)")
    name = rp   # path เต็มแบบ relative (ไฟล์สถานะอยู่ใน status/)
    watched = name in ("status/OPEN_DECISIONS.md", "status/GATES.md", "status/PREFLIGHT_CHECKLIST.md") or rp.startswith(".design/adr/")
    if not watched:
        sys.exit(0)
    old, new = before_after(ev)
    add = added_lines(old, new)
    if name in ("status/OPEN_DECISIONS.md", "status/GATES.md"):
        for l in add:
            if re.match(r"^\s*-\s*\[[xX]\]", l) and not SA_MARK.search(l):
                block(f"{name}: ติ๊ก [X] โดยไม่มี '✅ SA YYYY-MM-DD' → `{l.strip()[:90]}`")
    if name == "status/GATES.md":
        for l in add:
            if re.match(r"^\|\s*W\d+\s*\|", l) and not SA_DATE.search(l):
                block(f"status/GATES.md: waiver ต้องมีผู้อนุมัติ SA + วันที่ → `{l.strip()[:90]}`")
    if name == "status/PREFLIGHT_CHECKLIST.md":
        for l in add:
            if re.match(r"^\|\s*\d+\s*\|\s*✅", l) and not (SA_DATE.search(l) or "Setup.ps1 (auto)" in l):
                block(f"PREFLIGHT: เปลี่ยนเป็น ✅ ต้องระบุ SA + วันที่ → `{l.strip()[:90]}`")
    if rp.startswith(".design/adr/"):
        for l in add:
            if re.match(r"^\s*-\s*Status:\s*Accepted", l, re.I):
                block(f"{name}: เปลี่ยน ADR เป็น Accepted ได้เฉพาะ SA (CLAUDE.md §7) — agent สร้างได้แค่ Proposed")
    sys.exit(0)


if __name__ == "__main__":
    main()
