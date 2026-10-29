# GAP ANALYSIS — As-Is (Blendata / Spark SQL) ↔ To-Be (ODI / Oracle) — SS_ESIM_L2D

Updated: 2026-10-29 · โครงสร้างโดย `setup_migrate.ps1` · เติมด้วย `/gap-analysis` จาก `status/PHASE4_REVIEW_LOG.md`, `status/OPEN_DECISIONS.md`, `status/BUSINESS_RULES.md`, `knowledge/reference/spark-to-oracle-sql.md`, `knowledge/reference/validation-and-cutover.md`, `knowledge/lessons-learned.md`, `output/verify/sql_check_*.txt`

- Disposition: **K** Keep · **M** Modify (เปลี่ยนวิธี ผลเท่าเดิม) · **A** Accept (ผลต่าง ยอมรับโดย Q) · **R** Remove/Defer
- ผลกระทบ: **H** เปลี่ยนตัวเลข/แถวที่ downstream เห็น · **M** บางคอลัมน์ / ข้อมูลขอบ · **L** ไม่กระทบผลลัพธ์
- ทุกแถวที่ไม่ใช่ K ต้องมี Q/ADR ที่ SA ปิดแล้ว · "ยืนยันด้วย" = หลักฐานที่ต้องมีก่อน G5/G6

## 1. Semantics ของข้อมูล

| GAP | เรื่อง | As-Is (Spark) | To-Be (Oracle) | BR | กระทบ | Disp. | Q / ADR | ยืนยันด้วย | สถานะ |
|---|---|---|---|---|---|---|---|---|---|

## 2. พฤติกรรมของ workflow / การรัน

| GAP | เรื่อง | As-Is | To-Be | BR | กระทบ | Disp. | Q / ADR | ยืนยันด้วย | สถานะ |
|---|---|---|---|---|---|---|---|---|---|

## 3. Scope ของ task

| GAP | Task | As-Is | To-Be | Disp. | Q | สถานะ |
|---|---|---|---|---|---|---|

## 4. Platform / ODI

| GAP | เรื่อง | ข้อเท็จจริง | Disp. | Q | สถานะ |
|---|---|---|---|---|---|

## 5. สรุป

| สถานะ | GAP |
|---|---|
| เปิด — ต้องให้ SA ตัดสิน | |
| เปิด — ต้องมีหลักฐาน/test | |
| ปิดแล้ว รอยืนยันใน D1/D2 | |
| ข้อสังเกต (ผลเท่ากันทั้งสองฝั่ง) | |

## Checklist gap ที่พบบ่อย (ไล่ให้ครบ แล้วลบ/ติ๊กเมื่อบันทึกเป็น GAP หรือยืนยันว่าไม่เกี่ยว)

- [ ] `''` vs NULL (`= ''`, `<> ''`, `nullif(x,'')`, `coalesce(x,'')`, `concat` เมื่อมี NULL)
- [ ] `spark.sql.legacy.timeParserPolicy` (EXCEPTION = ทั้งรอบ error, Oracle = NULL)
- [ ] ค่าวันที่สั้นกว่า pattern (D-R8 / L37) — ต้องมี shape guard หรือ mask `FX` + test แถวสั้นกว่า pattern
- [ ] `spark.sql.parser.escapedStringLiterals` กับ regex / LIKE escape
- [ ] `now()` precision / timezone (`spark.sql.session.timeZone` vs DB)
- [ ] `get_user()` → `USER`
- [ ] boolean → VARCHAR2 / NUMBER
- [ ] overwrite ตาราง partition: ห้าม TRUNCATE ทั้งตารางเอง · ถามเลือกต่อ task (I14: DELETE เฉพาะ partition ใน SELECT / TRUNCATE PARTITION / TRUNCATE ทั้งตารางเมื่อยืนยันว่าว่าง) + ยืนยัน `spark.sql.sources.partitionOverwriteMode` (D-R7 / L29, `config/partitions_check.csv`)
- [ ] status table ที่ schema เปลี่ยนตาม overwrite (guard รอบค้าง)
- [ ] ลำดับไม่แน่นอน (`ROW_NUMBER() over(order by 1)`, tie, `NULLS FIRST`)
- [ ] INNER JOIN กับ master/lookup ที่ทำให้แถวหายเงียบ
- [ ] task non-SQL (recover / retention / export ต่าง technology)
- [ ] ความยาว string (Spark ไม่จำกัด, Oracle VARCHAR2)
- [ ] schema qualification (D-R2 ↔ kit V3)
- [ ] Oracle version ของ Dev ≠ Prod (19c)
- [ ] schedule / timezone ของ DAG และ alert / recovery