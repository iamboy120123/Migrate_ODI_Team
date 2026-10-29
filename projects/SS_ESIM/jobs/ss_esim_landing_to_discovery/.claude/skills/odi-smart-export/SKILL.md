---
name: odi-smart-export
description: กฎและโครงสร้าง ODI 14c Smart Export / Smart Import XML ของ kit — GlobalId lifecycle, Overwrite vs Merge ตอน import, StepType ใน package, ตัวแปร ODI (Refresh Query), SNP_* ของ work repository — ใช้เมื่อ /gen-export, /sync-guid, ตรวจ XML (xml-auditor), วางแผน import เข้า Studio หรือ query log ของ ODI · ไม่ใช่ reference การแปลง SQL (ใช้ spark-oracle-dialect)
---
# ODI Smart Export / Import — reference ของ kit

ใช้คู่กับ `.claude/rules/odi-step-sql.md` (กฎ SQL ใน step) · โครงสร้าง XML เต็มอยู่ที่ `references/odi-smart-export-format.md` (layout ของ field อ่านจาก Smart Export ใน `input/odi_reference/` ไม่ใช่ template ตายตัว) (field order / Java type) — **อ่านก่อนแก้ generator**

## 1. GlobalId — สิ่งที่พลาดแล้วแพงที่สุด

- Smart Import จับคู่ object ด้วย `GlobalId` (UUID) ไม่ใช่ internal ID → GlobalId เปลี่ยน = ODI มองเป็น object ใหม่ (project ซ้ำ / procedure ซ้ำ)
- `build_odi_export.py` reuse GlobalId จาก `output/odi_export/_guid_keys.json` เมื่อ **ชื่อตรงกับ build ก่อนหน้า** (project code + project name + folder + package) → Smart Import แบบ Overwrite เป็นการ update · ชื่อไม่ตรง = GlobalId ใหม่ทั้งหมด = project ใหม่ · procedure/step ที่เพิ่มใหม่ได้ GlobalId ใหม่เฉพาะตัว · `--new-guid` บังคับสร้างใหม่ (settings = ask)
- procedure ที่หายไปจาก build ไม่ถูกลบใน repository — ลบเองใน Studio · `_guid_keys.json` / `_guid_map.json` แก้ด้วย script เท่านั้น (settings = deny)
- import เข้า Studio ทำ **ครั้งเดียวตอนจบ** — Smart Export จาก Studio ที่ต้องใช้ตอน build คือ reference ที่ SA เตรียมให้ *ก่อน* build เท่านั้น · ถ้าแก้ project ใน Studio ระหว่างทดสอบ ค่อย export มาเก็บ `input/odi_reference/smart_export_<desc>_<yyyyMMdd>.xml` แล้ว `/sync-guid <file>` (ไม่บังคับ · ไฟล์ใน `input/odi_reference/` ห้ามแก้)

## 2. ตอน import เข้า ODI Studio (บอก SA เป็นขั้นตอน)

| Object | ตัวเลือก | เหตุผล |
|---|---|---|
| Procedure / Package ที่ code เปลี่ยน | **Overwrite** | Merge ไม่อัปเดต SQL ของ step เดิม |
| Project / Folder | Merge | ไม่ต้องเขียนทับ |
| ทุก object | ห้าม *Create Copy* | จะได้ project ซ้ำ + GlobalId ใหม่ |

หลัง import (ครั้งเดียว): SA เปิด procedure ใน Studio ยืนยันว่า code เป็นเวอร์ชันใหม่ แล้วไปขั้นทดสอบ · Smart Export กลับ/`/sync-guid`/`xml-auditor` เป็นหลักฐานทดสอบ (G4) ไม่ใช่เงื่อนไขก่อนเทส

## 3. โครงสร้างที่ generator ต้องรักษา

- **1 step = 1 statement** — `TRUNCATE` กับ `INSERT` แยก `SnpLineTrt` (`OrdTrt` 10 / 20)
- `TRUNCATE`: default = `TRUNCATE TABLE schema.x` ตรง ๆ (reference มีตัวอย่างที่ SqlIndGrp=0) · ห่อ `BEGIN EXECUTE IMMEDIATE` ได้เมื่อ reference มีตัวอย่าง BEGIN..END เท่านั้น ไม่งั้น builder หยุดถาม (SqlIndGrp ไม่เดา)
- ค่า `SnpOrigTxt` / `SqlIndGrp` / topology / `<Admin>` / `<Encryption>` มาจาก reference เท่านั้น — **ห้ามฝังเลข 102/103/128 หรือค่าอื่นในโค้ด**
- schema ใน SQL ≠ `DefLschemaName` (logical schema ของ Topology) — คนละเรื่องกัน
- Package chain: `OkNextStep` → `IStep` ถัดไป · step สุดท้าย `OkNextStep=null` + `OkExit=1` · ทุก step `KoExit=1` (fail-fast)
- ไม่มี `LOG ERRORS` / `DBMS_ERRLOG` ในโปรเจกต์อ้างอิง → `error_handling=fail-fast` (เปลี่ยน = human-decide)
- Encoding ISO-8859-1 → ห้ามอักขระนอก latin-1 ใน step SQL (ดู rule ข้อ 2)

## 4. StepType ใน package

| StepType | ความหมาย | หมายเหตุ |
|---|---|---|
| `T` | procedure | ปกติ |
| `V` | refresh variable | ใช้ Refresh Query ของตัวแปร |
| `VS` | set variable | |
| `VE` | evaluate variable | **ต้องมี sample จาก Studio ก่อน** จึง generate ได้ |

## 5. ตัวแปร ODI

- นิยามใน `config/config.json` → `odi.variables` · ใช้ Refresh Query แทน task precheck เดิม (`replaces_tasks`) — ดู ADR-002
- อ้างใน SQL ด้วย `#PROJECT_CODE.VAR_NAME`

## 6. Log / runtime ของ ODI

- ตาราง `SNP_*` (session, step log) อยู่ใน schema ของ **work repository** (`odi.work_repo_schema`) ไม่ใช่ work user ของตาราง → diagnose script ต้องระบุ schema นั้น และให้คนรันด้วย user ที่มีสิทธิ์
- ค่าจริงของ Dev/SIT/Prod อยู่ใน `knowledge/environment-facts.md`

## 7. Checklist หลัง /gen-export

1. `python scripts/pipeline/validate_odi_xml.py` = 0 error
2. `python scripts/checks/verify_all.py --level V2` (XML ไม่ stale, SQL ใน XML = DML, GlobalId = Smart Export ล่าสุด)
3. `xml-auditor` ตรวจ drift
4. `python scripts/pipeline/gen_design_docs.py` (อัปเดต block AUTO ใน `.design/`)
