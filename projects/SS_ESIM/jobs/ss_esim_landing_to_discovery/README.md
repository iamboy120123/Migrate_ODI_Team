# โปรเจกต์ migrate Blendata (Spark SQL) -> ODI 14c / Oracle 19c

อ่านไฟล์นี้ก่อน — ทุกโฟลเดอร์ในโปรเจกต์มีบทบาทเดียว ดูตารางด้านล่างว่าอะไรเป็นของใคร

## แผนที่โฟลเดอร์

| โฟลเดอร์ / ไฟล์ | คืออะไร | ใครเขียนลง |
|---|---|---|
| `CLAUDE.md`, `.claude/` | กฎ + คำสั่ง (`/convert`, `/gen-export`, `/status` ...) + ผู้ช่วยเฉพาะทางของ Claude | ระบบ (setup) |
| `input/` | **ไฟล์จริงของคุณ**: `config.json`, `export_workflow.json`, `ddl/`, ไฟล์ที่ AI ขอเพิ่ม | คุณ |
| `references/` | ของอ้างอิง: `smart_export/` (ของ repository ปลายทาง), field template, `example/` (ตัวอย่างทั้งหมดรวมที่เดียว — ห้ามใช้เป็นข้อมูลจริง) | คุณ / kit |
| `output/` | ผลที่ระบบสร้าง: `sql/` (raw -> converted), `dml/`, `odi_export/` (XML ที่ import), `ddl/`, `dba/`, `validation/`, `backfill/`, `verify/` — ลบแล้วสร้างใหม่ได้ | ระบบ |
| `run_packs/` | ใบงานให้คนไปรันบน Oracle / ODI และREPORT.md | ระบบ + คุณ |
| `status/` | **เอกสารที่คนตัดสินใจและติดตาม**: `MIGRATION_STATUS.md`, `OPEN_DECISIONS.md`, `GATES.md`, `PREFLIGHT_CHECKLIST.md`, `PHASE4_REVIEW_LOG.md`, `REVIEW_FLAGS.md`, `CUTOVER_RUNBOOK.md` (+ `INTAKE.md`, `BUSINESS_RULES.md`, `GAP_ANALYSIS.md` ถ้าใช้ workflow md) | คุณ + Claude |
| `.design/` | เอกสารออกแบบ: `specs/` (ต่อ task), `adr/`, `diagrams/` | Claude |
| `knowledge/` | คู่มือ + ความรู้ประจำโปรเจกต์: `migration-rules`, `intake-questions`, `spark-to-oracle-sql`, `delivery-checklist`, `validation-and-cutover`, ... (ดูตารางใน `CLAUDE.md` หัวข้อ 10) · `knowledge/reference/` อ่านอย่างเดียว · แก้ได้เฉพาะ glossary / environment-facts / lessons-learned / WORKFLOW | ระบบ (reference/) + คุณ/Claude |
| `scripts/` | โปรแกรม (ดูข้างล่าง) — ไม่แก้เองระหว่างงาน | kit |

## `scripts/` แยกตามขั้นงาน

| โฟลเดอร์ | ทำอะไร |
|---|---|
| `pipeline/` | สายพานแปลง: `extract_workflow` -> `convert_sql` -> `gen_dml` -> `build_odi_export` (builder ของ md15 ใน `scripts/odi_builder/`) -> `validate_odi_xml` · เสริม: `sync_guid_from_export`, `gen_ddl`, `gen_dba_prereq`, `gen_design_docs`, `gen_backfill`, `agent_reviewer` (โหมด auto) |
| `runpack/` | `gen_preflight_pack`, `gen_run_pack` (สร้างใบงานให้คนรัน) · `read_run_results` (อ่านผลที่วางกลับ) · `gen_validation` (query เทียบผล) |
| `checks/` | `verify_all` (ตรวจทุกชั้นแบบ offline) · `check_gate` (ผ่านด่าน G0-G7 หรือยัง) · `check_sql` (กฎ D-R1–D-R8 กับ SQL) · `extract_partitions` |
| `testing/` | `make_mock_sql` · `spark_reference_run` · `compare_tables` (ทดสอบ SQL บน Spark เทียบ) · `run_d1` (รัน Spark SQL ต้นฉบับเทียบหลายค่าตั้งค่า) · `compare_results` (เทียบผลระดับแถว Blendata vs Oracle) |
| `hooks/` | ตัวกัน AI แก้ไฟล์ต้องห้าม (ผูกใน `.claude/settings.json`) |

## ลำดับงาน (ย่อ)

1. วางไฟล์เก่าจาก Blendata ทั้งหมดที่ `input/blendata/` (export_workflow.json บังคับ · เอกสาร / ข้อมูลเทส / expected_results.csv / .sql มีก็วาง), `input/odi_reference/*.xml`, `input/oracle_ddl/*`
2. `/preflight` -> `/intake` -> `/convert` -> `/review-sql` -> `/inputs` (ของต้องครบ) -> `/gen-export`
3. **Smart Import** `output/odi_export/<package>.zip` เข้า ODI Studio **ครั้งเดียว** (Overwrite ถ้าชื่อตรงของเดิม) -> `/run-pack` -> `/read-results` (หลังจากนี้เป็นเรื่องทดสอบ)
4. `/validation` -> `/compare-d2` -> `/cutover`
5. ไม่แน่ใจว่าถึงไหน: `/status` หรือ `/next-step`

