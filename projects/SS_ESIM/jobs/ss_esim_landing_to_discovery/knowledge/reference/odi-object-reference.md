> **อ่านตอนไหน** — ต้องรู้โครงสร้าง XML / field ของ object ODI (ตอน /gen-export ผิดพลาด หรือตรวจ xml-auditor)

# โครงสร้าง object ของ ODI 14c SmartExport

> **ไฟล์นี้คืออะไร** — พจนานุกรมโครงสร้าง XML: object แต่ละตัวคืออะไร เชื่อกันยังไง
> field ไหน type อะไร และ convention ของ `SnpFKXRef`
> **อ่านตอนไหน** — ตอนจะประกอบไฟล์ด้วยมือ (คู่กับ`knowledge/reference/optional/manual-build-procedure.md`) หรือตอนสงสัยว่า ODI
> เวอร์ชันปลายทางมี field ไม่ตรงกับที่เขียนไว้ที่นี่

---

## A1. สองฟอร์แมต — อย่าสลับกัน **[พิสูจน์แล้ว]**

ODI Studio สร้าง XML สองแบบสำหรับโปรเจกต์เดียวกัน และใช้แทนกันไม่ได้
(ยืนยันโดยเทียบ export ทั้งสองแบบของโปรเจกต์เดียวกันจาก repository เดียวกัน)

| | **Smart Export** (แบบที่เราสร้าง) | **Export Project** (`PROJ_*.xml`) |
|---|---|---|
| สร้างจาก | คลิกขวา object → Export → Smart Export | คลิกขวา Project → Export → Export Project |
| import ด้วย | Smart Import | Import Project |
| ตัวอย่างจริง | 242 object | 174 object |
| Topology | **มี** — Connect, Mtxt, ConnectProp, Context, Lschema, Pschema, PschemaCont | **ไม่มี** — อาศัยชื่อ `DefLschemaName`/`DefContextCode` ที่ต้องมีอยู่แล้วปลายทาง |
| `SnpGrpState` / `SnpState2` | มี (3 + 18) | มี (3 + 18) |
| `DwgExportSummary` | **ไม่มี** | **มี** — เป็น object สุดท้ายเสมอ class อยู่ใต้ `dwg.` ไม่ใช่ `dwg.dbobj.` |
| attribute ของ `<Admin>` | `IsSmartExportFile="true"`, `RepositoryVersion`, `OdiVersion`, `OriginMasterRepositoryID`, `OriginWorkRepositoryID`, `IsLegacyIdCompatible`, `Created` | มีแค่ `RepositoryVersion` และ `IsLegacyIdCompatible` |

**ผลที่ต้องจำ**

- **ห้ามใส่ `DwgExportSummary` ใน Smart Export** ของจริงไม่มี
  ถ้าวันหนึ่งต้องสร้างฟอร์แมต Export Project ขึ้นมาจริงๆ ค่าในนั้นคำนวณได้ทั้งหมด
  **[เห็นในไฟล์จริง — ยืนยันกับ `PROJ_esim.xml` 174 object]** class อยู่ที่
  `com.sunopsis.dwg.DwgExportSummary` (ไม่ใช่ `.dbobj` — เป็นเหตุผลที่ grep แรกๆ หาไม่เจอ)
  และเป็น object สุดท้ายเสมอ:
  `TxtNb` = `OrigTxtNb` = จำนวน `SnpTxtHeader` · `StepNb` = จำนวน `SnpStep` ·
  `ExpTxtNb` = จำนวน `SnpExpTxtHeader` · `OtherObjectsNb` = จำนวน object ทั้งหมด ลบ
  (`SnpTxtHeader` + `SnpOrigTxt` + `SnpStep` + `SnpExpTxtHeader` + `SnpFKXRef` +
  `SnpReferencedObject` + ตัวมันเอง) · ที่เหลือเป็น 0 สำหรับโปรเจกต์ที่มีแต่ Procedure
- **ห้ามเปลี่ยนไปใช้ topology แบบอ้างชื่ออย่างเดียว** นั่นคือ convention ของ Export Project ถ้าทำใน Smart Export จะได้ `ODI-10113 Broken Link` (`knowledge/reference/delivery-checklist.md` ข้อ 2)
- **`<Admin>` ต้องตรงกับวิธีที่จะ import** ไฟล์ที่ใส่ header ของ project-export แล้วเอาไป Smart Import คือความไม่เข้ากันที่ทำให้เกิด error ที่อ่านไม่รู้เรื่อง — **ลอก `<Admin>` จาก reference** อย่าพิมพ์เอง

---

## A2. โครงไฟล์

```xml
<?xml version="1.0" encoding="ISO-8859-1"?>
<SunopsisExport>
  <Admin IsSmartExportFile="true" RepositoryVersion="…" OdiVersion="14.1.2"
         OriginMasterRepositoryID="…" IsLegacyIdCompatible="false"
         OriginWorkRepositoryID="…" Created="YYYY-MM-DD HH:MM:SS +0700" />
  <Encryption algorithm="AES" keyLength="128" exportKeyHash="null"
              keyVect="…" exportKeySalt="…" containsCipherText="false"/>
  <SmartExportList materializeShortcut="false">
  </SmartExportList>

  <Object class="com.sunopsis.dwg.dbobj.SnpXxx">
      <Field name="…" type="java.lang.String"><![CDATA[value]]></Field>
      <Field name="…" type="com.sunopsis.sql.DbInt">null</Field>
  </Object>
  …
  <Object class="com.sunopsis.dwg.dbobj.SnpFKXRef"> … </Object>
</SunopsisExport>
```

