<!-- ส่วนที่เหมือนกันทุกงาน (ย้ายมาจาก CLAUDE.md ของงานโดย slim-job) · แก้ผ่าน PR ของ kit เท่านั้น -->

## 0. Workflow หลัก (คู่มือใน knowledge/ เป็นแกน)

ลำดับขั้นยึด `knowledge/reference/migration-rules.md` หัวข้อ 3 + ส่วนเสริมของ kit — ตารางรวมอยู่ที่ **`knowledge/WORKFLOW.md`** (อ่านเมื่อไม่แน่ใจว่าอยู่ขั้นไหน)
- ไฟล์เพิ่ม: `status/INTAKE.md` (I1–I17) · `status/BUSINESS_RULES.md` (BR-nn) · `status/GAP_ANALYSIS.md` (GAP-nn) — คำสั่ง `/intake` `/br-catalog` `/gap-analysis` `/sql-check`
- XML สร้างด้วย `scripts/pipeline/build_odi_export.py` (builder ของ md15) เท่านั้น ห้ามใช้ `scripts/_deprecated/` · `scripts/checks/check_sql.py` + `knowledge/reference/delivery-checklist.md` = ด่านตรวจเพิ่ม
- กฎขัดกัน: OPEN_DECISIONS/GATES > CLAUDE.md + rules ของ kit > `knowledge/reference/` · D-R2 (qualify schema) ↔ rule ห้าม hardcode schema → ดู Q "Schema qualification"
- **overwrite: AI ห้ามเลือก DELETE หรือ TRUNCATE เอง** — อ่าน `sinkOption.partitions` + `partitionOverwriteMode` ของ Spark แล้วถาม I14 ทีละ task พร้อมตัวอย่างคำตอบ · partitions ว่าง = `TRUNCATE` + `INSERT` (2 step) · ไม่ว่าง = ให้ผู้ใช้เลือก DELETE เฉพาะ partition ที่อยู่ใน SELECT (รูปแบบมาตรฐาน `knowledge/reference/spark-to-oracle-sql.md` หัวข้อ "overwrite เฉพาะ partition") / `TRUNCATE PARTITION` / `TRUNCATE` ทั้งตาราง · คำตอบบันทึกลง `status/OPEN_DECISIONS.md` ต่อ task
- `/intake` เริ่มโดยยังไม่มี DDL จริงใน `input/oracle_ddl/` → เตือนก่อนว่า column list / ชนิดข้อมูลจะเป็นการเดา ให้ผู้ใช้เลือกรอ DDL หรือไปต่อโดยรับความเสี่ยงเป็นลายลักษณ์อักษร
- ไฟล์สถานะทั้งหมดอยู่ใน `status/` · `scripts/` แยก `pipeline/ runpack/ checks/ testing/ hooks/`
- `knowledge/reference/**` เป็นอ้างอิงกลาง ห้ามแก้ (hook กัน) — แก้ได้เฉพาะ `knowledge/lessons-learned.md`, `environment-facts.md`, `glossary.md`, `WORKFLOW.md` · `status/INTAKE.md`, `status/BUSINESS_RULES.md`, `status/GAP_ANALYSIS.md` แก้ได้ แต่ช่อง SA ห้ามติ๊กแทน
## 2. Pipeline (รันจาก root ของโปรเจกต์)

| Phase | คำสั่ง | ผล |
|---|---|---|
| 0 Pre-flight | `/preflight` → `python scripts/runpack/gen_preflight_pack.py` (P1–P5: env, สิทธิ์, ชนิดคอลัมน์ landing, work repo, Spark config) | `run_packs/rp00_preflight_*/` |
| 1-3 Extract + Convert | `python scripts/pipeline/extract_workflow.py` → `python scripts/pipeline/convert_sql.py` | `output/sql/raw/`, `output/sql/converted/`, `status/REVIEW_FLAGS.md` |
| 4 Review | `/review-sql` (subagent `sql-reviewer`) แล้วแก้ใน `output/sql/converted/` | บันทึกใน `status/PHASE4_REVIEW_LOG.md` |
| 5a DML | `python scripts/pipeline/gen_dml.py` | `output/dml/` |
| 5b ODI export | `python scripts/pipeline/build_odi_export.py` → `python scripts/pipeline/validate_odi_xml.py` | `output/odi_export/<package>.zip` (+ `PROJ_EXPORT.xml`, `build-spec.json`) |
| 6 DDL / DBA | `/gen-ddl` → `python scripts/pipeline/gen_ddl.py && python scripts/pipeline/gen_dba_prereq.py` + `ddl-dba-reviewer` | `output/ddl/`, `output/dba/` |
| 7 Validation | `/validation` → `python scripts/runpack/gen_validation.py` · `/compare-d2` (G5.M2) | `output/validation/`, `D2_REPORT.md` |
| 8 Backfill / Cutover | `/cutover` → `python scripts/pipeline/gen_backfill.py` + `cutover-planner` | `output/backfill/`, `status/CUTOVER_RUNBOOK.md` |
| Design docs | `python scripts/pipeline/gen_design_docs.py` แล้ว `/design` เติม spec | `.design/` |
| รอบให้คนรัน | `python scripts/runpack/gen_run_pack.py --pack rpNN` → `python scripts/runpack/read_run_results.py --pack run_packs/<pack>` | `run_packs/<pack>/results/REPORT.md` |

