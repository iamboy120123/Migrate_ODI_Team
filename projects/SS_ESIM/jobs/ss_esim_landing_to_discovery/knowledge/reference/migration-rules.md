# กฎหลักและการตัดสินใจเชิงสถาปัตยกรรม

> **อ่านตอนไหน** — ก่อนเริ่มงาน และเมื่อต้องตัดสินใจ Procedure/Mapping หรือสงสัยว่าอะไรทำไม่ได้ (หัวข้อ 7 ข้อห้ามเด็ดขาด)

## 1. เอกสารนี้เชื่อได้แค่ไหน

ทุกข้อในเอกสารชุดนี้ติดป้ายระดับความเชื่อถือไว้ **อย่าเหมารวมว่าเท่ากันหมด**

| ป้าย | หมายถึง |
|---|---|
| **[พิสูจน์แล้ว]** | เคย import พังจริง แก้แล้วหายจริง |
| **[เห็นในไฟล์จริง]** | อ่านได้จากไฟล์ export จริง แต่ไม่เคยทดสอบว่าทำต่างไปจะพังไหม |
| **[อนุมาน]** | เหตุผลฟังขึ้น แต่ไม่มีหลักฐานตรง |

**สถานะการยืนยันปลายทาง** — แยกให้ชัดว่าหลักฐานมาจากไหน

| ด่าน | สถานะ |
|---|---|
| โครงสร้าง XML ตรงกับ export จริง | ตรวจเทียบ export จริงแล้วในชุดคู่มือเดิม · ของ repository ปลายทางของคุณ ตรวจด้วย `validate_odi_xml.py` กับ reference ที่คุณวางเอง |
| Smart Import เข้า ODI Studio | ชุดคู่มือเดิม (**generator คนละตัวกับของโปรเจกต์นี้**) เคย import ผ่านกับงานทดสอบ `TEST_AI_GEN_03` (ODI 14.1.2) — **XML ที่ generate จากโปรเจกต์นี้ ยังไม่มีบันทึกว่า import ผ่าน** |
| รัน Package ได้จริง | ชุดเดิมรันผ่าน step 1–4 ติดต่อกันแล้วหยุดที่ step 5 (`ORA-00947` ของ SQL ไม่ใช่โครงสร้าง XML) · ของโปรเจกต์นี้ยังไม่มีบันทึก |
| รันจบทั้ง package | ❌ ยังไม่เคย |
| ตัวเลขตรงกับงานเดิม | ❌ ยังไม่เคยเทียบเป็นลายลักษณ์อักษร |

**สิ่งที่ยังไม่มีใครยืนยัน (สำคัญที่สุด)** — ยังไม่มี package ที่รันจบทั้งเส้นแล้วได้ตัวเลขตรงกับงาน Blendata เดิม
ด่านที่เหลืออยู่ที่ **ความถูกต้องของ SQL ไม่ใช่โครงสร้างไฟล์** จึงมีการตรวจ SQL (`/sql-check`) เป็นด่านบังคับ
(ข้อ I3, I4, I10 ชุดที่ 2–4, I14 ข้อ 2 และ 7, `knowledge/lessons-learned.md` L24–L29 และ `delivery-checklist.md` ข้อ 29–43)
งานถัดไปควรจบด้วยการรันจบแล้วบันทึกผล — ผ่านหรือไม่ผ่านมีค่าเท่ากัน

ห้ามอ่านตารางนี้ว่า "ผ่านการทดสอบมาแล้ว" — ไม่มีรายงานเทียบตัวเลขเป็นลายลักษณ์อักษรในชุดนี้

---

## 2. กฎข้อเดียวที่ทุกอย่างเดินตาม

> **ไม่มีค่าที่เป็นของ repository ตัวไหนถูกสมมติขึ้น**

ทุกค่าที่ผูกกับ repository ปลายทาง — GlobalId ของ topology, เลข `SnpOrigTxt`,
ชุดชื่อและชนิดของ field, ค่า flag ตามธรรมเนียมของ repo นั้น, header `<Admin>` /
`<Encryption>` — **อ่านออกมาจากไฟล์ reference ที่ export จาก repository ปลายทาง**
มีแต่ object ที่สร้างใหม่จริงๆ (Project / Folder / Package / Procedure / Variable / Step)
ที่ได้ GlobalId ใหม่

ค่าที่อ่านจาก reference ไม่ได้ และผู้ใช้ก็ตอบไม่ได้ → **หยุดแล้วถาม** ห้ามเติมด้วยค่าที่ดูน่าเชื่อ

