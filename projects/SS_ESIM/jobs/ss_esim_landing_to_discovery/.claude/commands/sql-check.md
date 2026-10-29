---
description: ด่านตรวจ SQL — รัน scripts/checks/check_sql.py (D-R1–D-R8) กับ converted SQL / DML พร้อม --ddl และ --partitions ถ้ามี
argument-hint: "[converted | dml]"
---
1. โฟลเดอร์ = `output/sql/converted` (default) หรือ `output/dml` ถ้า $ARGUMENTS = dml (D-R1 column list / D-R7 TRUNCATE ตรวจได้ที่ DML เท่านั้น)
2. ถ้ายังไม่มี `config/partitions_check.csv` → `python scripts/checks/extract_partitions.py <export json> -o config/partitions_check.csv`
3. `python scripts/checks/check_sql.py <โฟลเดอร์> [--ddl input/oracle_ddl/<ไฟล์>] [--partitions config/partitions_check.csv]` — ไม่มี DDL ให้บอกว่า D-R5/D-R6 ชั้น 2–3 ยัง UNCHECKED (INTAKE I3)
4. สรุปตาราง rule / จำนวน ERROR / WARN · กฎที่ขัดกับ kit (D-R2 ↔ odi-step-sql ข้อ 6) **ห้ามแก้ SQL ตาม D-R2 จนกว่า Q "Schema qualification" ปิด** — ลำดับกฎอยู่ใน `knowledge/WORKFLOW.md` §4 · D-R3 `;` ในไฟล์ DML = ตรวจใน `PROJ_EXPORT.xml` ก่อนสรุป
5. finding ใหม่ที่เป็นปัญหาจริง → แถวใน `status/PHASE4_REVIEW_LOG.md` (OPEN) + `status/GAP_ANALYSIS.md` ถ้าผลต่างจาก Spark · WARN ที่ตรวจแล้วไม่ต้องแก้ → บันทึก NO_CHANGE พร้อมเหตุผล ห้ามแก้ SQL เพียงให้ WARN หาย (md D-R8)