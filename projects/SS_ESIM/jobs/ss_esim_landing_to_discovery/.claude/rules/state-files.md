---
paths:
  - "status/MIGRATION_STATUS.md"
  - "status/OPEN_DECISIONS.md"
  - "status/PREFLIGHT_CHECKLIST.md"
  - "status/GATES.md"
  - "status/PHASE4_REVIEW_LOG.md"
  - "status/REVIEW_FLAGS.md"
  - "status/CUTOVER_RUNBOOK.md"
  - ".design/adr/**"
---
# กฎไฟล์สถานะ (hook `guard_owned_files` บังคับบางข้อ — รู้ก่อนดีกว่าโดน block)

1. `[x]` ใน `status/OPEN_DECISIONS.md` / `status/GATES.md` ต้องมี `✅ SA YYYY-MM-DD` บรรทัดเดียวกัน · ✅ ใน `status/PREFLIGHT_CHECKLIST.md` ต้องมี SA + วันที่ · waiver ต้องมีผู้อนุมัติ SA + วันที่ — agent บันทึกแทนได้**เฉพาะเมื่อ SA ยืนยันในแชต**
2. ADR: agent สร้างได้แค่ `Proposed` — เปลี่ยนเป็น `Accepted` ได้เฉพาะ SA
3. `status/MIGRATION_STATUS.md`: เพิ่ม rev ทุกครั้งที่จบ step (`Updated: YYYY-MM-DD (rev.N)`) · ห้ามลบประวัติ · ทุก Q ที่ยังเปิดต้องถูกอ้างใน STATUS (V4 WARN) · ห้ามเขียนว่า "ปิดครบ" ถ้ายังมี Q เปิด (V4 FAIL)
4. `status/PHASE4_REVIEW_LOG.md`: 1 แถว/ประเด็นในหัวข้อ "บันทึกต่อ task", คอลัมน์แรก = task id, คอลัมน์สุดท้าย = `OPEN` / `FIXED` / `ACCEPTED` / `NO_CHANGE` (G2 auto)
5. `status/REVIEW_FLAGS.md` generate โดย `convert_sql.py` — agent เปลี่ยนได้แค่ `PENDING` → `RESOLVED` (หรือเพิ่มแถวจาก conversion-auditor)
6. `status/CUTOVER_RUNBOOK.md`: ช่องที่ต้องตัดสินใจคง `_(TBD)_` + อ้าง Q จนกว่า SA/Business ตอบ (V9)
7. ห้ามลบไฟล์ — แทนด้วยการเขียนทับหรือ backup `*.bak-YYYYMMDD`
8. ก่อน `/update-status` ใช้ `state-auditor` หาความขัดแย้ง