ความพังทั้งหมดใน `knowledge/lessons-learned.md` เริ่มจากการเดาที่ดูสมเหตุสมผลทั้งนั้น


---

## 3. ภาพรวม 7 ขั้น

| ขั้น | ทำอะไร | ใครทำ |
|---|---|---|
| 0 | **รับคำสั่ง** คำสั่งของ kit (`/intake`, `/next-step` — คำสั่ง `/start` ของ md ไม่ใช้แล้ว) | คนพิมพ์ |
| 1 | **ถามตอบ I1–I17 ทีละข้อ** (`intake-questions.md` · คำสั่ง `/intake`) รวมการเลือกสถาปัตยกรรมที่ I11 · มีขั้นเสริม **S** (หลัง I9: ค่า Spark config) · การตรวจสภาพฐานข้อมูล Oracle รวมอยู่ใน I3/I4/I10/I17b ไม่มีขั้นแยก · ปิดท้ายด้วย **I17b** (error log เลือกเปิด/ปิด) · บันทึกสถานะลง `status/MIGRATION_STATUS.md` (`knowledge/reference/deliverables.md` (หัวข้อ migration-state)) | AI ถาม / คนตอบ |
| 2 | **ตรวจความพร้อมของ SQL + แปลง** ยังเป็น Spark หรือเป็น Oracle แล้ว · เติม column list ทุก `INSERT` จาก DDL หรือจากการเดาที่ยืนยันไว้แล้ว (I3) · เติม schema ทุกชื่อตาราง (I4) → `knowledge/reference/spark-to-oracle-sql.md` (+ `scripts/checks/check_sql.py --ddl` ถ้ารัน python ได้ และมี DDL จริง) | AI แปลง / คนตรวจรายการที่ระบุ |
| 3 | **อ่านค่าจากไฟล์ reference** topology, `SnpOrigTxt`, ค่า default, กฎ `SqlIndGrp`, field layout — `scripts/odi_builder/build_from_spec.py` (เรียกผ่าน `build_odi_export.py`) อ่านจาก `input/odi_reference/` เอง (ประกอบด้วยมือ: `knowledge/reference/optional/manual-build-procedure.md` ขั้น 1–4) | AI (script) |
| 4 | **บันทึกคำตอบทั้งหมด** ลง `config/config.json` + `status/INTAKE.md` (ไม่มีไฟล์ build spec แยก) | AI |
| 5 | **ประกอบ XML + ตรวจ** — `/gen-export` → `validate_odi_xml.py` + `/sql-check dml` + `knowledge/reference/delivery-checklist.md` + `knowledge/lessons-learned.md` (zip ให้ export จาก Studio เอง) | AI (script) |
|  | *(ถ้า I11 ตอบว่า Mapping ขั้น 3–5 เปลี่ยนเป็น `knowledge/reference/optional/mapping-based-path.md` — ส่ง build spec ให้คนสร้างใน Studio แทน XML)* | |
| 6 | **ส่งมอบ + รายงาน** ทาสก์ที่เป็น placeholder พร้อมทางเลือกที่เลือกไว้ (I12), Topology ที่ต้องตั้งเอง, Scenario ที่ต้อง generate → `knowledge/reference/validation-and-cutover.md E6` | AI รายงาน / คน import |
| 7 | **ตรวจว่าตัวเลขตรงกับของเดิม แล้วค่อย cutover** → `knowledge/reference/validation-and-cutover.md` (ใช้ `output/validation/` จาก E7) | คนรัน / AI ช่วยเขียน query เทียบ |

ห้ามข้ามขั้น 1 แม้โจทย์จะดูชัดเจน — **สองในสามความพังที่เกิดจริงมาจากคำถามที่ไม่ได้ถาม
ไม่ใช่จากโค้ดผิด**


---

## 4. ตรวจไฟล์ reference ก่อนเริ่ม (ไม่ต้องถามผู้ใช้)

ใช้ก่อนเริ่มงานจริง เพื่อดูว่าไฟล์ที่มีอยู่ใช้ได้หรือต้อง export ใหม่ **ไม่ต้องถามคำถามใดๆ**

**เช็คแค่ว่าค่าที่ต้องใช้ครบไหม** แล้วรายงานสั้นๆ (ไม่เกิน 3–4 บรรทัด) แล้วจบ

ต้องครบ 5 อย่าง:

