> **อ่านตอนไหน** — ต้องขอผลตรวจฐานข้อมูล Oracle / ค่า Spark config จากผู้ใช้

# query ตรวจฐานข้อมูล Oracle (ใช้ใน I3/I4/I10/I17b) และคำถาม Spark config

> ไฟล์นี้เป็นคลัง SQL ที่ฝังอยู่ในคำถาม intake (I3/I4/I10/I17b) ไม่มีขั้นแยกให้ผู้ใช้รันอีกรอบ — "ขั้นเสริม S" (Spark config) อยู่ที่ I4
> **ที่มาของไอเดีย** — esim kit (คนละชุด) เคยเจอตารางชื่อเดียวกันซ้ำสอง schema ทำให้ job รันผ่านแต่ได้ 0 แถว
> **สถานะหลักฐาน** — กรณีนั้นยังไม่เคยเกิดกับ package ที่ชุดนี้สร้าง และการปรับนี้ **ยังไม่เคยรันกับงานจริง**

---

## I1. กติกา

1. **รันด้วย login เดียวกับที่ ODI ใช้ต่อ data server** (`SnpConnect.UserName` จาก reference) ไม่ใช่ login ที่สะดวกกว่า
2. ทุกคำสั่งเป็น `SELECT` อ่านอย่างเดียว (ข้อห้ามใน `migration-rules.md` หัวข้อ 7) คนเป็นคนรัน agent ไม่รัน
3. **แทนค่าให้ครบก่อนส่งให้ผู้ใช้** (กฎการถามข้อ 13) — ห้ามส่ง placeholder เปล่าให้เติมเอง
4. ผลให้ผู้ใช้วางกลับ แล้วบันทึกลง `status/MIGRATION_STATUS.md` (`knowledge/reference/deliverables.md` (หัวข้อ migration-state))
5. ถ้าได้ `ORA-00942` / `ORA-01031` ให้ข้ามคำสั่งนั้น บันทึกว่า "ตรวจไม่ได้เพราะสิทธิ์" ห้ามเดาค่า

## I2. SQL ที่ใช้ และอยู่ในคำถามไหน

| อยู่ที่ | SQL | เพื่อ |
|---|---|---|
| **I3** | `SELECT owner, table_name, column_id, column_name, data_type, data_length, data_precision, data_scale, nullable, data_default FROM all_tab_columns WHERE table_name IN (<ตารางที่ DAG แตะถึงทุกตัว>) ORDER BY table_name, owner, column_id` | ได้ DDL (column list, nullable, default) + ชนิดคอลัมน์สำหรับ D-R6/D-R8 + เห็นว่าตารางซ้ำข้าม owner ไหม ในคำสั่งเดียว |
| **I4** | ไม่มี SQL ใหม่ — อ่านคอลัมน์ `owner` จากผล I3 | ตรวจตารางชื่อเดียวกันหลาย owner เทียบกับ `SnpConnect.UserName` / `SnpPschema.SchemaName` |
| **I10 ข้อ 6** | `SELECT product, version_full FROM product_component_version` และ `SELECT DBTIMEZONE, SESSIONTIMEZONE, TO_CHAR(SYSDATE,...), TO_CHAR(SYSTIMESTAMP,...) FROM dual` | เวอร์ชัน (≥ 12.2 ไหม) และนาฬิกา DB — ถามเฉพาะเมื่อ SQL parse text เป็นวันที่ หรือใช้ `now()` |
| **I17b** | `SELECT privilege FROM session_privs WHERE privilege IN ('CREATE TABLE','CREATE ANY TABLE')` | ตรวจสิทธิ์สร้างตาราง `ERR_` — ถามเฉพาะเมื่อเลือกเปิด error log |

**ที่ตัดออกจากขั้น P เดิม** — P2 (ตัวตน session: ซ้ำกับที่ I4 อ่านจาก reference อยู่แล้ว), P4 (NLS: ยังเป็นคำถามตอน cutover ที่ `knowledge/reference/validation-and-cutover.md` ข้อ 11), P7 เต็มชุด (เหลือเฉพาะสิทธิ์สร้างตารางที่ I17b)

## I3. อ่านผลอย่างไร