กติกาการเขียนค่า:

- ค่าที่มีอยู่จริง → `<![CDATA[…]]>`
- ค่าว่าง → ข้อความ `null` ดิบๆ **ไม่ใส่ CDATA**
- ทุก class อยู่ใต้ prefix `com.sunopsis.dwg.dbobj.`
- **`<Admin>` และ `<Encryption>` ลอกจาก reference** (เปลี่ยนได้แค่ `Created` และ `exportKeySalt`) — `keyVect` เป็นค่าฝั่ง repository การเอาค่าจาก export คนละไฟล์มาใส่คือการสมมติค่าที่ผิดกฎข้อเดียวของงานนี้

### ลำดับของ object ในไฟล์ **[อนุมาน — อ่านให้ครบ]**

object ที่บอกเจ้าของด้วย id (`SnpFolder.IProject`, `SnpLineTrt.ITrt`,
`SnpState2.IGrpState`, `SnpTxtHeader.ITxtOrig`, …) resolve ด้วย id นั้น และยังไม่เคยมี
ความพังที่สืบย้อนไปถึงตำแหน่งในไฟล์

**`SnpReferencedObject` เป็นข้อยกเว้น** — เป็น class เดียวที่ **ไม่มี field ชี้ไปที่เจ้าของ**:

```
IObject   ObjectPKasString   ObjectAKasString   Description   GlobalId
```

และ `GlobalId` ที่มันถืออยู่เป็นของ object ที่มัน *อธิบาย* (Context หรือ Logical Schema)
ไม่ใช่ของ `SnpVar` / `SnpLineTrt` ที่มันสังกัด เท่าที่หลักฐานบอกได้ **ตำแหน่งคือสิ่งเดียว
ที่เชื่อมสองอย่างเข้าด้วยกัน** ฉะนั้นให้วางตามรูปแบบของ reference เป๊ะ: 1 แถวหลัง `SnpVar`
แต่ละตัว, 2 แถวหลัง `SnpLineTrt` แต่ละบรรทัด — **อย่าสลับลำดับแถวพวกนี้โดยอ้างว่า
ลำดับไม่สำคัญ**

### `IObject` คือ type code และบทบาทของ class นี้ต่างกันตามฟอร์แมต

`IObject` ไม่ใช่ id ของ object ไหน — มันคือ **รหัสชนิดของตารางที่ถูกอ้างถึง**
ค่าที่ยืนยันแล้วจากไฟล์จริงสองฟอร์แมต:

| `IObject` | ชี้ไปที่ | เห็นใน |
|---|---|---|
| `1500` | `SNP_PSCHEMA` | Smart Export |
| `1700` | `SNP_CONTEXT` | Smart Export |
| `2100` | `SNP_LSCHEMA` | Smart Export |
| `3500` | `SNP_VAR` | Export Project |
| `3600` | `SNP_TRT` | Export Project |

**บทบาทของ class นี้ไม่เหมือนกันในสองฟอร์แมต** — อย่าเอาความเข้าใจจากไฟล์หนึ่ง
ไปอ่านอีกไฟล์:

| | **Smart Export** | **Export Project** |
|---|---|---|
| จำนวนแถว | มาก (ไฟล์ตัวอย่าง 66 แถว) | น้อย — เท่าจำนวน object ที่สั่ง export |
| ชี้ไปที่อะไร | topology ที่ object ข้างหน้ามันใช้ (Context / Lschema / Pschema) | Variable และ Procedure ที่ผู้ใช้เลือก export |
| `ObjectAKasString` | คีย์ทางเลือกของ topology เช่น `77##DSSDEV` | `<IProject>#<ชื่อ>` สำหรับ Variable, null สำหรับ Procedure |
| `Description` | `SNP_TECHNO : Oracle #SNP_LSCHEMA : DSS_ODI_LOG` | `SNP_PROJECT : <project> #SNP_VAR : <ชื่อ>` |
| หน้าที่ | descriptor ต่อการใช้งานหนึ่งครั้ง | สารบัญว่า export นี้ถูกสั่งให้เอาอะไรมา |

ในฟอร์แมตที่เอกสารชุดนี้สร้าง (Smart Export) ให้ยึดคอลัมน์ซ้าย

---

## A3. กับดักเรื่อง `type=` **[พิสูจน์แล้ว]**

field ที่ค่าดูเป็นตัวเลขจำนวนมาก ประกาศเป็น `java.lang.String` ไม่ใช่ `com.sunopsis.sql.DbInt`

| String ทั้งที่ค่าดูเป็นเลข | DbInt |
|---|---|
| `OkExit`, `KoExit`, `OkExitCode`, `KoExitCode` | `IStep`, `OkNextStep`, `KoNextStep` |
| `IndChange`, `IndGenerateLoad`, `IndIsHidden`, `IndErr`, `IndLogFinalCmd`, `IndLogNb`, `IndStore` | `ITrt`, `IVar`, `ILineTrt`, `ITxt`, `ITxtOrig` |
| `CleanupOnError`, `IsConcurrent`, `KimMultiDserver`, `AlwaysExe` | `IProject`, `IFolder`, `IPackage`, `IntVersion` |
| `Enc`, `SqlIndGrp`, `LogLevDet` | `PosX`, `PosY`, `Nno`, `OrdTrt`, `OrdFolder` |

