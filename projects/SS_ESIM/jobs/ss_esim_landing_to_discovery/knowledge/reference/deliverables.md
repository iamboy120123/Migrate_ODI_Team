# สิ่งที่ส่งมอบ + กฎไฟล์สถานะ

> **อ่านเมื่อ** — ก่อนส่งมอบ/ปิดงาน และเมื่อต้องจดสถานะหรือบันทึกการตัดสินใจ
> **ไม่ต้องอ่านเมื่อ** — กำลังแปลง SQL หรือไล่ intake (ใช้ `spark-to-oracle-sql.md` / `intake-questions.md`)

## 1. สิ่งที่ส่งมอบ

ของส่งมอบอยู่ในโฟลเดอร์ของโปรเจกต์นี้เอง (ไม่มีโฟลเดอร์ `<PackageName>/` แยก) — ย้ายไปส่งต่อทั้งโฟลเดอร์ได้โดยไม่ต้องรวมไฟล์

| ของส่งมอบ | อยู่ที่ | สร้างด้วย | หมายเหตุ |
|---|---|---|---|
| **ODI Smart Export (ไฟล์ที่ Smart Import)** | `output/odi_export/<package>.zip` (XML กลาง = `PROJ_EXPORT.xml`) | `/inputs` แล้ว `/gen-export` | Project / Folder / Package / Procedure (1 ต่อทาสก์) / Variable / step chain / topology ที่ลอกจาก reference · import เข้า Studio ด้วย Smart Import ครั้งเดียวตอนจบ |
| **Oracle SQL ที่แปลงแล้ว** | `output/sql/converted/` (+ `output/dml/`) | `/convert`, `gen_dml.py` | 1 statement ต่อ 1 ไฟล์ |
| **Handover report** | `HANDOVER.md` | `/handoff` | ทาสก์ที่ implement ตรงๆ ไม่ได้ (placeholder) พร้อมเหตุผลและทางเลือกที่ตัดสินไว้ (I12) · step สถานะที่ยังเป็น placeholder · Topology ที่ต้องตั้งเอง · ย้ำว่ายังไม่มีการยืนยัน import/run |
| **DDL / DBA prerequisite** | `output/ddl/`, `output/dba/` | `/gen-ddl` | แยกจาก package — คนรันเอง |
| **ชุดตรวจผล** | `output/validation/` | `/validation` | SELECT จำนวนแถว/ผลรวม/hash รายแถว/การกระจายสถานะ — คนรันแล้ววางผลกลับ ไม่ใช่หลักฐานว่าถูกจนกว่าจะเทียบ (ดู `validation-and-cutover.md` E7) |
| **สถานะ + คำตอบ intake + การตัดสินใจ** | `status/MIGRATION_STATUS.md`, `status/INTAKE.md`, `status/OPEN_DECISIONS.md` | `/update-status`, `/intake`, `/decide` | ข้อค้างต้องตรงกับ `HANDOVER.md` |
| **Table inventory** (เมื่อผู้ใช้ขอ) | `output/table-inventory.md` | ยังไม่มีตัวสร้าง — เขียนตามรูปแบบด้านล่าง | |

**ไม่ส่งมอบ (โดยตั้งใจ)** — Scenario ที่ compile แล้ว (ไป generate ใน Studio) · password/credential · Mapping-based components (ต้องสั่งชัดเจน) · การรัน DDL/DML ให้ · **การสร้างตารางปลายทางที่ยังไม่มี**

### `table-inventory.md` — รูปแบบ

ไล่ทุกไฟล์ใน `output/sql/converted/` เก็บชื่อตารางทุกตัวที่ปรากฏ (`FROM` / `JOIN` = อ่าน, `INSERT INTO` / `MERGE INTO` = เขียน) ประกอบกับคำตอบ I3/I4/I14 แล้วแสดงเป็นตารางเดียว:

| ตาราง (schema-qualified) | บทบาท | สถานะ DDL | ใช้โดยทาสก์ | หมายเหตุ |
|---|---|---|---|---|
| `<schema>.<table>` | อ่าน / เขียน / ทั้งคู่ | DDL จริง (I3) / 🔶 เดา — ยังไม่ยืนยัน / ⛔ ยังไม่มีอยู่จริง | `<task1>, <task2>` | เช่น "ยืนยันแล้วที่ I3", "ต้องให้ DBA ยืนยัน column type" |

มีไว้ให้ DBA/reviewer ตอบว่า "ตารางนี้ถูกใครแตะบ้าง" โดยไม่ต้องไล่เปิด SQL — เป็นจุดที่ต้องเช็คก่อน DBA จะ grant สิทธิ์หรือเตรียม tablespace

