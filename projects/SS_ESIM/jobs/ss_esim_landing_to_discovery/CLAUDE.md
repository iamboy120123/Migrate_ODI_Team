# CLAUDE.md — SS_ESIM_L2D: Blendata → ODI Migration (ss_esim_landing_to_discovery)

> สร้างโดย `setup_migrate.ps1` เมื่อ 2026-10-29 (kit 2.8.1 (2026-10-14)) — แก้ได้ แต่ถ้ารัน `setup_migrate.ps1 -Mode InPlace -Force` ไฟล์นี้จะถูก backup แล้วเขียนใหม่

<!-- ws:slim -->
> กฎส่วนที่เหมือนกันทุกงานอยู่ใน kit กลาง (โหลดอัตโนมัติด้านล่าง) · ถ้า Claude Code ถามเรื่อง external import ให้อนุญาต

## 1. บริบทโปรเจกต์

| รายการ | ค่า |
|---|---|
| Workflow ต้นทาง (Blendata / Spark SQL) | `ss_esim_landing_to_discovery` |
| Target | Oracle 19c ผ่าน ODI 14.1.2 — As-Is Migration (ELT pushdown) |
| ODI project / package | `SS_ESIM_L2D` / `PKG_SS_ESIM_L2D` |
| Logical schema / context | `DSS_ODI_LOG` / `DEV` |
| Work user (schema ของตาราง) | `DSSDEV` |
| SA | 41642975+iamboy120123@users.noreply.github.com |

**Gate Phase 0:** ก่อนเริ่ม Phase 1 กับข้อมูลจริง `status/PREFLIGHT_CHECKLIST.md` ต้องผ่านครบ 5/5 — ถ้ายังไม่ครบให้แจ้ง SA ว่าข้อไหนค้าง (ทดสอบ pipeline ด้วย export ตัวอย่างได้)

ไฟล์สถานะหลักคือ `status/MIGRATION_STATUS.md` — **อ่านก่อนเริ่มงานทุกครั้ง** และอัปเดต (เพิ่ม rev) ทุกครั้งที่จบ step
คำถามที่ต้องให้คนตัดสินใจอยู่ใน `status/OPEN_DECISIONS.md` (ห้ามตอบแทน SA)

ตอบผู้ใช้เป็น **ภาษาไทย** ใช้ศัพท์เทคนิคเป็นภาษาอังกฤษ กระชับ บอกสิ่งที่ต้องให้คนทำเป็นขั้นตอนมีเลขกำกับ

## กฎส่วนกลางของ kit

@../../../../kit/CLAUDE.job.md

<!-- ws:imports -->
## กฎของทีม (workspace)

@../../../../kit/CLAUDE.kit.md