**กลไกที่ทำให้เรื่องนี้ร้ายกว่าที่คิด** — attribute `type=` อธิบาย **property ฝั่ง Java**
ไม่ใช่คอลัมน์ในฐานข้อมูล ถ้าใส่ type ผิด ODI ไม่ได้แปลงให้และไม่ได้เมิน — deserializer
ปล่อยให้ property นั้นไม่ถูกเซ็ต แล้วจุดที่เรียก `.equals()` ตัวถัดไปจะโยน
`NullPointerException` ⇒ error ไม่โผล่ตรงที่ field อยู่ แต่โผล่ตรงที่มันถูกอ่านครั้งแรก

**ห้ามเดา type จากค่า** ใช้ตารางในหัวข้อ A7 และเทียบกับ reference ทุกครั้ง

---

## A4. object เชื่อกันยังไง

```
SnpProject (IProject)
└── SnpFolder (IFolder → IProject)
    ├── SnpPackage (IPackage → IFolder)
    │   └── SnpStep (IStep → IPackage)          หนึ่งตัวต่อหนึ่ง step
    │         ├── StepType="T" → ITrt           step แบบ Procedure
    │         └── StepType="V" → IVar, VarOp="=" step แบบ Variable
    ├── SnpTrt (ITrt → IProject / IFolder)      หนึ่งตัวต่อหนึ่ง Procedure
    │   ├── ITxtTrtTxt → SnpTxtHeader           ช่อง editor ที่ Txt เป็น null เสมอ
    │   └── SnpLineTrt (ILineTrt → ITrt)        หนึ่งตัวต่อหนึ่งบรรทัดคำสั่ง
    │         └── DefITxt → SnpTxtHeader        ตัว SQL จริง
    └── SnpVar (IVar → IProject)                หนึ่งตัวต่อหนึ่ง Variable
          └── ITxtVarIn → SnpTxtHeader          refresh query

ทุก SnpTxtHeader.ITxtOrig → SnpOrigTxt          ค่า seed ของ repository ใช้ร่วมกัน
```

### `SnpStep` — สายโซ่ของ Package **[พิสูจน์แล้ว]**

step เป็น **linked list เส้นเดียว ไม่ใช่กราฟ** — `OkNextStep` ของแต่ละตัวชี้ `IStep` ตัวถัดไป
ตัวสุดท้าย `OkNextStep=null`

- `OkExit="0"` ทุก step ที่ยังมี `OkNextStep` และ `"1"` **เฉพาะตัวสุดท้าย**
  ถ้าใส่ `"1"` ทุกตัว Studio จะวาดไดอะแกรมที่ **ไม่มีลูกศรเชื่อมเลย** เพราะมันแปลว่า
  "step นี้จบ package" ทุกตัว แล้วมันจะเมิน `OkNextStep` ทั้งหมด
- `KoExit="1"` ทุก step ในไฟล์จริง = พังแล้วหยุดทั้ง package `KoNextStep` แตกสายตอน error ได้
  แต่ให้ทำก็ต่อเมื่อมีตัวอย่างจริงให้ลอก
- `Nno` คือลำดับเริ่มที่ 0, `PosX`/`PosY` คือพิกัดในไดอะแกรม
- step แบบ Procedure ตั้ง `ITrt` และปล่อย `IVar` เป็น null
  step แบบ Variable ตั้ง `IVar`, `VarOp="="` และปล่อย `ITrt` เป็น null

**กติกาตอนอ่านไฟล์ของคนอื่น (ต่างจากตอนเขียนของตัวเอง)** **[เห็นในไฟล์จริง]**

- **`IStep` ข้ามเลขได้** step ที่ถูกลบหรือถูก renumber ใน Studio ทิ้งช่องว่างไว้ —
  ไฟล์ตัวอย่างที่ใช้อยู่มี `IStep` 1–9 แล้วกระโดดไป 11 **ห้ามอนุมานว่า step N รันก่อน
  N+1 เพราะเลขติดกัน** ลำดับการรันมาจากสาย `OkNextStep` เท่านั้น
- ตอน**เขียน**ไฟล์ใหม่ ใช้เลขเรียง 1, 2, 3, … ได้ตามปกติ ไม่มีเหตุผลต้องเว้นช่อง

DAG ของ Blendata มี fan-out / fan-in จริง (`parentTask` เป็น array) ODI Package
เขียนแบบนั้นใน step chain ไม่ได้ ต้องบีบเป็นลำดับเดียว **และคนต้องยืนยันลำดับนั้น**

### `SnpTrt` / `SnpLineTrt` / `SnpTxtHeader` — หนึ่ง Procedure

- `SnpTrt` คือ Procedure — `TrtType`, `KmTechno`, `KmSrcTechno` อ่านจาก reference
- `ITxtTrtTxt` ชี้ไป `SnpTxtHeader` ที่ `Txt` เป็น null เสมอ — ช่อง editor ที่ไม่ได้ใช้ แต่**ต้องมี**
- แต่ละบรรทัดคำสั่งคือ `SnpLineTrt` หนึ่งตัว มี `OrdTrt`, `DefITxt` → `SnpTxtHeader` ที่เก็บ SQL และค่าผูกการรันเป็น string ล้วน: `DefContextCode`, `DefLschemaName`, `DefTechno`/`ColTechno`, `ExeChannel`, `MapTaskType`, `SqlName`, `LogLevDet` — **ทุกค่าอ่านจาก reference**
- หลัง `SnpLineTrt` แต่ละตัว ตามด้วย `SnpReferencedObject` 2 แถว (Context และ Logical Schema) ลอกจาก reference

