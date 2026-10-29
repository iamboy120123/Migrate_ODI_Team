---
description: Phase 6 — generate DDL + DBA prerequisite แล้วให้ ddl-dba-reviewer ตรวจก่อนส่ง DBA
---
> **ใครรัน SQL — กฎทีม `kit/CLAUDE.kit.md` หัวข้อ "AI กับฐานข้อมูล" ชนะขั้นตอนด้านล่างเรื่องนี้** · ดูโหมด: `python scripts/ws/job_status.py --modes`
> - `db=ask` / `db=auto` → ใช้ `python scripts/runpack/run_sql.py <pack | ไฟล์> --plan` แล้ว **ถามคนในแชท: 1 = ให้ AI รัน / 2 = ฉันรันเอง** (ตอบเป็นเลข · ห้ามเลือกแทนคน)
>   ตอบ 1 → `run_sql.py --execute <แผน> --approved "<ชื่อคน> <วันที่>"` (คำสั่งที่ลบแล้วกู้คืนไม่ได้ ให้คนพิมพ์ชื่อตารางก่อน → `--confirm`) · ตอบ 2 → `run_sql.py --human <แผน>` บอกคนทีละไฟล์ แล้ว `--record-human`
>   `db=auto` + SELECT ล้วน → `run_sql.py <pack> --run-read` ได้เลยไม่ต้องถาม · pack หลายขั้นใช้ `--only` เฉพาะขั้นที่ถึงแล้ว
> - `db=human` → AI ไม่ต่อฐาน · บอกคนทีละไฟล์ตามขั้นตอนด้านล่าง (เปิดไฟล์ไหน · รันเพื่ออะไร · export แบบไหน · วางที่ไหน)
> - ไฟล์ Blendata (Spark SQL) · งานใน ODI Studio = คนทำเสมอ · ห้ามเรียก sqlplus / sqlcl เอง · ห้ามขอรหัสผ่านในแชท

1. ต้องมี `output/dml/_manifest.json` (ผ่าน `/gen-export` แล้ว) — ไม่มีให้หยุดและบอกขั้นตอน
2. ถ้ามี `input/run_results/profile_result.csv` (ผลรัน `output/ddl/03_profile_source_lengths.sql` ฝั่ง Blendata) จะใช้ความยาวจริง — ไม่มีให้บอก SA ว่าความยาวยังเป็น DRAFT
3. `python scripts/pipeline/gen_ddl.py && python scripts/pipeline/gen_dba_prereq.py`
4. `python scripts/checks/verify_all.py --level V3,V6` แล้วสรุป: fallback กี่คอลัมน์, target/คอลัมน์ที่ DDL ขาด, data contract
5. ใช้ subagent `ddl-dba-reviewer` — ข้อ FIX: แก้ที่ต้นทาง (`config/config.json` → `profile.*` ต้องบอก SA ว่าแก้ field ไหน / converted SQL) แล้ววนข้อ 3; ข้อ DECIDE → `/decide`
6. ถ้า DDL ยังไม่มีใน Dev: เสนอ Run Pack (`/run-pack`) ที่มี `S2a_create_tables_DRAFT.sql` (Execute Script Alt+X) + `output/dba/*.sql` ให้ DBA
7. บอก SA เป็นขั้นตอนมีเลขกำกับ: ไฟล์ที่ส่ง DBA, ลำดับรัน, สิ่งที่ต้องยืนยัน (G6.M2–M4) แล้ว `/update-status`
