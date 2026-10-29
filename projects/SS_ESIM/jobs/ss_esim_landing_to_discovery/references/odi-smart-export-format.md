# ODI Smart Export XML — โครงสร้างที่ builder ประกอบ

> kit 2.8.0: XML สร้างด้วย `scripts/odi_builder/` (builder ของ md15) ผ่าน `scripts/pipeline/build_odi_export.py`
> **ทุกค่าอ่านจาก Smart Export ของ repository ปลายทาง (`input/odi_reference/`)** — ไฟล์นี้อธิบายโครงสร้างให้คนอ่านเท่านั้น
> ห้ามใช้เป็นแหล่งค่าที่จะฝังในโค้ด (เช่น เลข `SnpOrigTxt`) — แต่ละ repository อาจไม่เหมือนกัน

## Header (ลอกจาก reference, ยกเว้น Created / exportKeySalt)

```xml
<Admin IsSmartExportFile="true" RepositoryVersion="..." OdiVersion="..."
       OriginMasterRepositoryID="..." IsLegacyIdCompatible="false"
       OriginWorkRepositoryID="..." Created="..." />
<Encryption algorithm="AES" keyLength="128" exportKeyHash="null" keyVect="(จาก reference)"
            exportKeySalt="(สุ่มใหม่ต่อไฟล์)" containsCipherText="false"/>
```

## Object ที่ builder เขียน

| Class | ที่มา | หมายเหตุ |
|---|---|---|
| `SnpConnect` `SnpMtxt` `SnpConnectProp` `SnpLschema` `SnpPschema` `SnpContext` `SnpPschemaCont` | clone จาก reference (topology) | ไม่มี = **ODI-10113 Broken Link** · ห้ามเป็น FKXRef อย่างเดียว |
| `SnpReferencedObject` | clone จาก reference ตาม GlobalId ของ Context/Logical Schema | วางต่อจาก LineTrt / Var ที่ใช้ |
| `SnpProject` `SnpFolder` `SnpPackage` | สร้างใหม่ (GlobalId สุ่ม) | ชื่อ/รหัสจาก config.odi |
| `SnpGrpState` `SnpState2` | clone จาก reference (marker ของ project) | คอลัมน์ NOT NULL เดาไม่ได้ → ห้ามแต่งเอง (ORA-01400) |
| `SnpOrigTxt` | **id จาก reference ต่อ slot** (`SNP_TRT.I_TXT_TRT_TXT`, `SNP_LINE_TRT.DEF_I_TXT`, `SNP_VAR.I_TXT_VAR_IN`) | id ที่ไม่มีใน reference = `SnpsInexistantObjectException` ตอน import |
| `SnpTrt` | Procedure (1 task = 1 procedure) | `ITxtTrtTxt` ชี้ `SnpTxtHeader` placeholder (ไม่ใช่ null) |
| `SnpLineTrt` + `SnpTxtHeader` | 1 command line = 1 statement | `OrdTrt` ตามตำแหน่ง 10,20,… · `SqlIndGrp` ตาม **ชนิด statement** จากตัวอย่างใน reference (ไม่ใช่ตามลำดับ) |
| `SnpVar` | Refresh Variable | ค่า convention (IndStore/VarDatatype/VarType) จาก reference |
| `SnpStep` | chain เดียวใน Package | `OkExit=0` ทุก step ที่มีตัวถัดไป, `1` เฉพาะ step สุดท้าย |
| `SnpFKXRef` | index ของ object | มี `RefObjFQName` + `RefObjFQNameLengths` (คำนวณจาก segment จริง) |

## จุดสำคัญ

- **1 command line = 1 statement** — `TRUNCATE` กับ `INSERT` แยก `SnpLineTrt`
- `SqlIndGrp` ที่ reference ไม่มีตัวอย่าง (เช่น `BEGIN..END`, `DELETE` ถ้าไม่เคยเห็น) → builder **หยุดถาม** ไม่เดา
- schema ใน SQL เขียนเต็ม (`<SCHEMA>.TABLE`) — ODI ไม่เติมให้ SQL ดิบ · `DefLschemaName` คือ logical schema ของ Topology คนละเรื่อง
- ตัวแปร ODI อ้างด้วย `#PROJECT_CODE.VAR_NAME` (builder ตรวจชื่อว่ามี Variable นั้นจริง)
- Encoding ISO-8859-1 — ห้ามอักขระนอก latin-1 ทุกค่า รวมคอมเมนต์ (builder ปฏิเสธ; `build_odi_export.py` ตัดบรรทัดคอมเมนต์ที่ไม่ผ่านออกจาก step ก่อน ต้นฉบับยังอยู่ใน `output/dml/`)
- **GlobalId**: Smart Import จับคู่ด้วย GlobalId · `build_odi_export.py` reuse GlobalId เดิมเมื่อชื่อ project/folder/package ตรงกับ build ก่อน (จำใน `_guid_keys.json`) → import ทับ (Overwrite) ได้ · ชื่อไม่ตรง = project ใหม่ (GlobalId ใหม่ทั้งหมด)
- รหัสผ่านใน Topology ต้องเป็น `null` เสมอ (builder ลอก topology จาก reference ที่ผู้ใช้ export — ตรวจก่อนวาง reference ว่าไม่มี credential)
- Scenario ที่ compile แล้วไม่สร้าง — ไป generate ใน Studio