1. เลข `SnpOrigTxt` ครบ 3 slot
2. topology ครบ 7 object
3. step chain มีทั้ง `V` และ `T` และมี `OkExit=1` ตัวเดียวท้ายสุด
4. ไม่ถูกเข้ารหัส (`containsCipherText="false"`)
5. มี `SnpGrpState` / `SnpState2` (สัญญาณว่าเป็น export จาก Studio จริง)

- **ครบทั้ง 5** → รายงานบรรทัดเดียวว่า "reference ครบ ใช้ได้" แล้วไปคำถามถัดไปทันที **ห้ามถามผู้ใช้ต่อ**
- **ขาดอย่างใดอย่างหนึ่ง** → บอกว่าขาดอะไร แล้วขอ export ใหม่ (ส่งสเปก 18 ข้อ ข้อ 3 ของไฟล์นี้)
- **ห้ามรายงาน/ถามเรื่อง `SqlIndGrp` ที่มาจากตัวอย่างเดียว (x1), ค่าธงที่อ่านไม่ได้ (`KoExit`, `VarDatatype`) หรือค่า schema ที่ I2** —
  ค่าเหล่านี้ไม่ทำให้ไฟล์ใช้ไม่ได้ ให้บันทึกไว้เงียบๆ แล้วใส่ในรายงานส่งมอบตอนท้าย (`knowledge/reference/validation-and-cutover.md E6`) ส่วนเรื่อง `UserName` ≠ `SchemaName` ให้ยกที่ I4

วิธีอ่านค่าอยู่ใน `knowledge/reference/optional/manual-build-procedure.md` ขั้น 1–3 (หรือรัน `inspect_reference.py (ไม่รวมในโปรเจกต์นี้)` ถ้ารัน
python ได้) ถ้าข้อ 1–3 ไม่ผ่าน ให้ส่งสเปก 18 ข้อ (ข้อ 3 ของไฟล์นี้) ให้ไปทำก่อน


---

## 5. เลือกสถาปัตยกรรม — Procedure, Mapping หรือ ผสม

**ข้อสรุป: ใช้ Procedure เป็นค่าตั้งต้น ต่อทาสก์** ย้ายไป Mapping ทีหลังได้ ย้ายกลับยากกว่า
**ในทางปฏิบัติ งานส่วนใหญ่ควรเป็น "ผสม"** — ไล่ตารางด้านล่างทีละทาสก์ ไม่ใช่ตัดสินทั้งงาน
เป็นก้อนเดียว ดูเกณฑ์ตัดสินรายทาสก์แบบละเอียดใน `knowledge/reference/optional/mapping-based-path.md F7`

### เหตุผล

| | **Procedure** (แนะนำ) | **Mapping** |
|---|---|---|
| สิ่งที่ส่งมอบได้ | **XML ที่ import แล้วรันได้** | build spec + SQL ให้คนไปสร้างใน Studio |
| เคยมีคน generate XML สำเร็จไหม | โครงสร้างตรวจครบทุกจุดกับ export จริง | **ไม่เคย** — ลองแล้วจบที่ NullPointerException ใน Studio |
| ต้องเตรียมอะไรก่อน | ไฟล์ reference หนึ่งไฟล์ | reverse-engineer Datastore ของทุกตารางก่อน |
| หลาย statement ต่อกัน (`TRUNCATE` แล้ว `INSERT`) | บรรทัดคำสั่งสองบรรทัดใน Procedure เดียว | ต้องแยกเป็นสอง object |
| correlated subquery / window function หนักๆ | วาง SQL ลงไปตรงๆ | ยัดลงช่อง Expression อยู่ดี ได้ Mapping ที่อ่านยากกว่า SQL |
| lineage / impact analysis ใน Studio | ไม่มี — ODI มองเห็นแค่ข้อความ SQL | **มี** นี่คือข้อได้เปรียบจริงข้อเดียว |
| ทีมมาแก้ logic ผ่านหน้าจอทีหลัง | ต้องแก้ SQL | แก้ใน GUI ได้ |

### เลือก Mapping เมื่อไร

เลือกเมื่อ **ข้อใดข้อหนึ่ง** เป็นจริง — ไม่ใช่เพราะ "Mapping ดูเป็นวิธีที่ถูกต้องกว่า"

- **package ที่ทีมใช้อยู่จริงเป็น Mapping** ← น้ำหนักมากที่สุด
- องค์กรบังคับให้ทุก transformation ต้อง trace ได้ผ่าน lineage ของ ODI
- logic ส่วนใหญ่เป็น source → transform → target ตรงๆ ไม่มี multi-statement
- มี Datastore Model ครบอยู่แล้ว และมีคนพร้อมนั่งสร้าง Mapping

