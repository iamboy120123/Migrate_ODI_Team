---
description: ขั้น 1.5 — สร้าง/อัปเดต Business Rules Catalog (status/BUSINESS_RULES.md) จาก raw Spark SQL ทีละ task พร้อมโยง converted SQL, gap และ test
argument-hint: "[task code เช่น 040000 | all]"
---
1. อ่าน `output/sql/raw/<task>.sql` (ความจริงของ As-Is), `output/sql/converted/<task>.sql`, `status/PHASE4_REVIEW_LOG.md`, `status/BUSINESS_RULES.md` เดิม, `.design/specs/<task>.md`
2. ต่อ task ($ARGUMENTS, ว่าง = all) ดึงกฎทุกข้อ: เงื่อนไขอ่าน/กรอง, การ derive คอลัมน์, dedup, การกำหนด status และลำดับความสำคัญ, guard/idempotency, lookup join (INNER join ที่ทำให้แถวหายเงียบ = BR แยก), การเขียน (overwrite/append/merge)
3. 1 แถว = 1 กฎ ในหมวด A–E · `ที่มา` = clause ของ raw SQL ที่อ้างตรงตัว · ห้ามเดาเจตนา — ถ้าความหมายเชิงธุรกิจไม่ชัด ใส่ในคอลัมน์ SA ว่า "ต้องยืนยัน ..."
4. ใส่วิธีของ Oracle (จาก converted) · ถ้าผลต่างจาก Spark ใส่ `GAP-nn` (สร้างใน `/gap-analysis` ถ้ายังไม่มี) · ใส่ test case ที่ครอบคลุม (rp* `TEST_CASE`)
5. **ห้ามติ๊ก SA แทน** — คงเป็น ⬜ จนกว่า SA ยืนยันในแชต
6. อัปเดตหัวข้อ "สรุปความครอบคลุม test" → BR ที่ไม่มี test ส่งให้ subagent `test-designer` ก่อน G5
7. เติม Business logic / Rules ใน `.design/specs/<task>.md` ให้อ้างเลข BR (ใช้ `spec-writer`) แล้ว `/update-status`