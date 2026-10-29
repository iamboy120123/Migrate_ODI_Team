# แผนที่ระบบ Claude ของ SS_ESIM_L2D

> **อ่านเมื่อ** จะเพิ่ม/ย้ายกฎ, skill, agent, command, hook หรือ backport kit · อ้างจาก `CLAUDE.md`, `status/GATES.md`, `glossary.md`, `/kit-backport` · **ไม่ต้องเปิดทุก session** — เปิดเมื่อจะเพิ่ม/ย้ายกฎ, command, agent, skill หรือ backport kit

## 1. ชั้นของระบบ — อะไรอยู่ที่ไหน

| ชั้น | ตำแหน่ง | โหลดเมื่อ | ใส่อะไร | ห้ามใส่ |
|---|---|---|---|---|
| CLAUDE.md | root | ทุก session | บริบท, กฎเหล็ก, human vs agent, ขอบเขตแก้ไฟล์, pointer | รายละเอียดที่มีใน rule/skill แล้ว |
| rules | `.claude/rules/*.md` (`paths:`) | อัตโนมัติเมื่อแตะ path | กฎสั้นที่ต้องทำตามตอนแก้ไฟล์ชนิดนั้น | ตาราง reference ยาว |
| skills | `.claude/skills/<name>/SKILL.md` | ตาม `description` | ความรู้เฉพาะทาง / reference ที่ใช้เป็นครั้งคราว | สถานะโปรเจกต์ |
| knowledge | `knowledge/*.md` (ของโปรเจกต์) + `knowledge/reference/**` (อ้างอิงกลาง อ่านอย่างเดียว) | ถูกอ้างถึง | ข้อเท็จจริง env, บทเรียน, glossary (มีแหล่งที่มา) · กฎ/ขั้นตอนอ้างอิง | คำสั่งให้ agent ทำ |
| agents | `.claude/agents/*.md` | command / workflow เรียก | reviewer/auditor ใน context แยก, tools น้อยสุด | ขั้นตอนที่ SA สั่งเอง |
| commands | `.claude/commands/*.md` | SA พิมพ์ `/name` | entry point บาง: gate → script/agent → ขั้นถัดไป | ความรู้เชิงลึก (อ้าง skill/rule) |
| workflows | `.claude/workflows/*.js` | SA สั่ง "run workflow …" | orchestration หลาย agent แบบ deterministic | งานเดี่ยว |
| hooks | `.claude/settings.json` → `scripts/hooks/` | อัตโนมัติ | กฎที่ห้ามพลาดและตรวจด้วยโค้ดได้ (block / warn) | กฎที่ต้องใช้ดุลยพินิจ |
| state files | root (`status/MIGRATION_STATUS.md` ฯลฯ) | command อ่าน | สถานะ, คำถาม, gate, log — **ห้ามย้าย path** (script/hook อ้างตรง) | — |

**ตัดสินว่าของใหม่ไปไหน:** ห้ามละเมิด + ตรวจด้วยโค้ดได้ → hook · ไม่ได้ → rule · ความรู้ใช้บางครั้ง → skill · ข้อเท็จจริง/บทเรียน → knowledge (`/lesson`) · อยากได้ความเห็นที่สองแยก context → agent · SA สั่ง → command · หลาย agent → workflow
**หลักกันซ้ำ:** 1 กฎมีต้นฉบับที่เดียว ที่อื่นอ้างถึง — ถ้าต้องสรุปใน CLAUDE.md ให้สั้นและชี้ไปต้นฉบับ

## 2. Inventory ของ `.claude/`

| ชนิด | รายการ |
|---|---|
| rules | `odi-step-sql` (converted SQL, DML, procedure template) · `run-pack` (run_packs, generator/reader) · `state-files` (STATUS, OPEN_DECISIONS, PREFLIGHT, GATES, review log, REVIEW_FLAGS, runbook, ADR) |
| skills | `spark-oracle-dialect` (mapping Spark → Oracle + edge case) · `odi-smart-export` (GlobalId, import Overwrite/Merge, StepType, ตัวแปร, SNP_*) |
| workflows | `phase4-review.js` — sql-reviewer ∥ semantic-verifier → test-designer ต่อ task (อ่านอย่างเดียว คืนแถวให้ `status/PHASE4_REVIEW_LOG.md`) |
| settings | allow / ask / deny + hooks 4 ตัว (§5) · `settings.local.json` ไม่ commit |

## 3. Commands และ Subagents

| กลุ่ม | Commands |
|---|---|
| ประจำวัน | `/next-step` (ทางเข้าหลัก) · `/status` · `/update-status` · `/handoff` |
| ตาม phase | `/preflight` (0) · `/convert` (1–3) · `/review-sql` (4) · `/gen-export` (5) · `/design` · `/gen-ddl` (6) · `/validation` · `/compare-d2` (7) · `/cutover` (8) |
| Courier loop | `/run-pack` · `/read-results` · `/diagnose` |
| Governance | `/gate` · `/verify` · `/decide` · `/adr` · `/lesson` |
| Kit / ODI | `/sync-guid` · `/kit-backport` |