| ผลจาก | ดูอะไร | ถ้าเจอแบบนี้ | ต้องทำอะไร |
|---|---|---|---|
| I3 | `owner` ของชื่อตารางเดียวกัน | มากกว่าหนึ่ง owner | **อันตราย** — ถ้า login คือ owner ที่ไม่ใช่ตัวจริง SQL ที่ไม่ qualify จะอ่านสำเนาแล้วได้ 0 แถวโดยไม่มี error บันทึกใน `status/MIGRATION_STATUS.md` แล้วย้ำที่ I4 |
| I3 | `data_type` ของคอลัมน์ที่ SQL เอาไป parse | `TIMESTAMP`/`DATE` อยู่แล้ว | ห้ามห่อ `TO_DATE`/`TO_TIMESTAMP` (D-R6) |
| I3 | `data_type` เป็น `VARCHAR2` แต่เก็บวันที่ | | ต้องมี shape guard (D-R8) |
| I3 | `data_length` ของ `VARCHAR2` (ถ้าเห็นว่าเป็น byte) | ข้อมูลภาษาไทยกว้างกว่าที่คิด | แจ้งผู้ใช้ — `NLS_LENGTH_SEMANTICS` ถ้าต้องรู้ให้ถามเพิ่ม |
| I3 | ตารางที่ DAG แตะแต่ไม่มีแถวในผล | ไม่มี object ชื่อนั้นใน `all_tab_columns` | อาจไม่มีใน Oracle (เช่น `ext_*` อาจเป็น view/synonym — ตรวจ `all_objects` ต่อ) หรือไม่มีสิทธิ์เห็น — **อย่าสรุปว่าไม่มี** ถามผู้ใช้ |
| I10 ข้อ 6 | เวอร์ชัน | ต่ำกว่า 12.2 | `DEFAULT NULL ON CONVERSION ERROR` ใช้ไม่ได้ — หยุด แจ้งผู้ใช้ก่อนแปลง |
| I10 ข้อ 6 | `sysdate_value` เทียบกับ `session.timeZone` ของ Spark | ไม่ตรง | `now()` ของ Spark ใช้ session timezone ส่วน `SYSDATE` ใช้นาฬิกาเครื่อง DB — ตัวเลข/partition ที่อิงเวลาจะเลื่อน ถามผู้ใช้ก่อนปิด I10 (D-R9) |
| I10 ข้อ 6 | `DBTIMEZONE` ≠ `sysdate_value` | เกิดได้ปกติ | `DBTIMEZONE` ไม่ได้กำหนด `SYSDATE` อย่าสรุปจาก `DBTIMEZONE` อย่างเดียว |
| I17b | ไม่มี `CREATE TABLE` | | ไม่ใช่เหตุยกเลิก package — ส่งสคริปต์สร้าง `ERR_` ให้ DBA |

---

## I4. คำถาม Spark config (ขั้นเสริม S)

**ทำไมต้องถาม** — config เหล่านี้เปลี่ยนผลของ SQL เดิมโดยไม่ต้องแก้โค้ด: ค่าเดียวกันอาจทำให้ Spark ล้มทั้งงาน
(ข้อมูลผิดรูป) หรือคืน NULL เงียบๆ การแปลงเป็น Oracle ต้องเลือกให้ตรงกับพฤติกรรมจริง ดูผลต่อการแปลงที่ `knowledge/reference/spark-to-oracle-sql.md` กฎ D-R9

**ขอให้ผู้ใช้รันบน Blendata/Spark (ถ้ารันได้) แล้ววางผลทั้งหมด**

```sql
SELECT version();
SET spark.sql.ansi.enabled;
SET spark.sql.legacy.timeParserPolicy;
SET spark.sql.parser.escapedStringLiterals;
SET spark.sql.session.timeZone;
SET spark.sql.storeAssignmentPolicy;
SET spark.sql.legacy.sizeOfNull;
```

**ตัวอย่างคำตอบ** (ค่าจริงของงาน esim ที่เคยทำ — ใช้เป็นรูปแบบเท่านั้น ห้ามใช้เป็นค่าเริ่มต้นของงานอื่น):
`ansi=false · timeParserPolicy=EXCEPTION · escapedStringLiterals=false · session.timeZone=Asia/Bangkok · storeAssignmentPolicy=LEGACY · sizeOfNull=true`

**ถ้าผู้ใช้ตอบว่ารันไม่ได้ / ไม่ทราบ**

1. ห้ามเดาค่า และห้ามใช้ค่า default ของ Spark เวอร์ชันใดเวอร์ชันหนึ่งแทน (default เปลี่ยนตามเวอร์ชัน)
2. ให้ผู้ใช้ถามผู้ดูแล Blendata/ทีม platform หรือดูจาก config ของ job/cluster
3. ถ้ายังไม่ได้ค่า: บันทึกเป็น **"ไม่ทราบ"** ใน `status/MIGRATION_STATUS.md` (ตารางสมมติฐานที่ยังไม่ยืนยัน) และใน
   `HANDOVER.md` — แล้วบังคับให้ชุดข้อมูลทดสอบใน `knowledge/reference/validation-and-cutover.md` E7 มีแถวขอบ (วันที่ผิดรูป, สตริงมี backslash) เพื่อเทียบกับ Blendata จริง
4. **ค่าที่ผิดสังเกต** (เช่นค่าที่ไม่ใช่ `true`/`false` ทั้งที่ config เป็น boolean) ให้ถามผู้ใช้กลับก่อนใช้ ไม่ตีความเอง

**ผลของคำตอบ** — ไปที่ `knowledge/reference/spark-to-oracle-sql.md` กฎ D-R9 (ตารางว่าแต่ละค่าบังคับให้แปลงอย่างไร) และบันทึกค่าลง `status/MIGRATION_STATUS.md` ทุกครั้ง
