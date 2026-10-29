# Migration Status — ss_esim_landing_to_discovery (Blendata → ODI)

Updated: 2026-10-29 (rev.1) | SA: 41642975+iamboy120123@users.noreply.github.com

> สร้างโดย `setup_migrate.ps1` — Claude Code อัปเดตไฟล์นี้ด้วย `/update-status` ทุกครั้งที่จบ step

## 1. Scope

| รายการ | ค่า |
|---|---|
| Workflow | `ss_esim_landing_to_discovery` |
| Blendata export | `input/blendata/export_workflow.json` |
| ODI project / package | `SS_ESIM_L2D` / `PKG_SS_ESIM_L2D` |
| Logical schema / context | `DSS_ODI_LOG` / `DEV` |
| Excluded tasks | - |

## 2. สถานะรายเฟส

| Phase | งาน | สถานะ |
|---|---|---|
| 0 | Setup / config (`setup_migrate.ps1`) + pre-flight | ✅ setup 2026-10-29 — pre-flight ดู `status/PREFLIGHT_CHECKLIST.md` |
| 1-3 | Extract + Convert | ⏳ |
| 4 | SQL Review | ⏳ |
| 5 | DML + ODI Smart Import XML | ⏳ |
| 6 | DDL / DBA prereq | ⏳ |
| 7 | Validation (Dev run + L1/L2/L3) | ⏳ |
| 8 | Backfill / Cutover | ⏳ |

## 3. Package (ลำดับรันใน ODI)

_(เติมหลัง Phase 5)_

## 4. การตัดสินใจที่ปิดแล้ว

_(ดู `status/OPEN_DECISIONS.md`)_

## 5. ยังค้าง

- [ ] `/inputs` ขึ้น `[พร้อม]` (ของครบ) → build → **Smart Import ครั้งเดียว** → ทดสอบ (`/run-pack`)
- [ ] ยืนยัน `odi.work_repo_schema` (user ที่ query ตาราง SNP_* ได้)

## 6. Kit — สิ่งที่แก้/เพิ่ม

| # | ไฟล์ | รายละเอียด |
|---|---|---|

## 7. ไฟล์อ้างอิง

- `CLAUDE.md` — กฎของโปรเจกต์สำหรับ Claude Code
- `config/config.json` — config pipeline
- `status/PREFLIGHT_CHECKLIST.md` — gate ก่อน Phase 1 (อัปเดตด้วย `setup_migrate.ps1 -Mode InPlace`)
