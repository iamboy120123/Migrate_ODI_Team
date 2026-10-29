---
description: Phase 8 — generate backfill pack แล้วให้ cutover-planner ร่าง/ตรวจ status/CUTOVER_RUNBOOK.md ก่อน G7
---
1. `python scripts/checks/check_gate.py G6` — ยัง BLOCKED ได้ แต่ต้องบอกว่าแผนเป็น DRAFT และข้อที่ขาด
2. `python scripts/pipeline/gen_backfill.py` (ต้องมี `output/ddl/01_create_tables.sql` — ไม่มีให้ `/gen-ddl` ก่อน) แล้วอ่าน `output/backfill/00_README.md`
3. ใช้ subagent `cutover-planner` — ถ้ายังไม่มี `status/CUTOVER_RUNBOOK.md` ให้ร่างจาก `templates/claude/CUTOVER_RUNBOOK.md.tpl` (แทน `{{...}}` ด้วยค่าจาก `config/config.json`)
4. `python scripts/checks/verify_all.py --level V9` — หัวข้อ Rollback / Go-No-go / Parallel run ต้องครบ, ช่อง TBD = รายการที่ต้องให้ SA/Business ตัดสิน → `/decide`
5. บอก SA เป็นขั้นตอนมีเลขกำกับ: ตัดสินใจที่ค้าง, Run Pack ที่ต้องรัน (baseline / export / load / reconcile), rehearsal rollback (G7.M3) แล้ว `/update-status`