**ตอนอ่านไฟล์: ลำดับการรันของบรรทัดคำสั่งมาจาก `OrdTrt` ไม่ใช่ตำแหน่งในไฟล์**
**[เห็นในไฟล์จริง]** `SnpLineTrt` ของ Procedure เดียวกันวางสลับลำดับกันในไฟล์ได้ —
ในไฟล์ตัวอย่างที่ใช้อยู่ บรรทัด `OrdTrt=20` มาก่อน `OrdTrt=10` ในบาง Procedure
**ต้อง sort ตาม `OrdTrt` ก่อนเสมอ** ก่อนสรุปว่าคำสั่งไหนรันก่อน

### `OrdTrt` กับ `SqlIndGrp` เป็นคนละแกน — ห้ามคำนวณจากกันและกัน **[เห็นในไฟล์จริง]**

| Procedure | `OrdTrt` | คำสั่ง | `SqlIndGrp` |
|---|---|---|---|
| overwrite | 10 | `TRUNCATE` | `0` |
| overwrite | 20 | `INSERT` | `2` |
| append | **10** | `INSERT` | **`2`** |
| upsert | **10** | `MERGE` | **`2`** |

- **`OrdTrt` คือตำแหน่งบรรทัด** บรรทัดแรก = 10 บรรทัดที่สอง = 20 ไม่ว่าคำสั่งเป็นอะไร
  Procedure แบบ append ที่มีบรรทัดเดียวอยู่ที่ **10 ไม่ใช่ 20**
- **`SqlIndGrp` เป็นคุณสมบัติของคำสั่ง** `TRUNCATE` → `"0"`, `INSERT`/`MERGE` → `"2"` ที่ตำแหน่งไหนก็ตาม

ถ้าคำนวณ `SqlIndGrp` จาก `OrdTrt` จะได้ `"0"` บน `INSERT` ก้อนใหญ่ทันทีที่ Procedure มี
บรรทัด append เดียว — ซึ่งเป็นคู่ที่ไม่ปรากฏใน export จริงเลย บน field ที่ค่าผิดเคยทำให้เกิด
NullPointerException มาแล้ว (A3)

**วิธีที่ถูก** — อ่านกฎจาก reference เอง: จับคู่ `SnpTxtHeader` แต่ละแถวเข้ากับ slot ของมัน
(ผ่าน `ITxtOrig`) แล้วดูว่าคำแรกของ `Txt` คืออะไร ได้เป็นตาราง *คำสั่ง → ค่า → เห็นกี่ครั้ง*

- เห็นค่าเดียว ≥ 2 ครั้ง → ใช้ได้ เป็นกฎ
- เห็นค่าเดียวแค่ **ครั้งเดียว** → ใช้ได้ **ไม่ต้องบอก/ถามผู้ใช้ที่ I2** — ให้บันทึกไว้ในรายงานส่งมอบ (`knowledge/reference/validation-and-cutover.md E6`) ว่ามาจากตัวอย่างเดียว
- เห็นหลายค่า หรือไม่มีตัวอย่างเลย → **หยุดแล้วถาม**

ในไฟล์จริง refresh query ของ Variable **กำกวม** — `SELECT … FROM DUAL` ทรงเดียวกันมีทั้ง
`0` และ `2` อะไรคือตัวแยกยังไม่รู้ ฉะนั้นค่าของ Variable ต้องให้คนระบุ

### `SnpVar` — หนึ่ง Variable

`VarType`, `VarDatatype`, `IndStore`, `LschemaName` อ่านจาก Variable ที่มีใน reference
(ในไฟล์จริงคือ `P` = declare/refresh, `T` = text, `L`) `ITxtVarIn` ชี้ไป refresh SELECT
SQL อ้างถึงมันด้วย `#PROJECTCODE.VARNAME`

### bind variable

SQL เข้าถึง Variable ของโปรเจกต์ด้วย `#<PROJECT_CODE>.<VARNAME>` ซึ่ง ODI แทนค่าตอนรัน
ผลที่ตามมาสองข้อ:

- **code ห้ามมีจุดและห้ามมีช่องว่าง** ไม่งั้น reference ทั้งโปรเจกต์ parse ไม่ได้
- **ชื่อหลังจุดต้องเป็น Variable ที่ประกาศไว้จริง** ตรวจแค่ prefix ไม่พอ — `#AI_TEST_01.V_SUCESS`
  จะ import ผ่านแล้วแทนค่าเป็นค่าว่างตอนรัน
- **ทิศกลับด้านไม่ผิด** — Variable ที่ประกาศแล้วไม่มีใน SQL เป็นเรื่องปกติ (ตัวแปรสถานะ
  ทำงานผ่าน Package step ไม่ใช่ผ่าน bind)
- `#GLOBAL.<VAR>` เป็น namespace ของ global variable ซึ่งอยู่ระดับ repository นอกโปรเจกต์ —
  ไฟล์ตรวจไม่ได้ ปล่อยไว้

### `SnpOrigTxt` — ค่า seed ของ repository ห้ามแต่งขึ้น **[พิสูจน์แล้ว]**

หนึ่งแถวต่อหนึ่ง slot `(SnpsTable, SnpsCol)` ใช้ร่วมกันทั้งไฟล์

| slot | `SnpsTable` | `SnpsCol` | `OrigineName` | ค่าที่เห็นใน 14.1.2 |
|---|---|---|---|---|
| refresh query ของ Variable | `SNP_VAR` | `I_TXT_VAR_IN` | Variable Query | 128 |
| ช่อง editor ของ Procedure | `SNP_TRT` | `I_TXT_TRT_TXT` | Edit Command | 107 |
| ตัว SQL ของบรรทัดคำสั่ง | `SNP_LINE_TRT` | `DEF_I_TXT` | Target Technology | 102 |

