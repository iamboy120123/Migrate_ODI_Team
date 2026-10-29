# Glossary

| คำ | ความหมาย |
|---|---|
| landing | ตารางรับข้อมูลดิบ (`tb_staging_ss_esim_landing_to_discovery_workflow_status`) แบ่งตาม `partition_minute` |
| staging / checkpoint | ตารางกลางของ workflow — checkpoint เก็บ partition ล่าสุดที่ประมวลผลแล้ว |
| valid / reject | ตารางผลลัพธ์: ผ่าน / ไม่ผ่านการตรวจ |
| MAN / TYP / LEN / DUP / COM | สถานะแถว: ขาดค่าบังคับ / ชนิดผิด / ยาวเกิน / ซ้ำ / ผ่าน (ชื่อจริงดูใน SQL ของ workflow) |
| wpd | `workflow_process_date` — เวลาเริ่มรอบ (สร้างใน step running) |
| courier loop | agent สร้างสคริปต์ → SA รันใน DBeaver/ODI → วางผลใน `input/run_results/<pack>/` → agent อ่าน (ADR-003) |
| Run Pack | ชุดสคริปต์ + ขั้นตอนต่อหนึ่งรอบทดสอบ (`run_packs/rpNN_*`) |
| D1 / D1+ / D2 / D3 / D4 | ระดับการพิสูจน์: PySpark รัน raw SQL / D1 หลาย case / seed คู่ทั้งสองฝั่ง / backtest ข้อมูลจริง / parallel run |
| Gate G0–G7 / Verify V1–V9, V12 | ดู `status/GATES.md`, `scripts/checks/verify_all.py` และ `knowledge/reference/claude-system.md` |
| rp00 / P1–P5 | Run Pack ตรวจ environment ของ Phase 0 (`/preflight`): env/NLS, สิทธิ์, ชนิดคอลัมน์ landing, work repo, Spark config |
| review log | `status/PHASE4_REVIEW_LOG.md` — 1 แถว/ประเด็น สถานะ OPEN / FIXED / ACCEPTED / NO_CHANGE (G2) |
| K# | บั๊ก/การแก้ของ kit ที่ต้อง backport (`status/MIGRATION_STATUS.md` หัวข้อ Kit) |
| I# / BR-nn / GAP-nn | คำถาม intake / business rule / gap — ดู `knowledge/WORKFLOW.md` §2 |
| D-R1–D-R9 | กฎแปลง SQL (`knowledge/reference/spark-to-oracle-sql.md`) · `/sql-check` ตรวจอัตโนมัติ D-R1–D-R8 |
