# WORKFLOW — คู่มือใน knowledge/ เป็นแกน + SA governance ของ kit

> แกนขั้นตอน = `knowledge/reference/migration-rules.md` หัวข้อ 3 (7 ขั้น) · ส่วนเสริม = Business Rules, Gap Analysis, Confirm Decision, Status/Gate จาก kit
> ติดตั้งโดย `setup_migrate.ps1` 2.10.0 (2026-10-29) เมื่อ 2026-10-29 · **generator ของ XML = `build_odi_export.py` (builder ของ md15)** (reuse GlobalId เมื่อชื่อ project/folder/package ตรงกับ build ก่อน = import ทับได้, ชื่อไม่ตรง = project ใหม่; `_guid_keys.json`/`_guid_map.json`, G3/G4/V2, `/sync-guid`) · `scripts/checks/check_sql.py` + `knowledge/reference/delivery-checklist.md` เป็นด่านตรวจเพิ่ม
> อ่านไฟล์นี้เมื่อไม่แน่ใจว่าอยู่ขั้นไหน · `/next-step` ใช้ตารางนี้ตัดสินขั้นถัดไป

## 1. ภาพรวม

| ขั้น | งานหลัก (knowledge/) | ส่วนเสริม (kit + ใหม่) | ไฟล์ผลลัพธ์ | Gate / ผู้อนุมัติ | คำสั่ง |
|---|---|---|---|---|---|
| 0 Start / Resume | อ่านสถานะก่อนเสมอ (`knowledge/reference/migration-rules.md`) | อ่าน `status/MIGRATION_STATUS.md` + `status/OPEN_DECISIONS.md` ก่อนเสมอ | – | – | `/next-step` |
| 1 Intake | ถาม I1–I17 ทีละข้อ (`knowledge/reference/intake-questions.md`) — เติมคำตอบจาก config/STATUS ให้ก่อน ถามเฉพาะ ⬜ · สรุป business flow | Preflight P1–P5 (rp00) | `status/INTAKE.md`, `.design/02_architecture.md` | **G0** PREFLIGHT 5/5 · SA | `/intake` · `/preflight` |
| 1.5 Business Rules | – | **BR Catalog** จาก raw Spark SQL ทีละ task (filter / derive / dedup / status / guard) | `status/BUSINESS_RULES.md` | SA ยืนยัน BR (คอลัมน์ "SA") | `/br-catalog` |
| 2 SQL | แปลงตาม `knowledge/reference/spark-to-oracle-sql.md` (กลุ่ม A, D-R1–D-R8) + `check_sql.py` | `convert_sql.py` → `status/REVIEW_FLAGS.md` · `/review-sql` → `status/PHASE4_REVIEW_LOG.md` · semantic-verifier · **Gap Analysis** | `output/sql/converted/`, `status/GAP_ANALYSIS.md` | **G1**, **G2** (+ G2.M1 SA) | `/convert` · `/sql-check` · `/review-sql` · `/gap-analysis` |
| 2D Confirm Decision | ("ต้องให้คนตัดสิน" ใน `knowledge/reference/spark-to-oracle-sql.md`) | gap ที่ต่างจาก Spark / เปลี่ยน semantics → Q ใน `status/OPEN_DECISIONS.md` · ออกแบบ → ADR | `status/OPEN_DECISIONS.md`, `.design/adr/` | SA (`✅ SA YYYY-MM-DD`) | `/decide` · `/adr` |
| 3–5 Build | อ่าน reference → build spec → ประกอบ XML → checklist `knowledge/reference/delivery-checklist.md` | `gen_dml.py` → `build_odi_export.py` → `validate_odi_xml.py` · xml-auditor · `/sql-check dml` | `output/dml/`, `output/odi_export/<package>.zip` (+ `PROJ_EXPORT.xml`, `build-spec.json`) | **G3** | `/gen-export` |
| 6 Handover / Import | handover-report + table-inventory (`knowledge/reference/deliverables.md`) | DDL/DBA prereq (แยกจาก package) · **Smart Import ครั้งเดียว** (`<package>.zip`, Overwrite ถ้าชื่อตรง) หลัง `/inputs` ผ่าน · `/sync-guid` ไม่บังคับ (เฟสทดสอบ) | `output/ddl/`, `output/dba/`, `HANDOVER.md` | **G4** (+ M1, M2 SA) | `/gen-ddl` · `/sync-guid` · `/handoff` |
| 7 Validate / Cutover | `knowledge/reference/validation-and-cutover.md` 4 ระดับ (row count → sum → row-level → parallel run) | Run Pack courier loop · test case ครอบคลุม **ทุก BR** · D1/D2 · `status/CUTOVER_RUNBOOK.md` | `run_packs/*/REPORT.md`, `D2_REPORT.md` | **G5**, **G6**, **G7** | `/run-pack` · `/read-results` · `/validation` · `/compare-d2` · `/cutover` |
| ทุกขั้น | – | **Status**: `/update-status` (rev+1) · บทเรียน `/lesson` · ความขัดแย้ง state-auditor | `status/MIGRATION_STATUS.md`, `knowledge/` | – | `/update-status` · `/gate` · `/verify` |

