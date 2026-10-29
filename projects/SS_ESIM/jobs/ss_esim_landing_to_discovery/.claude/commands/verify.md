---
description: ตรวจทุกชั้นแบบ offline (V1 static → V9 release readiness) แล้วสรุป FAIL/WARN
argument-hint: "[V1,V2,...]"
---
1. level = $ARGUMENTS (ว่าง = ทุกระดับ) → `python scripts/checks/verify_all.py` หรือ `python scripts/checks/verify_all.py --level <level>`
2. อ่าน `output/verify/VERIFY_REPORT.md` แล้วสรุปเป็นตาราง level / สถานะ / ข้อที่ FAIL-WARN
3. แต่ละ FAIL: บอกสาเหตุและวิธีแก้ที่ต้นทาง (converted SQL / config / script) — ห้ามแก้ `PROJ_EXPORT.xml` ตรง ๆ
   - V2 XML stale → เสนอ `/gen-export`
   - V4 state ขัดกัน → ใช้ subagent `state-auditor` แล้วเสนอข้อความที่ต้องแก้
   - V5 REPORT ค้าง → `python scripts/runpack/read_run_results.py --pack <pack>`
   - V2 Studio ≠ DML → (เฟสทดสอบ) แจ้ง SA ตรวจว่า import Overwrite ถูกต้อง / `/sync-guid` (G4) · ไม่ใช่เงื่อนไขก่อน build
   - V6 fallback / DML↔DDL / data contract → `/gen-ddl` + `ddl-dba-reviewer`; TO_TIMESTAMP บนคอลัมน์ TIMESTAMP → แก้ converted SQL (L1)
   - V7 Run Pack → แก้ generator (`gen_run_pack.py` / `gen_preflight_pack.py`) หรือ test-designer แล้วสร้าง pack ใหม่
   - V8 traceability → ดู `output/verify/TRACEABILITY.md` (spec ยังไม่เติม → `/design`)
   - V9 release → `/cutover`
4. ไม่แก้ไฟล์ใด ๆ ในคำสั่งนี้ นอกจาก output ของ verify เอง