แก้ SQL หรือ config แล้ว ต้อง regenerate ต่อเนื่องจนถึง `validate_odi_xml.py` ผ่าน 0 error เสมอ

## 3. Courier loop — agent เข้า Oracle / ODI / Blendata ตรงไม่ได้

agent สร้าง Run Pack (`/run-pack`) → คนรันใน DBeaver แล้ววางผลใน `input/run_results/<pack>/` → agent `/read-results` สรุปและบอก step ถัดไป
- ORA error ที่ไม่อยู่ใน `KNOWN_ERRORS` ของ reader = **ห้ามเดาแก้** → `/diagnose` ขอ log เพิ่ม
- กฎของสคริปต์ใน pack (ห้าม `SET`/`SPOOL`, Alt+X, NULL จาก DBeaver ฯลฯ): `.claude/rules/run-pack.md`
- **ทุกครั้งที่ขอไฟล์/ข้อมูลจากผู้ใช้** AI ต้องสร้างโฟลเดอร์ปลายทางไว้ให้ก่อน (mkdir -p) และตรวจว่ามีจริง แล้วบอก 5 อย่าง: ไฟล์นี้คืออะไร · เอามาจากไหน/ทำอย่างไร (ถ้าต้องรัน SQL → เขียนไฟล์ `.sql` ไว้ใน `run_packs/<pack>/` แล้วบอก path + วิธี export ผล) · วางที่ path เต็ม · ชื่อไฟล์ · ถ้าไม่มีทำอย่างไร (กฎข้อ 19 ใน `knowledge/reference/intake-questions.md`)

## 4. กฎ ODI ที่ต้องทำตามเสมอ (สรุป — ต้นฉบับอยู่ใน rule / skill)

1. SQL ใน step: ห้าม `;` ท้าย SQL ธรรมดา, PL/SQL จบ `END;`, ห้ามบรรทัด `/`, ห้ามอักขระนอก latin-1 → `.claude/rules/odi-step-sql.md`
2. GlobalId: reuse จาก `_guid_keys.json` เมื่อชื่อ project/folder/package ตรงกับ build ก่อน (import ทับแบบ Overwrite ได้) · ชื่อไม่ตรง = project ใหม่ · ห้าม `--new-guid` เว้นแต่ SA สั่ง · import เข้า Studio = **Smart Import ครั้งเดียวตอนจบ** (ไฟล์ `<package>.zip`, procedure/package ที่ชื่อตรงของเดิมใช้ **Overwrite**) → skill `odi-smart-export`
2a. **ของครบก่อน build:** ก่อนสร้าง package ต้องรัน `/inputs` (`scripts/checks/check_inputs.py`) ให้ขึ้น `[พร้อม]` — ของที่ AI ต้องใช้: ไฟล์ export Blendata (JSON) · DDL ของ *ทุก* ตารางที่อ่าน/เขียน รวม view (CSV จาก `ALL_TAB_COLUMNS`) · Smart Export อ้างอิงจาก repository ปลายทางจริง (มี Procedure ที่ครบชนิดคำสั่ง TRUNCATE/DELETE/INSERT/MERGE, Package พร้อม step, Topology ที่มี logical schema/context ตาม config) · ผล `/preflight` P1–P5 · ค่า config (`schema_mode`, `convert_rules`, `concat_policy`) · `DECISION` ของ I14 · คำตอบ Spark config (Q3) · REVIEW_FLAGS ไม่มี PENDING · ห้ามบอกให้ผู้ใช้ import จนกว่า `check_inputs` PASS และห้ามชวน "import ลองก่อนแล้วเอาผลกลับมา"
3. ก่อนแปลง SQL ที่อ่าน landing ต้องรู้ชนิดคอลัมน์จริง (`all_tab_columns`, `/preflight` P3)
4. ผลของ Spark SQL ขึ้นกับ config ของ Blendata (`spark.sql.ansi.enabled`, `spark.sql.legacy.timeParserPolicy`, `spark.sql.parser.escapedStringLiterals`) — **ต้องยืนยันก่อนปิด Phase 4** → skill `spark-oracle-dialect`, `knowledge/lessons-learned.md`
5. Dev DB อาจไม่ใช่ 19c — SQL ที่พึ่ง feature ใหม่ต้องยืนยันบน 19c ก่อน cutover