**เลขในคอลัมน์ขวาเป็นแค่ตัวอย่าง ห้ามลอกไปใช้** — ต้องอ่านจาก reference ของ repository
ปลายทางทุกครั้ง เลขพวกนี้ถูก seed ตอนสร้าง repository และ import จะไปหา **ในฐานข้อมูล
ปลายทาง ไม่ใช่ในไฟล์** เลขที่ไม่มีอยู่ใน repository ไหนเลยจึง resolve ไม่ได้

**ไม่ใช่ทุก `ITxtOrig` ในไฟล์ที่ต้องมีแถว `SnpOrigTxt` และนั่นถูกแล้ว** — `SnpMtxt`
ที่ลอกมาจาก topology ถือ `ITxtOrig` ของ slot ที่สี่ติดมาด้วย และ export จริงก็ไม่มีแถวให้มัน
เหมือนกัน สามแถวข้างบนมีเพราะเป็น slot ที่ *เราเขียนข้อความลงไปเอง* id ที่ติดมากับ object
ที่ลอกทั้งดุ้นนั้น resolve ได้อยู่แล้วในปลายทาง

### topology

`SnpConnect` (+ `SnpMtxt` ที่เก็บ JDBC URL + `SnpConnectProp`), `SnpContext`, `SnpLschema`,
`SnpPschema`, `SnpPschemaCont` และ `SnpReferencedObject` อีก 3 แถว — **ลอกทั้งดุ้นจาก
reference ทุก byte รวม GlobalId เดิม** `Pass` เป็น null ในไฟล์จริง credential ไม่เดินทาง
มากับ SmartExport

### project marker metadata

`SnpGrpState` (3) + `SnpState2` (18) — ชุด Priorities / Progress / Smileys ที่ทุกโปรเจกต์ ODI มี
**ลอกจาก reference** โดยเปลี่ยนแค่ `GlobalId` เป็นตัวใหม่และ `IProject` เป็นของเรา ค่าอื่นลอก
ทุก byte เพราะคอลัมน์เบื้องหลังเป็น NOT NULL และค่าอย่าง `GrpOrderDisp`, `TreeDisplay`,
`IndAutoIncrement`, `IconRes` (`/markers/taskprior_1.gif`) เดาไม่ได้
มีเฉพาะ `SnpGrpState` ที่ถูก index ใน `SnpFKXRef` ส่วน `SnpState2` ไม่มี

---

## A5. `SnpFKXRef` — สารบัญการอ้างอิงข้ามกัน

object ที่ถูกตัวอื่นอ้างถึงจะมีแถวของตัวเองหนึ่งแถว: `RefKey`, `RefObjGlobalId` และ
(ถ้ามี) `RefObjFQName` / `RefObjFQType` / `RefObjFQNameLengths`

| `RefKey` | `FQName` | `FQType` |
|---|---|---|
| `SNP_TECHNO.<n>` | `Oracle` | `SNP_TECHNO` |
| `SNP_CONNECT.<n>` | `Oracle.<conn>` | `SNP_TECHNO.SNP_CONNECT` |
| `SNP_CONTEXT.<n>` | `<context>` | `SNP_CONTEXT` |
| `SNP_LSCHEMA.<n>` | `Oracle.<lschema>` | `SNP_TECHNO.SNP_LSCHEMA` |
| `SNP_PSCHEMA.<n>` | `Oracle.<conn>.<conn>.<schema>` | `SNP_TECHNO.SNP_CONNECT.SNP_PSCHEMA` |
| `SNP_PROJECT.<n>` | `<project>` | `SNP_PROJECT` |
| `SNP_FOLDER.<n>` | `<project>.<folder>` | `SNP_PROJECT.SNP_FOLDER` |
| `SNP_PACKAGE.<n>` | `<project>.<folder>.<package>` | `SNP_PROJECT.SNP_FOLDER.SNP_PACKAGE` |
| `SNP_STEP.<n>` | `<project>.<folder>.<package>.<step>` | `SNP_PROJECT.SNP_FOLDER.SNP_PACKAGE.SNP_STEP` |
| `SNP_TRT.<n>` | `<project>.<procedure>` | `SNP_PROJECT.SNP_TRT` |
| `SNP_VAR.<n>` | `<project>.<variable>` | `SNP_PROJECT.SNP_VAR` |
| `SNP_GRPSTATE.<n>` | `<project>.<groupname>` | `SNP_PROJECT.SNP_GRPSTATE` |
| `SNP_TXTHEADER.<n>` | null | null |
| `SNP_ORIGTXT.<n>` | null | null (และ `RefObjGlobalId` เป็น null ด้วย) |
| `SNP_MTXT.<n>` | null | null |

### `RefObjFQNameLengths` คือตัวคั่น ไม่ใช่จุด **[พิสูจน์แล้ว]**

ชื่อเต็มอย่าง `esim.First Folder.esim.020000_overwrite_ss_esim_checkpoint_temp`
**ห้าม `split(".")`** — ค่าที่คู่กันคือ `4.12.4.40` ซึ่งคือความยาวตัวอักษรของแต่ละ segment จริง

**วิธีที่ถูก** — เก็บชื่อไว้เป็น *รายการ segment* ตั้งแต่แรก แล้วสร้างทั้งสองค่าจากรายการนั้น:

