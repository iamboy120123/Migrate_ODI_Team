# 01 — Methodology: AI-Assisted Blendata → ODI Migration

Project: **SS_ESIM_L2D** · Workflow: `ss_esim_landing_to_discovery` · Updated: 2026-10-29 · SA: 41642975+iamboy120123@users.noreply.github.com

## 1. หลักการ

- **As-Is migration (ELT pushdown)** — แปลง Spark SQL เป็น Oracle SQL ทีละ task ให้ semantics เท่าเดิม ไม่ redesign business logic
- **Generator-first** — ของที่ส่งเข้า ODI (Smart Import XML) สร้างจาก script เสมอ ไม่แก้ XML ด้วยมือ; แก้ที่ converted SQL / config แล้ว regenerate
- **Offline gate ก่อนแตะระบบจริง** — `validate_odi_xml.py` ต้องผ่าน 0 error ก่อนสร้าง Run Pack
- **Human-decide สำหรับ scope / semantics / cutover** — agent ทำงานกลไก และเขียนคำถามให้ SA ตัดสินใจ

## 2. Phase

```mermaid
flowchart LR
  P0[Phase 0<br/>Setup / config] --> P13[Phase 1-3<br/>Extract + Convert]
  P13 --> P4[Phase 4<br/>SQL Review]
  P4 --> P5[Phase 5<br/>DML + Smart Import XML]
  P5 --> P6[Phase 6<br/>DDL / DBA prereq]
  P6 --> P7[Phase 7<br/>Dev run + L1/L2/L3]
  P7 --> P8[Phase 8<br/>Backfill / Cutover]
  P7 -. fail .-> P4
```

| Phase | Input | Output | Gate |
|---|---|---|---|
| 0 | ข้อมูล environment | `config/config.json`, `.claude/`, `.design/` | Pre-flight checklist |
| 1-3 | `export_workflow.json` | `output/sql/raw`, `output/sql/converted`, `status/REVIEW_FLAGS.md` | ทุก task มีไฟล์ |
| 4 | flag + SQL | converted SQL ที่แก้แล้ว, `status/PHASE4_REVIEW_LOG.md` | ไม่มี flag ค้าง |
| 5 | converted SQL | `output/dml`, `PROJ_EXPORT.xml` | validator 0 error |
| 6 | manifest | DDL, DBA prereq | DBA รันผ่าน |
| 7 | Run Pack | `run_packs/<pack>/REPORT.md` | S7 assertion ผ่านครบ, L1-L3 ตรง Blendata |
| 8 | backfill pack, runbook | ข้อมูลย้อนหลัง, go-live | sign-off |

## 3. Courier loop (agent เข้า Oracle / ODI / Blendata ตรงไม่ได้)

ดู `diagrams/courier_loop.mmd`

```mermaid
sequenceDiagram
  participant A as Claude Code
  participant K as Kit (scripts)
  participant H as SA / Dev
  participant S as Oracle / ODI / Blendata
  A->>K: gen_run_pack.py
  K-->>H: run_packs/<pack>/ (SQL + README)
  H->>S: รันตาม README (DBeaver / ODI Studio)
  S-->>H: ผลลัพธ์
  H->>K: export CSV / screenshot -> input/run_results/<pack>/
  A->>K: read_run_results.py
  K-->>A: REPORT.md
  A->>H: สรุป + step ถัดไป
```

## 4. Human-decide vs Agent-decide

| Human (SA) | Agent (Claude Code) |
|---|---|
| scope, load strategy, error handling | extract / convert / regenerate / validate |
| การเปลี่ยน semantics / business logic | แก้ dialect ที่ไม่เปลี่ยน semantics |
| logical schema / context / project ODI | สร้าง Run Pack และอ่านผล |
| retention, cutover, rollback, go-live | อัปเดตเอกสารสถานะ / design |