## 5. ขอบเขตการแก้ไฟล์

- **ห้ามแก้:** `input/**/export_workflow.json` (ของจริงจาก Blendata), `input/odi_reference/*.xml`, `knowledge/reference/**` (อ้างอิงกลาง), `input/blendata/**` (ไฟล์เก่าจาก Blendata ทั้งโฟลเดอร์ อ่านอย่างเดียว), `output/odi_export/_guid_map.json` (ให้ script จัดการ)
- **แก้ได้:** `output/sql/converted/*.sql` (Phase 4), `config/config.json` (ต้องบอก SA ว่าแก้ field ไหน), เอกสาร `.md`, `.design/**` (นอก block AUTO)
- ไฟล์ใน `output/` อื่น ๆ เป็นของที่ generate — แก้ที่ต้นทาง (converted SQL / config / script) แล้ว regenerate
- **ห้ามลบไฟล์** — ถ้าต้องแทนให้เขียนทับหรือเก็บ backup `*.bak-YYYYMMDD`
- แก้ script ใน `scripts/` ได้เมื่อเป็นบั๊กของ kit — บันทึกในหัวข้อ "Kit — สิ่งที่แก้" ของ `status/MIGRATION_STATUS.md`

## 6. การตัดสินใจ — Human-decide vs Agent-decide

| ต้องให้คนตัดสินใจ (บันทึกใน `status/OPEN_DECISIONS.md`) | agent ทำเองได้ |
|---|---|
| scope ของ task (excluded), load strategy, error handling | regenerate / validate / สร้าง Run Pack |
| logical schema, context, ชื่อ project ODI | แก้ dialect Spark → Oracle ที่ไม่เปลี่ยน semantics |
| retention, cutover, rollback, go-live | อ่านผล Run Pack และสรุป |
| การเปลี่ยน business logic ใด ๆ | อัปเดตเอกสารสถานะ |

### 6.1 วิธีถามคำถามผู้ใช้ (ทุกคำสั่ง ทุก phase — ไม่ใช่เฉพาะ /intake)

คำถามที่ต้องการคำตอบมากกว่า ใช่/ไม่ใช่ (เลือกทางแก้, ระบุค่า, ตัดสินใจ, ยืนยันหลายส่วน):