```
segments = ["esim", "First Folder", "esim", "020000_overwrite_ss_esim_checkpoint_temp"]
RefObjFQName        = "esim.First Folder.esim.020000_overwrite_ss_esim_checkpoint_temp"
RefObjFQNameLengths = "4.12.4.40"
```

ถ้าคำนวณจากสตริงที่ต่อแล้ว จะได้จำนวน segment ผิดทันทีที่ชื่อไหนมีจุดอยู่ข้างใน
**ตรวจได้ง่ายๆ:** ผลรวมของตัวเลขใน lengths + (จำนวน segment − 1) ต้องเท่ากับความยาว FQName

**`RefKey` ต้องไม่ซ้ำกันทั้งไฟล์** เลขท้ายเป็น sequence แยกตามชนิด — การเอา XML สองไฟล์
มาต่อกันจะทำให้ชนกัน สร้างไฟล์เดียวในรอบเดียวเสมอ

---

## A6. local id กับ GlobalId

- **local id** (`IProject`, `ITrt`, `IStep`, `ITxt`, …) มีความหมายแค่ในไฟล์ repository
  จะออกเลขจริงให้ตอน import ขอแค่ไม่ซ้ำกันในชนิดเดียวกันและอ้างถึงกันถูก **[อนุมาน]**
- **`GlobalId`** คือสิ่งที่ Smart Import ใช้จับคู่ — GlobalId เดิม = จับคู่ของที่มีอยู่,
  GlobalId ใหม่ = สร้างใหม่ นี่คือเหตุผลที่ topology ลอก GlobalId เดิมมา (จับคู่) ส่วน object
  ของโปรเจกต์ใหม่ได้ GlobalId ใหม่ (สร้าง)
- **ถ้าจะ import ทับของเดิม ต้องใช้ GlobalId ชุดเดิม** — สุ่มใหม่ทุกครั้งจะได้ของซ้ำวางข้าง
  ของเก่า ไม่ใช่การอัปเดต **[พิสูจน์แล้ว]** เก็บ GlobalId ไว้ใน build spec ถ้าเรื่องนี้สำคัญ

---

## A7. ตาราง field ครบทุกตัว

เรียงตามลำดับที่ต้องเขียนในไฟล์ **[เห็นในไฟล์จริง — ODI 14.1.2]**
ทุกครั้งที่ใช้ ให้เทียบกับ reference ที่มีอยู่จริงก่อน: ถ้า ODI ปลายทางคนละ build ชุด field
อาจต่างกัน ซึ่งกรณีนั้นให้ยึด reference ไม่ใช่ตารางนี้

`type=` ในตาราง: **String** = `java.lang.String` · **DbInt** = `com.sunopsis.sql.DbInt` ·
**Timestamp** = `java.sql.Timestamp`

### `SnpProject` — 14 fields

| # | Field | `type=` |
|---|---|---|
| 1 | `BegVersion` | Timestamp |
| 2 | `ExtVersion` | String |
| 3 | `FirstDate` | Timestamp |
| 4 | `FirstUser` | String |
| 5 | `GlobalId` | String |
| 6 | `IndChange` | String |
| 7 | `IntVersion` | DbInt |
| 8 | `IProject` | DbInt |
| 9 | `LastDate` | Timestamp |
| 10 | `LastUser` | String |
| 11 | `ProjectCode` | String |
| 12 | `ProjectName` | String |
| 13 | `PrvVersion` | DbInt |
| 14 | `VLastDate` | Timestamp |

### `SnpFolder` — 15 fields

| # | Field | `type=` |
|---|---|---|
| 1 | `ExtVersion` | String |
| 2 | `FirstDate` | Timestamp |
| 3 | `FirstUser` | String |
| 4 | `FolderName` | String |
| 5 | `GlobalId` | String |
| 6 | `IndChange` | String |
| 7 | `IntVersion` | DbInt |
| 8 | `IFolder` | DbInt |
| 9 | `IProject` | DbInt |
| 10 | `LastDate` | Timestamp |
| 11 | `LastUser` | String |
| 12 | `OrdFolder` | DbInt |
| 13 | `ParIFolder` | DbInt |
| 14 | `ReleaseTag` | String |
| 15 | `VLastDate` | Timestamp |

### `SnpPackage` — 21 fields

| # | Field | `type=` |
|---|---|---|
| 1 | `ExtVersion` | String |
| 2 | `FirstDate` | Timestamp |
| 3 | `FirstUser` | String |
| 4 | `GlobalId` | String |
| 5 | `IndChange` | String |
| 6 | `IntVersion` | DbInt |
| 7 | `IFolder` | DbInt |
| 8 | `IPackage` | DbInt |
| 9 | `IScBasePackage` | DbInt |
| 10 | `IScOrigPackage` | DbInt |
| 11 | `IScPackage` | DbInt |
| 12 | `IState` | DbInt |
| 13 | `ITxtPack` | DbInt |
| 14 | `LastDate` | Timestamp |
| 15 | `LastUser` | String |
| 16 | `OrdFolder` | DbInt |
| 17 | `PackName` | String |
| 18 | `RepGuid` | String |
| 19 | `RepVersion` | String |
| 20 | `ScOrigPackageTag` | String |
| 21 | `VLastDate` | Timestamp |

### `SnpVar` — 22 fields

