# INTAKE — คำถาม I1–I17 (ตาม knowledge/reference/intake-questions.md) — SS_ESIM_L2D

Updated: 2026-10-29 · สร้างโดย `setup_migrate.ps1` จาก `config/config.json` · ใช้กับ `/intake` · ข้อเหล่านี้ใช้ตัว `I` เพื่อไม่ชนกับ Q ของ `status/OPEN_DECISIONS.md` · รายละเอียดต่อข้อ: `knowledge/reference/intake-questions.md`

- ver 6: I1, I2, I5, I9, I11, I17 ตอบจากไฟล์ / ค่าเริ่มต้นแล้ว (ไม่ถาม) · I4, I7, I8, I13, I14, I16 ถามเป็นคำยืนยันครั้งเดียว · ตารางที่ตัด/ลด: knowledge/reference/intake-questions.md หัวข้อ "ver 6"
- ✅ = มีคำตอบพร้อมแหล่งที่มา · ⬜ = ต้องถาม SA (ทีละข้อ ตามกฎการถามใน intake-questions.md) · ⚠️ = ตอบแล้วแต่มีเงื่อนไขค้าง
- คำตอบที่มาจาก config = ค่าที่ตั้งตอน setup — SA ยืนยันอีกครั้งตอน `/intake`

| # | หัวข้อ | คำตอบ | แหล่งที่มา | สถานะ |
|---|---|---|---|---|
| I1 | โฟลเดอร์งาน Blendata ต้นทาง | `input/blendata/export_workflow.json` | config `paths.input_export_workflow` | ✅ |
| I2 | ไฟล์ reference SmartExport จาก repository ปลายทาง | `input/odi_reference/_shared_smart_export_DEV_20261028.xml` | config `odi.*`, `input/odi_reference/` | ✅ |
| I3 | โครงสร้างคอลัมน์ตารางปลายทาง (DDL) | `input/oracle_ddl/_shared_all_tab_columns.csv` | `input/oracle_ddl/`, rp00 P3 | ✅ |
| I4 | Oracle schema และวิธี qualify | schema / user / prefix อ่านจาก Smart Export แล้ว: `DSSDEV` / `dssdev.` · ถามเฉพาะวิธี qualify → Q "Schema qualification" ใน `status/OPEN_DECISIONS.md` | config `odi.*` (จาก Smart Export) | ⬜ |
| I5 | ODI ProjectName | SS_ESIM_L2D | config `odi.project_name` | ✅ |
| I6 | ProjectCode / prefix เดิมที่ต้อง rename | SS_ESIM_L2D | config `odi.project_code` | ✅ |
| I7 | FolderName | SS_ESIM_L2D | config `odi.folder_name` | ✅ |
| I8 | PackageName | PKG_SS_ESIM_L2D | config `odi.package_name` | ✅ |
| I9 | path ไฟล์ปลายทาง | output/odi_export/PROJ_EXPORT.xml | builder md15 (build_odi_export.py) | ✅ |
| I10 | ความพร้อมของ SQL | _(raw Spark SQL ใน `output/sql/raw/` · สถานะ Phase 4 ดู `status/REVIEW_FLAGS.md`)_ | `/convert`, `/review-sql` | ⬜ |
| I11 | สถาปัตยกรรม Procedure / Mapping / ผสม | Procedure 1 task = 1 procedure (ADR-001) — task ต่าง technology พิจารณา Mapping แยก | ADR-001 | ✅ |
| I12 | ทาสก์ที่ implement ตรง ๆ ไม่ได้ | _(ถาม SA)_ | config `scope.excluded_tasks` (+ Q ใน OPEN_DECISIONS) | ⬜ |
| I13 | ลำดับ step chain | _(จาก DAG / `.design/03_package_flow.md` หลัง `/gen-export`)_ | `.design/` | ⬜ |
| I14 | overwrite / append / upsert + column list | load strategy `smart` · partition: `config/partitions_check.csv` | config, D-R7 | ⚠️ ถามต่อ task: DELETE หรือ TRUNCATE - AI เลือกเองไม่ได้ |
| I15 | step สถานะ (success / running / checkpoint) | _(จาก SQL — ดู Q เรื่อง boolean / status table)_ | raw SQL | ⬜ |
| I16 | สภาพ repository ปลายทาง | ODI 14.1.2 · work repo schema `?` · context `DEV` · logical schema `DSS_ODI_LOG` · variables: v_max_partition, v_lag_minutes | config `odi.*`, rp00 P4 | ⚠️ ยืนยัน project ซ้ำใน Studio |
| I17 | รูปแบบ output | Smart Import XML จาก kit + เอกสารส่งมอบ (`HANDOVER.md`, table inventory) | setup_migrate.ps1 (generator = kit) | ✅ |