## 2. เลขอ้างอิง (ห้ามปนกัน)

| Prefix | ความหมาย | ไฟล์ต้นฉบับ |
|---|---|---|
| `I1`–`I17` | คำถาม intake (รายละเอียดต่อข้อใน `knowledge/reference/intake-questions.md`) | `status/INTAKE.md` |
| `Q<n>` | การตัดสินใจที่ SA ต้องปิด | `status/OPEN_DECISIONS.md` |
| `BR-<nn>` | business rule ที่ดึงจาก Spark SQL | `status/BUSINESS_RULES.md` |
| `GAP-<nn>` | ความต่าง As-Is ↔ To-Be | `status/GAP_ANALYSIS.md` |
| `D-R<n>` | กฎแปลง SQL | `knowledge/reference/spark-to-oracle-sql.md` |
| `L<n>` | บทเรียนที่เจอจริง (เลขเคสเดิม 1–41 ของชุดคู่มือเก่าเทียบได้ในตารางท้ายไฟล์) | `knowledge/lessons-learned.md` |
| `G<n>` / `V<n>` / `K<n>` / `W<n>` | gate / verify / การแก้ kit / waiver | `status/GATES.md`, `verify_all.py`, STATUS §6 |

## 3. เส้นโยง (traceability)

`BR-nn` → task + clause ใน raw SQL → expression ใน converted SQL → แถวใน `status/PHASE4_REVIEW_LOG.md` → (ถ้าต่าง) `GAP-nn` → `Q<n>` ที่ SA ปิด → test case ใน Run Pack (`TEST_CASE` อ้าง BR) → ผล D2

- BR ทุกข้อต้องมี test case อย่างน้อย 1 ก่อน G5 · GAP ทุกข้อต้องมี disposition (K/M/A/R) และ Q/ADR ถ้าไม่ใช่ Keep
- disposition: **K** Keep (ผลเท่าเดิม) · **M** Modify (เปลี่ยนวิธี ผลเท่าเดิม) · **A** Accept (ผลต่าง ยอมรับโดย Q) · **R** Remove/Defer (ตัดออก/เลื่อน)

## 4. กฎที่ใช้ร่วมกัน (ถ้าขัดกัน ใช้ลำดับนี้)

1. การตัดสินใจของ SA ใน `status/OPEN_DECISIONS.md` / `status/GATES.md` (Waiver)
2. `CLAUDE.md` + `.claude/rules/*` ของ kit
3. `knowledge/reference/` (D-R*, checklist, ข้อห้ามใน migration-rules.md หัวข้อ 7)

ความขัดแย้งที่รู้แล้ว: **D-R2 (คู่มือ: qualify schema ทุกตาราง) ↔ odi-step-sql ข้อ 6 (kit: ห้าม hardcode schema)** → Q "Schema qualification" ใน `status/OPEN_DECISIONS.md` · ระหว่างรอ ใช้กฎ kit · ถ้า SA เลือกไม่ใส่ schema ให้บันทึก waiver ของ D-R2 ใน `status/GATES.md`
ERROR ของ `check_sql.py` ที่รู้ว่าเป็น false positive: D-R3 `;` ท้ายไฟล์ใน `output/dml/` (generator ตัดออกตอนสร้าง XML — ตรวจใน `PROJ_EXPORT.xml`)