| # | Field | `type=` |
|---|---|---|
| 1 | `DefDate` | Timestamp |
| 2 | `DefN` | DbInt |
| 3 | `DefV` | String |
| 4 | `ExtVersion` | String |
| 5 | `FirstDate` | Timestamp |
| 6 | `FirstUser` | String |
| 7 | `GlobalId` | String |
| 8 | `IndChange` | String |
| 9 | `IndStore` | String |
| 10 | `IntVersion` | DbInt |
| 11 | `IProject` | DbInt |
| 12 | `ITxtVar` | DbInt |
| 13 | `ITxtVarIn` | DbInt |
| 14 | `ITxtVarValTxt` | DbInt |
| 15 | `IVar` | DbInt |
| 16 | `LastDate` | Timestamp |
| 17 | `LastUser` | String |
| 18 | `LschemaName` | String |
| 19 | `VarDatatype` | String |
| 20 | `VarName` | String |
| 21 | `VarType` | String |
| 22 | `VLastDate` | Timestamp |

### `SnpTrt` — 58 fields

| # | Field | `type=` |
|---|---|---|
| 1 | `CleanupOnError` | String |
| 2 | `CompType` | String |
| 3 | `DelegateClass` | String |
| 4 | `DelegateScript` | String |
| 5 | `ExpectedAstClass` | String |
| 6 | `ExtVersion` | String |
| 7 | `FirstDate` | Timestamp |
| 8 | `FirstUser` | String |
| 9 | `GlobalId` | String |
| 10 | `IndChange` | String |
| 11 | `IndExcludeExUnitBegin` | String |
| 12 | `IndExcludeExUnitEnd` | String |
| 13 | `IndExcludeExUnitMain` | String |
| 14 | `IndExcludeMapBegin` | String |
| 15 | `IndExcludeMapCleanup` | String |
| 16 | `IndExcludeMapEnd` | String |
| 17 | `IndGenerateLoad` | String |
| 18 | `IndIsHidden` | String |
| 19 | `IndJrnMethod` | String |
| 20 | `IndSuppSetBased` | String |
| 21 | `IntgType` | String |
| 22 | `IntVersion` | DbInt |
| 23 | `IsConcurrent` | String |
| 24 | `IsSeeded` | String |
| 25 | `IBaseCompKm` | DbInt |
| 26 | `IFolder` | DbInt |
| 27 | `IProject` | DbInt |
| 28 | `IScBaseTrt` | DbInt |
| 29 | `IScOrigTrt` | DbInt |
| 30 | `IScTrt` | DbInt |
| 31 | `ITrt` | DbInt |
| 32 | `ITxtDelTxt` | DbInt |
| 33 | `ITxtTrtTxt` | DbInt |
| 34 | `KimMultiDserver` | String |
| 35 | `KmDefault` | String |
| 36 | `KmLang` | String |
| 37 | `KmSrcLang` | String |
| 38 | `KmSrcTechno` | String |
| 39 | `KmTechno` | String |
| 40 | `KmVersion` | String |
| 41 | `LastDate` | Timestamp |
| 42 | `LastUser` | String |
| 43 | `LkmType` | String |
| 44 | `LChecksum` | DbInt |
| 45 | `LCode` | String |
| 46 | `OggJkm` | String |
| 47 | `OrdFolder` | DbInt |
| 48 | `ProcType` | String |
| 49 | `ProdAstType` | String |
| 50 | `RepGuid` | String |
| 51 | `RepVersion` | String |
| 52 | `ScriptPath` | String |
| 53 | `ScOrigTrtTag` | String |
| 54 | `Subtype` | String |
| 55 | `TrtName` | String |
| 56 | `TrtType` | String |
| 57 | `VariableDefs` | String |
| 58 | `VLastDate` | Timestamp |

### `SnpLineTrt` — 64 fields

| # | Field | `type=` |
|---|---|---|
| 1 | `AlwaysExe` | String |
| 2 | `BrpId` | DbInt |
| 3 | `ColConnectId` | String |
| 4 | `ColContextCode` | String |
| 5 | `ColIndCommit` | String |
| 6 | `ColIsolLevel` | String |
| 7 | `ColITxt` | DbInt |
| 8 | `ColLanguage` | String |
| 9 | `ColLschemaName` | String |
| 10 | `ColTechno` | String |
| 11 | `DefConnectId` | String |
| 12 | `DefContextCode` | String |
| 13 | `DefIndCommit` | String |
| 14 | `DefIsolLevel` | String |
| 15 | `DefITxt` | DbInt |
| 16 | `DefLanguage` | String |
| 17 | `DefLschemaName` | String |
| 18 | `DefTechno` | String |
| 19 | `ExeChannel` | String |
| 20 | `FirstDate` | Timestamp |
| 21 | `FirstUser` | String |
| 22 | `GlobalId` | String |
| 23 | `IndErr` | String |
| 24 | `IndLogFinalCmd` | String |
| 25 | `IndLogNb` | String |
| 26 | `ILineTrt` | DbInt |
| 27 | `IRefLineTrt` | DbInt |
| 28 | `IRefTrt` | DbInt |
| 29 | `ITrt` | DbInt |
| 30 | `KcmAk` | String |
| 31 | `KcmCond` | String |
| 32 | `KcmErrDel` | String |
| 33 | `KcmJoin` | String |
| 34 | `KcmNull` | String |
| 35 | `KcmPk` | String |
| 36 | `KimDrvdSel` | String |
| 37 | `KimIdx` | String |
| 38 | `KimJrn` | String |
| 39 | `KimJrnPop` | String |
| 40 | `KjmCreate` | String |
| 41 | `KjmDrop` | String |
| 42 | `KjmExtend` | String |
| 43 | `KjmInstall` | String |
| 44 | `KjmLock` | String |
| 45 | `KjmPurge` | String |
| 46 | `KjmSetInstall` | String |
| 47 | `KjmSetUninstall` | String |
| 48 | `KjmSubscribe` | String |
| 49 | `KjmTableOrder` | String |
| 50 | `KjmUninstall` | String |
| 51 | `KjmUnlock` | String |
| 52 | `KjmUnsubscribe` | String |
| 53 | `KlmAfterInt` | String |
| 54 | `KlmIdx` | String |
| 55 | `KlmJrn` | String |
| 56 | `LastDate` | Timestamp |
| 57 | `LastUser` | String |
| 58 | `LineType` | String |
| 59 | `LogLevDet` | String |
| 60 | `MapTaskType` | String |
| 61 | `OrdTrt` | DbInt |
| 62 | `SqlName` | String |
| 63 | `SupportedSubtypes` | String |
| 64 | `VariableDefs` | String |

