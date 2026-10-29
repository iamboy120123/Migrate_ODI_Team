# PHASE4 REVIEW LOG — ss_esim_landing_to_discovery (Blendata → ODI)

Updated: 2026-10-29 · บันทึกผล Phase 4 (`/review-sql` → `sql-reviewer` → `semantic-verifier`) ต่อ task
ใช้โดย: gate **G2** (`verify_all.py` V4 — ทุก task ใน `status/REVIEW_FLAGS.md` ต้องมีแถวที่นี่ และไม่มีสถานะ `OPEN`) · G2.M1 (SA ตรวจไฟล์นี้)

## วิธีบันทึก

- 1 แถว = 1 ประเด็น ของ 1 task · คอลัมน์แรก = task id ตรงกับ `status/REVIEW_FLAGS.md` · **คอลัมน์สุดท้าย = สถานะ**
- สถานะ: `OPEN` (ยังไม่จบ) · `FIXED` (แก้ใน converted แล้ว, semantics เท่าเดิม) · `ACCEPTED` (ต่างจาก Spark แต่มี Q/ADR ที่ SA ปิดแล้ว) · `NO_CHANGE` (ตรวจแล้วไม่ต้องแก้)
- เปลี่ยน semantics = `ใช่` → ต้องมี Q ใน `status/OPEN_DECISIONS.md` (ปิดโดย SA) หรือ ADR ก่อนเป็น `ACCEPTED` — agent ห้ามตัดสินเอง
- semantic-verifier: `PASS` (หา counter-example ไม่ได้) · `FAIL <case>` · `-` (ยังไม่รัน)

## Spark config ที่ใช้ตีความ (Q3)

| config | ค่า (Blendata) | แหล่งที่มา |
|---|---|---|
| `spark.sql.ansi.enabled` | _(รอ Q3)_ | |
| `spark.sql.legacy.timeParserPolicy` | _(รอ Q3)_ | |
| `spark.sql.parser.escapedStringLiterals` | _(รอ Q3)_ | |

## บันทึกต่อ task

| Task | ประเด็น / flag | ผลตรวจ (sql-reviewer) | การแก้ใน converted | เปลี่ยน semantics? | semantic-verifier | Q / ADR | สถานะ |
|---|---|---|---|---|---|---|---|

## ประวัติ

- 2026-10-29: สร้างจาก kit 2.8.1 (2026-10-14)
