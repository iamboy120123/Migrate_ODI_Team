---
description: Phase 0 / G0 — ไล่ PREFLIGHT_CHECKLIST ทีละข้อ, สร้าง Run Pack rp00_preflight ให้คนรัน, อ่านผลแล้วบันทึก environment facts
---
> **ใครรัน SQL — กฎทีม `kit/CLAUDE.kit.md` หัวข้อ "AI กับฐานข้อมูล" ชนะขั้นตอนด้านล่างเรื่องนี้** · ดูโหมด: `python scripts/ws/job_status.py --modes`
> - `db=ask` / `db=auto` → ใช้ `python scripts/runpack/run_sql.py <pack | ไฟล์> --plan` แล้ว **ถามคนในแชท: 1 = ให้ AI รัน / 2 = ฉันรันเอง** (ตอบเป็นเลข · ห้ามเลือกแทนคน)
>   ตอบ 1 → `run_sql.py --execute <แผน> --approved "<ชื่อคน> <วันที่>"` (คำสั่งที่ลบแล้วกู้คืนไม่ได้ ให้คนพิมพ์ชื่อตารางก่อน → `--confirm`) · ตอบ 2 → `run_sql.py --human <แผน>` บอกคนทีละไฟล์ แล้ว `--record-human`
>   `db=auto` + SELECT ล้วน → `run_sql.py <pack> --run-read` ได้เลยไม่ต้องถาม · pack หลายขั้นใช้ `--only` เฉพาะขั้นที่ถึงแล้ว
> - `db=human` → AI ไม่ต่อฐาน · บอกคนทีละไฟล์ตามขั้นตอนด้านล่าง (เปิดไฟล์ไหน · รันเพื่ออะไร · export แบบไหน · วางที่ไหน)
> - ไฟล์ Blendata (Spark SQL) · งานใน ODI Studio = คนทำเสมอ · ห้ามเรียก sqlplus / sqlcl เอง · ห้ามขอรหัสผ่านในแชท

1. อ่าน `status/PREFLIGHT_CHECKLIST.md`, `status/OPEN_DECISIONS.md` (Q เรื่อง Spark config / data contract / work repository), `knowledge/environment-facts.md`, `knowledge/lessons-learned.md` (L1, L3, L7–L10)
2. ถ้ายังไม่มี `run_packs/rp00_preflight_*/` หรือ source object เปลี่ยน (เช่น เพิ่งมี raw/converted SQL) → `python scripts/runpack/gen_preflight_pack.py` แล้วรันตามกล่องด้านบน: P1–P4 (Oracle Dev) ใช้ run_sql.py ตามโหมด · P5 Blendata บอก SA (คนรันเสมอ) · db=human บอก SA เป็นขั้นตอนมีเลขกำกับตาม `README.md` ของ pack
3. ถ้ามีผลใน `input/run_results/<pack>/` แล้ว → อ่าน CSV / screenshot ทุกไฟล์ (NULL ของ DBeaver = `" "`) แล้วสรุปเป็นตาราง: PREFLIGHT ข้อ / หลักฐาน / ผ่าน? / สิ่งที่ SA ต้องทำ
   - P1: DB version (ไม่ใช่ 19c → เตือน G6.M1), USER = work user, NLS / timezone
   - P2: สิทธิ์ CREATE TABLE / PROCEDURE / quota (ขาด → แจ้ง DBA = PREFLIGHT 5)
   - P3: ชนิดคอลัมน์จริงของ landing/source → ข้อมูลตอบ Q data contract; คอลัมน์ TIMESTAMP/NUMBER ที่ SQL ปฏิบัติเหมือน string = **ต้องแจ้งก่อน Phase 4**
   - P4: owner ของ SNP_* → ข้อมูลตอบ Q work repository และ `config.odi.work_repo_schema` (แก้ config ต้องบอก SA ว่า field ไหน)
   - P5: ค่า Spark config → ข้อมูลตอบ Q Spark config + เติมหัวข้อ Spark config ใน `status/PHASE4_REVIEW_LOG.md`
4. บันทึกข้อเท็จจริงใน `knowledge/environment-facts.md` พร้อมแหล่งที่มา (`input/run_results/<pack>/<file>`)
5. **ห้ามติ๊ก ✅ ใน PREFLIGHT หรือ `[x]` ใน OPEN_DECISIONS แทน SA** — เสนอคำตอบ [แนะนำ] พร้อมหลักฐาน แล้วให้ SA ยืนยัน (ถ้า SA ยืนยันในแชต บันทึกได้พร้อม `✅ SA <วันที่>`)
6. จบด้วย `python scripts/checks/check_gate.py G0` และบอกข้อที่ยังค้าง