### `SnpTxtHeader` — 8 fields

| # | Field | `type=` |
|---|---|---|
| 1 | `Enc` | String |
| 2 | `EncKey` | String |
| 3 | `EncKeyVect` | String |
| 4 | `GlobalId` | String |
| 5 | `ITxt` | DbInt |
| 6 | `ITxtOrig` | DbInt |
| 7 | `SqlIndGrp` | String |
| 8 | `Txt` | String |

### `SnpOrigTxt` — 5 fields

| # | Field | `type=` |
|---|---|---|
| 1 | `GlobalId` | String |
| 2 | `ITxtOrig` | DbInt |
| 3 | `OrigineName` | String |
| 4 | `SnpsCol` | String |
| 5 | `SnpsTable` | String |

### `SnpReferencedObject` — 5 fields

| # | Field | `type=` |
|---|---|---|
| 1 | `IObject` | DbInt |
| 2 | `ObjectPKasString` | String |
| 3 | `ObjectAKasString` | String |
| 4 | `Description` | String |
| 5 | `GlobalId` | String |

### `SnpStep` — 61 fields

| # | Field | `type=` |
|---|---|---|
| 1 | `BrpId` | DbInt |
| 2 | `Clean` | String |
| 3 | `ContextCode` | String |
| 4 | `CreateJournal` | String |
| 5 | `CreateSubcriber` | String |
| 6 | `DeleteErrors` | String |
| 7 | `DropJournal` | String |
| 8 | `DropSubscriber` | String |
| 9 | `ExtendJrn` | String |
| 10 | `ExtVersion` | String |
| 11 | `FirstDate` | Timestamp |
| 12 | `FirstUser` | String |
| 13 | `GlobalId` | String |
| 14 | `HeightVal` | DbInt |
| 15 | `IndChange` | String |
| 16 | `IndLogMethod` | String |
| 17 | `IntVersion` | DbInt |
| 18 | `IDeploySpec` | DbInt |
| 19 | `IMapping` | DbInt |
| 20 | `IMod` | DbInt |
| 21 | `IPackage` | DbInt |
| 22 | `IPop` | DbInt |
| 23 | `IScMapping` | DbInt |
| 24 | `IScPop` | DbInt |
| 25 | `IScTable` | DbInt |
| 26 | `IScTrt` | DbInt |
| 27 | `ISmod` | DbInt |
| 28 | `IStep` | DbInt |
| 29 | `ITable` | DbInt |
| 30 | `ITrt` | DbInt |
| 31 | `ITxtAction` | DbInt |
| 32 | `ITxtSubscribers` | DbInt |
| 33 | `ITxtVarValue` | DbInt |
| 34 | `IVar` | DbInt |
| 35 | `KoExit` | String |
| 36 | `KoExitCode` | String |
| 37 | `KoNextStep` | DbInt |
| 38 | `KoRetry` | DbInt |
| 39 | `KoRetryInterv` | DbInt |
| 40 | `LastDate` | Timestamp |
| 41 | `LastUser` | String |
| 42 | `LockJrn` | String |
| 43 | `ModCod` | String |
| 44 | `Nno` | DbInt |
| 45 | `OkExit` | String |
| 46 | `OkExitCode` | String |
| 47 | `OkNextStep` | DbInt |
| 48 | `PosX` | DbInt |
| 49 | `PosY` | DbInt |
| 50 | `PurgeJrn` | String |
| 51 | `RecurseSubmod` | String |
| 52 | `SetInstallJrn` | String |
| 53 | `SetUninstallJrn` | String |
| 54 | `SmodCod` | String |
| 55 | `StepName` | String |
| 56 | `StepType` | String |
| 57 | `TableName` | String |
| 58 | `UnlockJrn` | String |
| 59 | `VarIncr` | DbInt |
| 60 | `VarOp` | String |
| 61 | `WidthVal` | DbInt |


---

## A8. สิ่งที่จงใจไม่สร้าง

| ไม่สร้าง | เหตุผล |
|---|---|
| `SnpScen` / `SnpScenStep` / `SnpScenTask` / `SnpVarScen` / `SnpExpTxtHeader` | Scenario — Studio generate ให้ในคลิกเดียว การปั้นของที่ compile แล้วด้วยมือคือการเดาที่เสี่ยงเกินไป |
| `DwgExportSummary` | เป็นของฟอร์แมต Export Project ไม่มีใน Smart Export จริง (A1) |
| `SnpMapComp` / `SnpMapCp` / `SnpMapAttr` ฯลฯ | Mapping-based components — schema ใหญ่กว่ามาก ต้องมี Datastore Model ให้ผูก column และไม่ใช่สิ่งที่งานแบบนี้ใช้ |