### ข้อเท็จจริงที่ต้องบอกผู้ใช้ให้ตรง

คู่มือของ Oracle แนะนำ Mapping สำหรับงาน transformation โดยทั่วไป — **แต่ Oracle เอง
ระบุข้อยกเว้นไว้ด้วย** สำหรับ logic ที่เป็น SQL หนักๆ ซึ่งงาน ETL แบบ Blendata ที่เต็มไป
ด้วย correlated subquery และ window function อยู่ในข้อยกเว้นนั้นพอดี **และการทำตามแบบ
ที่ทีมใช้อยู่จริงสำคัญกว่ากฎทั่วไป** เพราะคนที่ต้องรีวิวและดูแลต่อคือทีมนั้น

ไม่ว่าเลือกทางไหน **ต้องบันทึกเป็นเอกสารการตัดสินใจ** ตามแบบใน `knowledge/reference/validation-and-cutover.md E5`


---

## 6. สองเส้นทางตอนสร้างไฟล์

**เส้นทาง A — ทำมือ (ใช้ได้ทุกแอป)**
ทำตาม `knowledge/reference/optional/manual-build-procedure.md` ทีละขั้น แล้วตรวจตาม checklist ใน `knowledge/lessons-learned.md` ให้ครบทุกข้อ
⚠️ การเขียน XML นี้ด้วยมือ **เคยพังมาแล้ว 3 ครั้งในการ import จริง** สาเหตุทั้งสามอยู่ใน
`knowledge/reference/delivery-checklist.md` ข้อ 1–3 ฉะนั้น **ห้ามข้าม checklist แม้ข้อเดียว** มันไม่ใช่พิธีกรรม

**เส้นทาง B — ใช้สคริปต์ (เร็วกว่าและปลอดภัยกว่า ถ้าแอปรัน python ได้)**
`scripts/` มี library ที่ทำขั้นตอนใน `knowledge/reference/optional/manual-build-procedure.md` ให้อัตโนมัติ พร้อมตัวตรวจ 17 ข้อและชุดเทส
ตัวเอง — ดู `README.md` ใช้เมื่อรัน python 3 ได้ ไม่ต้องติดตั้งอะไรเพิ่ม
(ใช้แค่ standard library)

**ไม่ว่าเลือกเส้นทางไหน ต้องผ่านการตรวจ SQL ก่อน**
`python scripts/checks/check_sql.py <โฟลเดอร์ sql> --schema <schema จาก I4> --ddl <ไฟล์ DDL จาก I3> --partitions <ไฟล์ partitions_check.csv จาก I14>`
ตรวจกฎ D-R1 (column list) และ D-R2 (schema prefix) โดยไม่ต้องต่อฐานข้อมูล และเมื่อใส่ `--ddl`
จะตรวจต่อได้อีกว่าชื่อในลิสต์มีอยู่จริงในตารางไหม มีคอลัมน์ `NOT NULL` ตัวไหนตกหล่นไหม และ D-R6
ชั้นที่ 2-3 (`TO_DATE`/`TO_TIMESTAMP`/การเทียบ literal ตรงๆ กับชนิดคอลัมน์จริง) เมื่อใส่ `--partitions`
จะตรวจ D-R7 ได้ว่า `TRUNCATE TABLE` ขัดกับ `sinkOption.partitions` ที่ไม่ว่างไหมเป็น `[ERROR]`/`[OK]`
จริง **ไม่ใส่จะได้แค่ `[WARN]` ทั่วไปสำหรับทุก `TRUNCATE` เสมอ**
ถ้าเลือกเส้นทาง B
`scripts/odi_builder/build_from_spec.py` (เรียกผ่าน `build_odi_export.py`) เรียกตัวตรวจนี้เองแล้ว (ผ่าน spec key `ddl_file` และ `partitions_file`)
**เจอ error จะไม่เขียนไฟล์ ไม่ว่าใส่ flag อะไร**
ถ้าเลือกเส้นทาง A ต้องไล่ checklist ข้อ 29–43 ด้วยตาแทน

ถ้าเลือกเส้นทาง B ก็ยังต้องถาม I1–I17 ให้ครบเหมือนกัน — สคริปต์สร้างไฟล์ ไม่ได้ตัดสินใจแทนคน


---

## 7. ข้อห้ามเด็ดขาด