| Subagent | ใช้เมื่อ | เขียนได้ |
|---|---|---|
| `sql-reviewer` | Phase 4 หาปัญหา task ที่ถูก flag | — |
| `semantic-verifier` | Phase 4 หา counter-example ก่อนปิด G2 | — |
| `conversion-auditor` | หลัง `/convert` หา pattern ที่ converter พลาด → เสนอ K# | — |
| `xml-auditor` | หลัง `/gen-export`, `/sync-guid` | — |
| `test-designer` | seed / assertion ของ Run Pack | `run_packs/**` |
| `run-result-analyst` | `/read-results`, `/diagnose` | — |
| `state-auditor` | ก่อน `/update-status` | — |
| `spec-writer` | `/design` | `.design/specs/**` |
| `ddl-dba-reviewer` | `/gen-ddl`, G6 | — |
| `cutover-planner` | `/cutover`, G7 | `status/CUTOVER_RUNBOOK.md` |

## 4. เอกสารออกแบบ `.design/`

| ไฟล์ | อัปเดตเมื่อ |
|---|---|
| `01_methodology.md` | เปลี่ยนวิธีทำงาน (น้อยครั้ง) |
| `02_architecture.md` | รู้ข้อเท็จจริงใหม่ของระบบ as-is / to-be |
| `03_package_flow.md`, `04_task_mapping.md` | หลัง `/gen-export` ทุกครั้ง (block AUTO — ห้ามแก้มือใน block) |
| `specs/<task>.md` | หลัง Phase 4 ของ task นั้น (`/design <code>`) |
| `adr/ADR-NNN-*.md` | มีการตัดสินใจเชิงออกแบบ (`/adr`) — agent สร้างได้แค่ `Proposed` |

กฎละเอียด: `.design/README.md`

## 5. Gates / Verify / Hooks

- **Gate** (`status/GATES.md`, `python scripts/checks/check_gate.py G<n>`): G0 Environment → G1 Extraction → G2 Review → G3 Build → G4 Import → G5 Dev test → G6 Pre-Prod → G7 Go-live — BLOCKED = ห้ามข้าม เว้นแต่มี waiver ที่ SA อนุมัติใน Waiver log
- **Verify** (`python scripts/checks/verify_all.py` → `output/verify/VERIFY_REPORT.md`): V1 static · V2 build (XML ไม่ stale + SQL ใน XML = DML + Smart Export จาก Studio = DML / GlobalId) · V3 portability · V4 state (+ REVIEW_FLAGS / PHASE4_REVIEW_LOG) · V5 runtime · V6 schema / data contract · V7 Run Pack hygiene · V8 traceability (`output/verify/TRACEABILITY.md`) · V9 release readiness — รายละเอียดใน docstring ของ `scripts/checks/verify_all.py`
- **Hooks** (`scripts/hooks/`, ทดสอบด้วย `selftest.py`):

| Hook | Event | ผล | ตรวจ |
|---|---|---|---|
| `guard_owned_files` | PreToolUse Edit/Write | **block** | ไฟล์ของ generator/ต้นทาง · `[X]` ใน OPEN_DECISIONS/GATES ต้องมี `✅ SA YYYY-MM-DD` · ✅ ใน PREFLIGHT ต้องมี SA + วันที่ · ADR → Accepted ห้าม agent |
| `guard_bash` | PreToolUse Bash/PowerShell | **block** | คำสั่งอันตราย (ลบไฟล์, push, sqlplus ฯลฯ) |
| `post_edit` | PostToolUse Edit/Write | warn | แก้ converted SQL → V1 ทันที + เตือน XML stale · แก้ scripts → py_compile + เตือนบันทึก K# |
| `remind_status` | Stop | warn | มีไฟล์เปลี่ยนแต่ STATUS ไม่ขยับ → เตือน `/update-status` |

## 6. Kit — ต้นฉบับ ↔ ไฟล์ในโปรเจกต์

`.claude/` และไฟล์สถานะถูกสร้างจาก templates ที่ฝังอยู่ใน `setup_migrate.ps1` (ไม่มีโฟลเดอร์ `templates/` ในโปรเจกต์นี้) — **ต้นฉบับคือ templates ใน kit**; รัน `setup_migrate.ps1 -Mode InPlace -Force` จะเขียนทับ (backup ให้) ดังนั้นการแก้ในโปรเจกต์ต้องมี K# แล้ว backport

| ในโปรเจกต์ | ต้นฉบับใน kit | หมายเหตุ |
|---|---|---|
| `CLAUDE.md` | `templates/claude/CLAUDE.md.tpl` | placeholder ของ Setup.ps1 |
| `.claude/{agents,commands,rules,skills,workflows}/**` | `templates/claude/<เดียวกัน>/**` | rules มี placeholder (เช่น WORK_USER) — diff ที่ต่างแค่ค่าแทนที่ไม่ใช่ drift |
| `.claude/settings.json` | `templates/claude/settings.json` | |
| state files (`status/MIGRATION_STATUS.md` ฯลฯ) | `templates/claude/*.md.tpl` | |
| `.design/**` | `templates/design/**` | |
| `knowledge/*.md`, `knowledge/reference/**` | `templates/knowledge/**/*.md.tpl` | reference/ ถูกเขียนทับทุกครั้งที่ InPlace (อ่านอย่างเดียว) |
| `scripts/{pipeline,runpack,checks,testing,hooks}/*.py` | ฝังใน `setup_migrate.ps1` | |