1. **ถามทีละข้อ** — หนึ่งคำถามต่อหนึ่งข้อความ หนึ่งคำถามต่อหนึ่งการตัดสินใจ ติดเลขความคืบหน้า `[n/N]` ห้ามยิงหลายข้อรวดเดียว
2. **อธิบายคำถามให้ชัดทุกข้อ** ในข้อความเดียวกัน: (ก) ต้องการรู้อะไร (ข) เอาไปใช้ทำอะไร / ถ้าไม่รู้จะเกิดอะไร (ค) ตอบแต่ละทางแล้วผลต่างกันอย่างไร (ง) ศัพท์เฉพาะ (ODI / Spark / Oracle) อธิบายเป็นภาษาปกติกำกับไว้ในคำถามเอง
3. **คำถามแบบเลือกต้องบอกด้วยเสมอว่า "แนะนำข้อไหน เพราะอะไร"** — ใส่ **[แนะนำ]** ที่ตัวเลือกเดียว พร้อมเหตุผลสั้น ๆ จากข้อเท็จจริงของงานนี้ (ไม่ใช่ความชอบ) และบอกเงื่อนไขที่ควรเลือกข้ออื่นแทน · ถ้าข้อมูลไม่พอจะแนะนำ ให้บอกว่าขาดอะไร อย่าเดา
4. **บอกให้ชัดว่าเป็นคำถามแบบไหน และตอบอย่างไร** — แบบใช่/ไม่ใช่ ("ตอบ ใช่ หรือ ไม่") · แบบเลือก (`1)` `2)` `3)` + บอกว่าพิมพ์เลขเดียว) · แบบพิมพ์ค่า (มีตัวอย่างกำกับ)
5. ต้องตัดสินใจหลายเรื่อง/หลายทาสก์ → แตกเป็นคำถามย่อยแล้วถามทีละอัน ห้ามสมมติว่าคำตอบเดียวใช้กับทุกแถว
6. ค้นหาคำตอบเองจากไฟล์ที่มีก่อนถาม — ถ้าเจอ ให้เสนอคำตอบแล้วขอแค่ยืนยัน
7. คำถามใช่/ไม่ใช่ล้วนที่ชัดอยู่แล้ว ถามสั้นได้ แต่ต้องบอกว่า "ใช่" หมายถึงอะไร ถ้าไม่ชัด
8a. **ค่าที่ผู้ใช้เลือกเองได้ใน `config/config.json`:** `schema_mode` (literal | odiref, ไม่ตั้ง = literal) และ `convert_rules` รายข้อ (auto | flag, ไม่ใส่ = auto) — ถ้าผู้ใช้ต้องการเปลี่ยนจากค่าตั้งต้น ให้ถามในแชตทีละข้อ ติดเลขความคืบหน้า พร้อม **[แนะนำ]** และตัวอย่างคำตอบ แล้วบันทึกลง config ให้เอง · ห้ามเปลี่ยนค่าเองโดยผู้ใช้ไม่ได้เลือก
8b. **`concat_policy` ไม่มีค่าตั้งต้น ผู้ใช้ต้องเป็นคนตอบ:** ถ้า SQL มี `concat(` หลาย argument ให้ถามในแชตหนึ่งคำถามต่อโปรเจกต์ พร้อมติดเลขความคืบหน้า ตัวเลือก **spark_null** [แนะนำ: คงพฤติกรรม NULL เดิมของ Spark ไม่เปลี่ยนความหมายของ key/เงื่อนไข] กับ **plain_concat** (NULL เป็นค่าว่าง) และตัวอย่างคำตอบ แล้วบันทึก `concat_policy` ลง `config/config.json` ให้เอง ก่อนรัน `convert_sql.py` · ถ้ายังไม่ตอบ `concat` จะติด PENDING
8. **ถาม-ตอบในแชต แล้ว agent บันทึกลงไฟล์เอง** — คำถามที่ต้องให้ SA ตัดสินใจ (Q ใน `status/OPEN_DECISIONS.md`, ค่าใน `config/config.json`, ผล intake) ให้ **ยกคำถาม + ตัวเลือก + [แนะนำ] มาแสดงในแชตเลย** ห้ามบอกให้ผู้ใช้ไปเปิดไฟล์อ่านก่อนตอบ · เมื่อ SA ตอบ agent บันทึกเองทั้งหมด (ติ๊กตัวเลือกพร้อม `✅ SA <วันที่>`, แก้ `config/config.json`, อัปเดต `status/`) แล้วสรุปสั้น ๆ ว่าแก้อะไรที่ไหน — ผู้ใช้เปิดไฟล์เองเฉพาะเมื่อ agent แก้ให้ไม่ได้ (เช่น งานใน ODI Studio / รัน SQL) และต้องบอกชื่อไฟล์หรือขั้นตอนเต็มทุกครั้ง