กฎสำคัญ: ไม่รัน DDL/DML กับฐานข้อมูลเอง · ไม่ใส่รหัสผ่านในไฟล์ · ไม่สร้าง Scenario ที่ compile แล้ว (generate ใน Studio) · ไฟล์ใน `references/` และ `input/export_workflow.json` อ่านอย่างเดียว

โปรเจกต์นี้สร้างจาก `setup_migrate.ps1` — ไม่มีแม่แบบหรือตัวติดตั้งปนอยู่ในโฟลเดอร์นี้ (ถ้าต้องการอัปเดต ให้รัน `setup_migrate.ps1 -Mode InPlace` จากไฟล์ต้นทาง)

## v18: เลือกวิธีใส่ schema ใน SQL (`schema_mode` ใน config/config.json)

ODI ไม่เติม schema ให้ SQL ที่อยู่ใน Procedure (ไม่มี schema = ORA-00942 ตอนรัน, กฎ D-R2) `convert_sql.py` จึงใส่ให้ตามที่เลือก:

| `schema_mode` (ไม่ตั้ง = `literal`) | ผลใน SQL | ต้องมีใน config | หมายเหตุ |
|---|---|---|---|
| `literal` | `dssdev.tb_xxx` | `target_table_prefix` เช่น `"dssdev."` | ตรงกับ md15 ที่ import ผ่านจริง |
| `odiref` | `<%=odiRef.getSchemaName("DSSDEV","D")%>.tb_xxx` | `odi.logical_schema` | ODI แปลงเป็น schema จริงจาก Topology ตอนรัน ย้าย Dev/Prod ได้โดยไม่แก้ SQL — **ยังไม่ได้ทดสอบใน Studio** |

`to_date(col)` / `to_timestamp(text,'yyyyMMddHHmmss')` แปลงตามกฎ md15 (D-R6/D-R8): ถ้า DDL (`input/oracle_ddl/*.csv`) ระบุว่าคอลัมน์เป็น DATE/TIMESTAMP แล้ว -> `TRUNC(col)`;
`to_timestamp` ของ text -> `CASE WHEN REGEXP_LIKE(...) THEN TO_TIMESTAMP(... DEFAULT NULL ON CONVERSION ERROR, ...) END`;
คอลัมน์ที่ไม่มีใน DDL **ไม่ถูกเดา** (ถูก flag ให้ไปเอา DDL มาเพิ่ม)
`build_odi_export.py` ไม่สร้าง package ถ้า `status/REVIEW_FLAGS.md` ยังมีแถว PENDING

### v18: เลือกได้ว่ากฎแปลงเชิงกลไกข้อไหนให้แปลงเอง (`convert_rules` ใน config/config.json)

แต่ละข้อตั้งเป็น `"auto"` (แปลงให้) หรือ `"flag"` (ไม่แตะ ปล่อยให้ติด PENDING ใน `status/REVIEW_FLAGS.md` ให้คน/AI แก้เอง) ไม่ใส่ = `auto`:
`get_user` (→`USER`) · `format_string` (→`LPAD(TO_CHAR(..),N,'0')`) · `date_format` (→`TO_CHAR`, เฉพาะ mask ที่รู้จัก) ·
`order_by_const` (→`ORDER BY NULL`) · `like_escape` (เติม `ESCAPE '\'`) · `cast_types` (`long/string/int/...`→ชนิด Oracle) ·
`interval` (ใส่ quote) · `bigint_ctor` (→`TO_NUMBER`) · `nullif_empty` (`nullif(x,'')`→`x` ผลข้างเคียง: ค่าเว้นวรรค `' '` ยังไม่เป็น NULL)

ส่วนที่ md15 ระบุว่า **ต้องให้คนตัดสิน** (`concat` หลาย arg / NULL propagation, `split`/`reverse`, `regexp_extract`, `TRUE`/`FALSE`, `to_date` ไม่มี DDL) ไม่มีกฎ auto ติด PENDING เสมอ

### v18: `concat_policy` (ผู้ใช้ตอบนโยบายเดียวต่อโปรเจกต์ ไม่มีค่าตั้งต้น)

`concat()` ของ Spark คืน NULL ถ้ามี argument ใดเป็น NULL แต่ `||` ของ Oracle มอง NULL เป็นค่าว่าง (md15 C1/C2) kit จึงไม่เลือกให้:

| `concat_policy` | ผลใน SQL |
|---|---|
| `spark_null` | `CASE WHEN a IS NULL OR b IS NULL THEN NULL ELSE a \|\| b END` (คงพฤติกรรม Spark) |
| `plain_concat` | `(a \|\| b)` (NULL กลายเป็นค่าว่าง ผลต่างจาก Spark เมื่อมี NULL) |
| ว่าง/ไม่ตั้ง | ไม่แปลง ติด PENDING ใน `status/REVIEW_FLAGS.md` ให้คนตัดสิน |

นโยบายใช้กับ `concat` ทุกจุดของโปรเจกต์ (`concat(x)` argument เดียวตัดทิ้งเสมอ) agent ต้องถามผู้ใช้ในแชตก่อนตั้งค่า (ดู `CLAUDE.md` ข้อ 8a)

