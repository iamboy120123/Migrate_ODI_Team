---
description: Phase 4 — ให้ subagent sql-reviewer ตรวจ SQL ที่ถูก flag (ระบุ task id ได้)
argument-hint: "[task_id ...]"
---
ใช้ subagent `sql-reviewer` ตรวจ task: $ARGUMENTS (ถ้าว่าง = ทุก task ใน `status/REVIEW_FLAGS.md`)
- ส่ง path ของ `output/sql/raw/<task>.sql` และ `output/sql/converted/<task>.sql` ให้ subagent เทียบ
- เมื่อได้ผล: แก้ใน `output/sql/converted/` เฉพาะข้อที่ **ไม่เปลี่ยน business logic**; ข้อที่เปลี่ยน semantics → ลง `status/OPEN_DECISIONS.md`
- บันทึกทุกประเด็นในตาราง "บันทึกต่อ task" ของ `status/PHASE4_REVIEW_LOG.md` — 1 แถว/ประเด็น, คอลัมน์แรก = task id ตาม `status/REVIEW_FLAGS.md`, คอลัมน์สุดท้าย = สถานะ `OPEN` / `FIXED` / `ACCEPTED` / `NO_CHANGE` (G2 ตรวจ auto: ทุก task ที่ถูก flag ต้องมีแถว และไม่มี OPEN)
- เปลี่ยน flag ใน `status/REVIEW_FLAGS.md` เป็น `RESOLVED` เมื่อทุกแถวของ task นั้นไม่ใช่ OPEN · `ACCEPTED` ต้องมี Q ที่ SA ปิดแล้วหรือ ADR
- ต่อด้วย subagent `semantic-verifier` กับ task ที่แก้ — DIFF = แก้หรือเปิด Q (`/decide`), NEEDS-D1 = บันทึกเป็นข้อค้างของ G5
- `python scripts/checks/check_gate.py G2` — ถ้า BLOCKED เพราะ Q Spark config ยังเปิด ให้เสนอ `/preflight` (P5) · PASS แล้วจึงเสนอ `/gen-export`