- **ทุกคำถามที่มีตัวเลือก ต้องบอกในข้อความเดียวกันว่า "แนะนำข้อไหน" (setup_migrate 2.6.7)** — ใส่ **[แนะนำ]** ข้อเดียว + เหตุผลจากข้อเท็จจริงของงาน (อ้างไฟล์/ค่า) + บอกว่าเมื่อไหร่ควรเลือกข้ออื่น · ถ้าข้อมูลไม่พอ ห้ามเดาและห้ามปล่อยว่าง ให้บอกว่า "ยังไม่แนะนำ เพราะขาด ... " · ใช้กับทุก command ทุก phase และกับ Q ที่ยกมาจาก `status/OPEN_DECISIONS.md` (เติม [แนะนำ] ก่อนถามถ้าในไฟล์ยังไม่มี) · I12: แนะนำได้เฉพาะวิธี ห้ามแนะนำให้ตัดทาสก์ → รายละเอียด `.claude/rules/ask-with-recommendation.md`
- **ขอข้อมูล/ขอผลรัน/ให้ผู้ใช้ลงมือทำ ต้องให้ทีละ 1 ข้อ แล้วรอผลก่อนข้อถัดไป (setup_migrate 2.6.8)** — ใช้กับทุกอย่างที่ agent ต้องการจากผู้ใช้ ไม่ใช่แค่คำถามมีตัวเลือก · ห้ามไล่รายการหลายขั้นหรือหลายคำถามในข้อความเดียว · ห้ามบอกว่าสคริปต์ "พร้อมรัน" ถ้ายังไม่เคยทดสอบกับเครื่องมือของผู้ใช้ · **ทุกคำถาม/ทุกข้อที่ให้ทำ ต้องอธิบายเป็นภาษาธรรมดาที่เข้าใจง่าย** (บอกว่าเรื่องคืออะไร ทำไมต้องตัดสินใจ ศัพท์เทคนิคมีคำอธิบาย แต่ละตัวเลือกบอกผลที่จะเกิดจริง ห้ามใช้รหัสภายใน Q#/GAP/BR โดยไม่อธิบาย) → รายละเอียด `.claude/rules/one-at-a-time.md`
- **ก่อนบอกว่า SQL/XML พร้อม import/รัน ต้องรัน `scripts/checks/pre_delivery_gate.py` ให้ FAIL = 0** · overwrite ห้ามเลือก DELETE/TRUNCATE เอง (อ่าน `config/partitions_check.csv`) · รอบแรกส่งโครงพื้นฐานเท่านั้น ของเสริมเติมทีหลัง (setup_migrate 2.6.9, `.claude/rules/pre-delivery-gate.md`)
- **import package ของ kit = Designer → Import → Smart Import ไฟล์ `output/odi_export/<package>.zip` (ไม่ใช่ Import Project)** — ชื่อ project/folder/package ตรงกับ build ก่อนหน้า = import ทับ (Overwrite) ได้ แต่ยังไม่ยืนยันใน Studio จึงต้องทดสอบใน Dev ก่อน · Topology/Scenario ต้องทำเองใน Studio · schema ของ SIT/Prod ต้องถาม DBA ก่อนตัดสิน Q Schema qualification (setup_migrate 2.8.0, `.claude/rules/odi-import.md`)
### 6.2 ก่อนถาม ต้องอ่านก่อน

ห้ามถามหรือให้ SA ไปเช็กสิ่งที่ `input/odi_reference/`, `config/config.json`, `status/OPEN_DECISIONS.md` ตอบได้อยู่แล้ว — ทำตาม `.claude/rules/read-before-ask.md` ทุกครั้งก่อนถาม

## 7. เอกสารออกแบบ `.design/`

- ADR: agent สร้างได้แค่ `Proposed` — `Accepted` เฉพาะ SA (`/adr`)
- block `<!-- AUTO -->` ห้ามแก้มือ (สร้างใหม่โดย `gen_design_docs.py`) · ตารางว่าไฟล์ไหนอัปเดตเมื่อไร: `knowledge/reference/claude-system.md` §4, `.design/README.md`

## 8. Slash commands / Subagents / Workflow

เริ่มงานด้วย **`/next-step`** เสมอ ถ้าไม่แน่ใจ · จบ session ด้วย `/update-status` หรือ `/handoff`
- ตาม phase: `/preflight` · `/convert` · `/review-sql` · `/gen-export` · `/design` · `/gen-ddl` · `/validation` · `/compare-d2` · `/cutover`
- Courier: `/run-pack` · `/read-results` · `/diagnose` · Governance: `/gate` · `/verify` · `/decide` · `/adr` · `/lesson` · Kit: `/inputs` · `/sync-guid` (ไม่บังคับ ใช้หลังทดสอบเมื่อมีการแก้ใน Studio) · `/kit-backport`
- Subagent 10 ตัว และ workflow `phase4-review` (ใช้เมื่อ SA สั่ง "run workflow phase4-review") — ตารางใช้เมื่อไร: `knowledge/reference/claude-system.md` §2–§3

## 9. Gates / Verify / Hooks

- Gate G0–G7 (`status/GATES.md`, `/gate`) — BLOCKED = ห้ามข้าม เว้นแต่มี waiver ที่ SA อนุมัติ
- Verify V1–V9 (`/verify`) → `output/verify/VERIFY_REPORT.md`
- Hooks บังคับ §5 และ `.claude/rules/state-files.md` (โดน block = แก้ตามข้อความ ห้ามหาทางเลี่ยง) — รายละเอียด: `knowledge/reference/claude-system.md` §5
- บันทึกคำตอบที่ SA ให้ในแชตได้ แต่ต้องใส่ `✅ SA <วันที่>` เสมอ — ห้ามติ๊กแทนโดยไม่มีคำยืนยัน

## 10. `knowledge/`

**ของโปรเจกต์นี้ (แก้ได้)** — `environment-facts.md` (ข้อเท็จจริง Dev/SIT/Prod + แหล่งที่มา) · `lessons-learned.md` (**อ่านก่อน Phase 1 และ Phase 4** · พบปัญหาใหม่ → `/lesson`) · `glossary.md` · `WORKFLOW.md` (ลำดับขั้นงาน + เลขอ้างอิง + ลำดับความสำคัญของกฎ — อ่านเมื่อไม่แน่ใจว่าอยู่ขั้นไหน)

**`knowledge/reference/` — อ้างอิงกลาง อ่านอย่างเดียว (hook กันแก้)** เปิดเฉพาะไฟล์/หัวข้อที่ต้องใช้ ไม่ต้องอ่านทั้งชุด:

| ต้องการ | เปิด |
|---|---|
| กฎหลัก, ข้อห้าม, ภาพรวม 7 ขั้น, Procedure vs Mapping | `reference/migration-rules.md` |
| ถาม intake ข้อ I<n> (**อย่าเปิดทั้งไฟล์** — `grep -n '^### \[I<n>/17\]'` แล้วอ่านเฉพาะส่วนนั้น) | `reference/intake-questions.md` |
| แปลง/รีวิว SQL (D-R1–D-R9) | `reference/spark-to-oracle-sql.md` (+ skill `spark-oracle-dialect`) |
| checklist ก่อนส่งมอบ | `reference/delivery-checklist.md` |
| ของส่งมอบ + กฎไฟล์สถานะ | `reference/deliverables.md` |
| ตรวจตัวเลข + cutover | `reference/validation-and-cutover.md` · วิธีเทสต์ด้วย mock: `reference/test-method.md` |
| query ตรวจ Oracle / Spark config | `reference/oracle-checks-and-spark-config.md` |
| โครง object ของ ODI / schema JSON ของ Blendata | `reference/odi-object-reference.md` · `reference/blendata-json-schema.md` |
| แผนที่ระบบ Claude (ชั้น, inventory, hook) | `reference/claude-system.md` |
| ประกอบ XML ด้วยมือ / เส้นทาง Mapping (**เฉพาะเมื่อ SA สั่ง**) | `reference/optional/manual-build-procedure.md` · `reference/optional/mapping-based-path.md` |

## 11. Rules / Skills (โหลดตาม path / description)

| ชนิด | ไฟล์ | ใช้เมื่อ |
|---|---|---|
| rule | `.claude/rules/read-before-ask.md` | **ทุกครั้งก่อนถามหรือให้ SA ไปเช็กค่าใน Studio** (โหลดเสมอ) — อ่านจาก `input/odi_reference/` / config / OPEN_DECISIONS ก่อน |
| rule | `.claude/rules/odi-step-sql.md` | แตะ `output/sql/converted/**`, `output/dml/**` |
| rule | `.claude/rules/run-pack.md` | แตะ `run_packs/**` หรือ generator/reader ของ Run Pack |
| rule | `.claude/rules/state-files.md` | แตะไฟล์สถานะ / runbook / ADR |
| skill | `spark-oracle-dialect` | แปลง / รีวิว SQL (Phase 4) |
| skill | `odi-smart-export` | `/gen-export`, `/sync-guid`, import เข้า Studio, query log ODI |

จะเพิ่ม/ย้ายกฎ: ดูหลัก "อะไรอยู่ที่ไหน" ใน `knowledge/reference/claude-system.md` §1 แล้วบันทึก K# ใน `status/MIGRATION_STATUS.md` §6
