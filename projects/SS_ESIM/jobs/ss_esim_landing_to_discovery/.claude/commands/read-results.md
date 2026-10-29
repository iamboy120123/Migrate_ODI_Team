---
description: อ่านผล Run Pack ใน input/run_results/<pack>/ แล้ววิเคราะห์ + บอก step ถัดไป
argument-hint: "[run_packs/<pack>]"
---
> **ใครรัน SQL — กฎทีม `kit/CLAUDE.kit.md` หัวข้อ "AI กับฐานข้อมูล" ชนะขั้นตอนด้านล่างเรื่องนี้** · ดูโหมด: `python scripts/ws/job_status.py --modes`
> - `db=ask` / `db=auto` → ใช้ `python scripts/runpack/run_sql.py <pack | ไฟล์> --plan` แล้ว **ถามคนในแชท: 1 = ให้ AI รัน / 2 = ฉันรันเอง** (ตอบเป็นเลข · ห้ามเลือกแทนคน)
>   ตอบ 1 → `run_sql.py --execute <แผน> --approved "<ชื่อคน> <วันที่>"` (คำสั่งที่ลบแล้วกู้คืนไม่ได้ ให้คนพิมพ์ชื่อตารางก่อน → `--confirm`) · ตอบ 2 → `run_sql.py --human <แผน>` บอกคนทีละไฟล์ แล้ว `--record-human`
>   `db=auto` + SELECT ล้วน → `run_sql.py <pack> --run-read` ได้เลยไม่ต้องถาม · pack หลายขั้นใช้ `--only` เฉพาะขั้นที่ถึงแล้ว
> - `db=human` → AI ไม่ต่อฐาน · บอกคนทีละไฟล์ตามขั้นตอนด้านล่าง (เปิดไฟล์ไหน · รันเพื่ออะไร · export แบบไหน · วางที่ไหน)
> - ไฟล์ Blendata (Spark SQL) · งานใน ODI Studio = คนทำเสมอ · ห้ามเรียก sqlplus / sqlcl เอง · ห้ามขอรหัสผ่านในแชท

1. pack = $ARGUMENTS (ถ้าว่าง = โฟลเดอร์ล่าสุดใน `run_packs/`)
2. `python scripts/runpack/read_run_results.py --pack <pack>` แล้วอ่าน `run_packs/<pack>/REPORT.md` และ CSV ที่เกี่ยวข้อง
3. screenshot (`*.png`) ให้เปิดดูด้วย Read
4. ใช้ subagent `run-result-analyst` วิเคราะห์สาเหตุ (ถ้า ❌) แยก "ข้อเท็จจริงจากผล" กับ "สมมติฐาน" — ถ้าแยกสมมติฐานไม่ได้ ให้เพิ่มสคริปต์ diagnose ใน pack
5. ORA error ที่ reader ไม่รู้จัก = ห้ามเดาแก้
6. สรุปผลเป็นตาราง step/ผล แล้ว `/update-status`