- **ห้ามรัน DDL/DML กับฐานข้อมูลของงาน** ไม่ว่า environment ไหน ตรวจ syntax ได้ อธิบายได้ ส่งสคริปต์ให้ได้ แต่คนต้องรันเอง แล้วตรวจผลด้วย `SELECT`
- **ห้ามฝังทางแก้ที่พึ่งพาการสร้าง object ใหม่ในฐานข้อมูล (`CREATE TABLE` เป็นต้น) ลงในไฟล์ผลลัพธ์หรือแผนที่ถือว่าสรุปแล้ว โดยไม่ได้รับอนุมัติแยกต่างหากก่อน** — **เสนอไอเดียนี้ได้** ถ้า agent เห็นว่าจำเป็น (ดูกฎการถามข้อ 11) แต่ต้องระบุชัดว่าเป็นข้อเสนอรอ approve ไม่ใช่ข้อสรุป และห้ามเขียนลง SQL/build spec ราวกับว่ามี object นั้นอยู่แล้ว ไม่ว่าจะระบุว่าใครเป็นคนรันก็ตาม รวมถึงการเสนอว่า "DBA จะสร้างให้ทีหลัง" — ปลายทางทุกตัวที่ใช้ใน SQL **ในไฟล์ที่ส่งมอบจริง** ต้องมีอยู่แล้วจริงและยืนยันแล้วเท่านั้น (จาก DDL ที่ผู้ใช้ให้ที่ I3 หรือปลายทาง redirect ที่ผู้ใช้ยืนยันว่ามีอยู่จริงที่ I12) ถ้าไม่มี object จริงรองรับ ต้อง fallback เป็น placeholder เสมอ และบันทึกไอเดียที่เสนอไว้เป็น open item รอการอนุมัติ + รอยืนยันว่าสร้างจริงแล้วในรอบถัดไป **[เกิดขึ้นจริงมาแล้ว — ดู I12 และ `knowledge/reference/delivery-checklist.md` ข้อ 32]**
- **ตาราง error log (`ERR_<table>`) นับเป็น object ใหม่ในฐานข้อมูล** — ใส่ `LOG ERRORS` ลง SQL ได้ต่อเมื่อผู้ใช้เลือกเปิดที่ I17b **และยืนยันแล้วว่าตารางมีอยู่จริง** ห้ามใส่ล่วงหน้าโดยหวังว่าจะมีคนสร้างให้ภายหลัง (`knowledge/lessons-learned.md` L32)
- **ห้ามฝัง credential** export จริงเก็บ `Pass` เป็น null — ต้องเป็น null ต่อไป ทาสก์ที่ต้องต่อระบบนอกให้ตัดออกแล้วแจ้งให้ไปตั้ง Topology เอง แม้จะเห็นรหัส (หรือรหัสที่เข้ารหัสไว้) ใน source material ก็ห้ามนำมาใช้หรือถอดรหัส
- **ห้ามสร้าง Scenario** (`SnpScen` / `SnpScenStep` / `SnpScenTask` / `SnpVarScen` / `SnpExpTxtHeader`) — Studio generate ให้ในคลิกเดียว การปั้น scenario ที่ compile แล้วด้วยมือคือการเดาชนิดที่ทำให้ import พัง
- **ห้ามแต่ง project marker metadata** (`SnpGrpState` / `SnpState2`) — ต้องลอกจาก reference คอลัมน์เบื้องหลังเป็น NOT NULL และค่าเดาไม่ได้ **[พิสูจน์แล้ว — เคยมีคนเขียนจากความจำแล้วได้ ORA-01400]**
- **ห้ามใส่ `DwgExportSummary`** — เป็นของฟอร์แมต Export Project ไม่ใช่ Smart Export
- **ห้ามแก้ไฟล์ reference** ถือเป็นหลักฐานอ้างอิง เปิดอ่านอย่างเดียว
- **ห้ามใช้อักขระนอก ISO-8859-1** ในทุกค่าในไฟล์ รวมคอมเมนต์ใน SQL
- **default คือ Procedure-based** เปลี่ยนไปใช้ Mapping-based components เมื่อมีคนสั่งชัดเจนเท่านั้น — schema ใหญ่กว่ามาก ต้องมี Datastore Model ให้ผูก column และไม่ใช่สิ่งที่งานพวกนี้ใช้
- **ห้าม `--` ใน XML comment** XML ห้าม `--` ในคอมเมนต์ วิธีที่ปลอดภัยที่สุดคือไม่ใส่คอมเมนต์ XML เลย
