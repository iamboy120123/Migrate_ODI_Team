---
description: สร้าง Run Pack ให้คนรันบน Oracle / ODI / Blendata (courier loop)
argument-hint: "[rpNN]"
---
> **ใครรัน SQL — กฎทีม `kit/CLAUDE.kit.md` หัวข้อ "AI กับฐานข้อมูล" ชนะขั้นตอนด้านล่างเรื่องนี้** · ดูโหมด: `python scripts/ws/job_status.py --modes`
> - `db=ask` / `db=auto` → ใช้ `python scripts/runpack/run_sql.py <pack | ไฟล์> --plan` แล้ว **ถามคนในแชท: 1 = ให้ AI รัน / 2 = ฉันรันเอง** (ตอบเป็นเลข · ห้ามเลือกแทนคน)
>   ตอบ 1 → `run_sql.py --execute <แผน> --approved "<ชื่อคน> <วันที่>"` (คำสั่งที่ลบแล้วกู้คืนไม่ได้ ให้คนพิมพ์ชื่อตารางก่อน → `--confirm`) · ตอบ 2 → `run_sql.py --human <แผน>` บอกคนทีละไฟล์ แล้ว `--record-human`
>   `db=auto` + SELECT ล้วน → `run_sql.py <pack> --run-read` ได้เลยไม่ต้องถาม · pack หลายขั้นใช้ `--only` เฉพาะขั้นที่ถึงแล้ว
> - `db=human` → AI ไม่ต่อฐาน · บอกคนทีละไฟล์ตามขั้นตอนด้านล่าง (เปิดไฟล์ไหน · รันเพื่ออะไร · export แบบไหน · วางที่ไหน)
> - ไฟล์ Blendata (Spark SQL) · งานใน ODI Studio = คนทำเสมอ · ห้ามเรียก sqlplus / sqlcl เอง · ห้ามขอรหัสผ่านในแชท

1. ถ้าไม่ระบุชื่อ → ใช้เลขถัดจาก pack ล่าสุดใน `run_packs/` (rp01, rp02, ...) — ถ้า pack เดิมยังรันไม่ครบให้ใช้ชื่อเดิม
2. `python scripts/checks/check_gate.py G3` ต้อง PASS ก่อน แล้ว `python scripts/runpack/gen_run_pack.py --pack $ARGUMENTS` (S0 gate = validator ต้องผ่าน)
3. ใครรัน: ตามกล่องด้านบน — db=ask / auto: `run_sql.py <pack> --plan` แล้วถามคน (1 ให้ AI รัน / 2 ฉันรันเอง) · db=human หรือคนเลือก 2: บอก SA ทีละไฟล์ (ไฟล์ไหน, รันด้วย user อะไร, Execute Script (Alt+X) ไหม, export ผลไปที่ `input/run_results/<pack>/`)
4. ย้ำ: สคริปต์ที่ insert/delete ข้อมูลทดสอบควรรันบน Dev · แผนของ run_sql.py บอกชื่อฐานทุกครั้ง — ถ้าไม่ใช่ DEV ต้องบอกคนให้ชัดก่อนถาม
5. `python scripts/checks/verify_all.py --level V7` ต้องไม่มี FAIL ก่อนส่ง pack ให้คน (SET/SPOOL/'/', หลาย statement ต้องบอก Alt+X)
6. pack ก่อน G0 (ตรวจ environment) ใช้ `/preflight` แทน — pack ชื่อ `rp00_preflight_*` ไม่นับในลำดับ rpNN
