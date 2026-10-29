---
description: Phase 1-3 — แตก SQL จาก Blendata export และแปลง dialect เป็น Oracle
---
0. อ่าน `status/PREFLIGHT_CHECKLIST.md` — ถ้ายังไม่ครบ 5/5 และ export ไม่ใช่ไฟล์ตัวอย่าง ให้หยุดและแจ้ง SA ว่าข้อไหนค้าง
1. ตรวจว่า `config/config.json` → `paths.input_export_workflow` ชี้ไฟล์ที่มีอยู่จริง
2. รัน `python scripts/pipeline/extract_workflow.py` แล้ว `python scripts/pipeline/convert_sql.py`
3. สรุปจาก `output/sql/raw/_manifest.json`: จำนวน task, task ที่อยู่ใน `scope.excluded_tasks`, task ที่ไม่ใช่ SQL
4. ใช้ subagent `conversion-auditor` หา pattern ที่ converter พลาดโดยไม่ flag — task ที่ควร flag เพิ่ม ให้เพิ่มแถว PENDING ใน `status/REVIEW_FLAGS.md` (ระบุว่ามาจาก conversion-auditor); rule ใหม่ของ kit → เสนอ SA (K#)
5. ถ้ามีผล P3 (`all_tab_columns`) ของ `/preflight` แล้ว: `python scripts/checks/verify_all.py --level V6` ตรวจ data contract ก่อน review
6. สรุป `status/REVIEW_FLAGS.md` เป็นตาราง task / flag / ความเสี่ยง แล้วเสนอให้รัน `/review-sql`
