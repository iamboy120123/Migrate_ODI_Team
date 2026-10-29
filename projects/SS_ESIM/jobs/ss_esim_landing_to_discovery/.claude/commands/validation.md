---
description: Phase 7 — generate query เทียบผล L1 / L2 / L3 (Spark vs Oracle) แล้วสร้างรอบให้คนรันทั้งสองฝั่ง
---
> **ใครรัน SQL — กฎทีม `kit/CLAUDE.kit.md` หัวข้อ "AI กับฐานข้อมูล" ชนะขั้นตอนด้านล่างเรื่องนี้** · ดูโหมด: `python scripts/ws/job_status.py --modes`
> - `db=ask` / `db=auto` → ใช้ `python scripts/runpack/run_sql.py <pack | ไฟล์> --plan` แล้ว **ถามคนในแชท: 1 = ให้ AI รัน / 2 = ฉันรันเอง** (ตอบเป็นเลข · ห้ามเลือกแทนคน)
>   ตอบ 1 → `run_sql.py --execute <แผน> --approved "<ชื่อคน> <วันที่>"` (คำสั่งที่ลบแล้วกู้คืนไม่ได้ ให้คนพิมพ์ชื่อตารางก่อน → `--confirm`) · ตอบ 2 → `run_sql.py --human <แผน>` บอกคนทีละไฟล์ แล้ว `--record-human`
>   `db=auto` + SELECT ล้วน → `run_sql.py <pack> --run-read` ได้เลยไม่ต้องถาม · pack หลายขั้นใช้ `--only` เฉพาะขั้นที่ถึงแล้ว
> - `db=human` → AI ไม่ต่อฐาน · บอกคนทีละไฟล์ตามขั้นตอนด้านล่าง (เปิดไฟล์ไหน · รันเพื่ออะไร · export แบบไหน · วางที่ไหน)
> - ไฟล์ Blendata (Spark SQL) · งานใน ODI Studio = คนทำเสมอ · ห้ามเรียก sqlplus / sqlcl เอง · ห้ามขอรหัสผ่านในแชท

1. ต้องผ่าน G5 auto ส่วน assertions (หรือ SA สั่งให้ทำคู่ขนาน) — `python scripts/checks/check_gate.py G5 --no-verify` แล้วบอกข้อที่ยังขาด
2. `python scripts/runpack/gen_validation.py` → `output/validation/` (L1 row count, L2 column profile / row hash, L3 business rules)
3. ตรวจ query คู่ก่อนส่ง: หน้าต่างข้อมูลเดียวกันทั้งสองฝั่ง (partition / process date), normalize NULL → `''`, format ของ DATE/TIMESTAMP/NUMBER ตรงกันทุกคอลัมน์ (อ่าน docstring ของ `gen_validation.py`)
4. สร้าง Run Pack (`/run-pack`) ที่มีไฟล์ `*_spark.sql` (Blendata) และ `*_oracle.sql` (Oracle Dev) — บอกคนรันเป็นขั้นตอนมีเลขกำกับ: ที่รัน, ไฟล์, ชื่อผลที่ export
5. หลังได้ผล: `/read-results` แล้วเทียบ L1 → L2 → L3 ตามลำดับ — **L1/L2 ไม่ตรง = หยุดหาสาเหตุ** (`/diagnose`) ห้ามปรับ threshold
6. ส่วนต่างที่อธิบายได้ต้องมี Q ที่ SA ปิดแล้ว · ผลตรงครบ → เสนอ SA ติ๊ก G5.M3