**กฎ**

- ตารางสถานะ 🔶 หรือ ⛔ ต้องตรงกับรายการ "โหมดเดา" ใน `HANDOVER.md` เป๊ะ (ชื่อตารางเดียวกัน) — ไม่ตรง = มีตารางตกหล่น ต้องหาให้เจอก่อนส่งมอบ
- การยืนยัน column list (checklist ข้อ 32–34) ทำได้เฉพาะตารางที่ได้ DDL จาก I3 · ตารางที่เลือกโหมดเดาต้องรายงานว่า **"เดา — ยังไม่ยืนยัน (checklist ข้อ 35)"** ไม่ใช่ "ตรวจไม่ได้" และไม่ใช่ "ผ่าน" · แจงเป็นรายการแยกกันในรายงานปิดงาน
- ทุกรายการโหมดเดาต้องมี **next-step ที่ระบุตัวคน/ทีมที่ต้องยืนยันก่อน deploy** (เช่น "ต้องให้ DBA ยืนยัน column type จริง") — **ห้ามเสนอ "สร้างตารางนี้แล้วเดาต่อ"** เพราะเท่ากับสมมติว่าจะมีคนรัน DDL ให้ ซึ่งอยู่นอกขอบเขตเสมอ (ข้อห้ามใน `migration-rules.md` หัวข้อ 7) · เคยเกิดจริง: เสนอ "ให้ DBA สร้างตารางก่อนแล้วค่อยยืนยัน column" ต้องแก้กลับเป็น placeholder

### สิ่งที่คนต้องทำต่อหลังได้ของส่งมอบ

1. Import เข้า ODI Studio (Smart Import แบบ **Overwrite**)
2. Package → Generate Scenario
3. ตั้ง Topology ที่ยังขาด + ใส่ credential
   - **ถ้าเลือกข้อ 2 ที่ I4** ต้องตั้ง `ALTER SESSION SET CURRENT_SCHEMA=<schema>` ที่ Data Server ด้วย ไม่งั้น step แรกที่แตะตารางจะตายด้วย `ORA-00942`
4. รัน SQL บน Oracle dev แล้วเทียบกับผลที่คาดหวังด้วยชุดใน `output/validation/` — ไม่ใช่หยุดแค่ "รันได้ไม่ error"
5. **รายงานผลกลับ** — ทั้งผล import และ **ผลการรันจนจบ** เพื่อปิดข้อค้าง · ข้อค้างที่เหลือคือ "รันจบทั้ง package แล้วตัวเลขตรง" ไม่ใช่ "import ผ่าน"

## 2. กฎไฟล์สถานะและบันทึกการตัดสินใจ

1. **อัปเดตทุกครั้งที่** ผู้ใช้ตอบ I · ผู้ใช้ตัดสินใจเรื่องใหม่ · แผนเปลี่ยน · import แล้วเจอ error และแก้ · ผู้ใช้เปลี่ยนใจ — เขียนเป็นแถวใหม่ ไม่ลบแถวเก่า ให้เห็นประวัติ
2. **บันทึกเฉพาะสิ่งที่ผู้ใช้พูดหรือยืนยันเอง** — ข้อเสนอของ agent ลงเป็น "ข้อเสนอ รอ approve" เท่านั้น ห้ามเขียนคำตอบแทนผู้ใช้
3. **ห้ามใส่ credential / password / ค่าลับ** ในไฟล์ใดๆ
4. **ข้อค้างใน `status/MIGRATION_STATUS.md` ต้องตรงกับ `HANDOVER.md`** — ข้อไหนอยู่ไฟล์หนึ่งแต่หายจากอีกไฟล์ แปลว่าตกหล่น (checklist ข้อ 55)
5. **`/next-step` อ่านสถานะก่อนเสมอ** — ถามผู้ใช้เฉพาะกรณีไฟล์ไม่มี หรือสถานะขัดกับสิ่งที่ผู้ใช้บอก
6. สถานะ "ตรวจตัวเลขแล้ว" ต้องเป็นค่าที่ผู้ใช้ยืนยันหลังรันชุดตรวจผล ไม่ใช่ค่าที่ agent สรุปเอง — import ผ่านหรือรันไม่ error ไม่ใช่เหตุผลที่จะเปลี่ยนสถานะนี้ (`knowledge/lessons-learned.md` L34)
7. ถ้า `config/config.json` กับ `status/INTAKE.md` ขัดกัน **ให้ถามผู้ใช้** อย่าเลือกเอง
