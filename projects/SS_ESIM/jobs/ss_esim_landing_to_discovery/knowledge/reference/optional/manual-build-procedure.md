> **อ่านตอนไหน** — ต้องประกอบ SmartExport ด้วยมือ หรือไล่ทีละขั้นว่า generator ควรทำอะไร

# วิธีประกอบไฟล์ด้วยมือ ทีละขั้น

> **ไฟล์นี้คืออะไร** — ขั้นตอนสร้าง `SmartExport.xml` โดยไม่ต้องใช้เครื่องมืออะไรเลย
> นอกจากตัวแก้ไขข้อความ ใช้คู่กับ `knowledge/reference/odi-object-reference.md` (ตาราง field) และ `knowledge/reference/delivery-checklist.md` (checklist)
> **อ่านตอนไหน** — ขั้นที่ 3–5 ของ workflow หลังตอบคำถามครบ 17 ข้อแล้ว
>
> ⚠️ **อ่านก่อนเริ่ม** — การเขียน XML นี้ด้วยมือ **เคยพังในการ import จริงมาแล้ว 3 ครั้ง**
> สาเหตุทั้งสามอยู่ใน `C` ข้อ 1–3 ทุกขั้นในไฟล์นี้มีไว้กันข้อใดข้อหนึ่งในนั้น
> **ห้ามข้าม checklist ใน `C`** ถ้ารัน python ได้ ใช้ `scripts/` แทนจะปลอดภัยกว่ามาก

---

## ภาพรวม 10 ขั้น

| ขั้น | ทำอะไร | ได้อะไร |
|---|---|---|
| 1 | อ่านค่าที่ต้องใช้ออกจาก reference | ตารางค่าคงที่ของ repository นี้ |
| 2 | อ่านกฎ `SqlIndGrp` จาก reference | ตาราง คำสั่ง → ค่า |
| 3 | อ่านค่า flag ตามธรรมเนียมของ repository | ค่า default ของแต่ละ class |
| 4 | เทียบชุด field กับ`knowledge/reference/odi-object-reference.md` | รู้ว่า ODI ปลายทางตรงกับตารางไหม |
| 5 | จองเลข local id | แผนผังเลขที่ไม่ชนกัน |
| 6 | เขียน header + topology + project | ครึ่งแรกของไฟล์ |
| 7 | เขียน Variable และ Procedure | เนื้องานจริง |
| 8 | เขียน Step chain | สายโซ่การรัน |
| 9 | เขียน `SnpFKXRef` ทั้งหมด แล้วห่อ zip | ไฟล์ที่พร้อมตรวจ |
| 10 | เขียนแผนการสร้างเก็บไว้ข้างๆ zip | สร้างซ้ำครั้งหน้าไม่ต้องถาม 17 ข้อใหม่ |

---

## ขั้น 1 — อ่านค่าที่ต้องใช้ออกจาก reference

แตก zip ของ reference เอา `.xml` ออกมา แล้วหาค่าเหล่านี้ **ทุกค่าต้องมาจากไฟล์นี้
ห้ามใช้ค่าตัวอย่างจากเอกสาร**

**1.1 เลข `SnpOrigTxt` ทั้ง 3 slot**
ค้นหา `<Object class="com.sunopsis.dwg.dbobj.SnpOrigTxt">` จะเจอ 3 ก้อน แต่ละก้อนจดคู่
`SnpsTable` + `SnpsCol` + `ITxtOrig`

| slot | `SnpsTable` | `SnpsCol` | จด `ITxtOrig` ไว้ |
|---|---|---|---|
| refresh query ของ Variable | `SNP_VAR` | `I_TXT_VAR_IN` | ___ |
| ช่อง editor ของ Procedure | `SNP_TRT` | `I_TXT_TRT_TXT` | ___ |
| SQL ของบรรทัดคำสั่ง | `SNP_LINE_TRT` | `DEF_I_TXT` | ___ |

**ขาด slot ไหนแปลว่า reference ไม่มี Procedure หรือไม่มี Variable — หยุด กลับไป I2**

**1.2 header สองอัน** — คัดลอกทั้งบรรทัดของ `<Admin …/>` และ `<Encryption …/>` เก็บไว้
ตอนเขียนไฟล์ใหม่ให้วางกลับไปเหมือนเดิม **เปลี่ยนได้แค่ 2 ค่า**: `Created` (เวลาปัจจุบัน)
และ `exportKeySalt` (UUID ใหม่ 1 ตัว ใช้ค่าเดียวตลอดทั้งไฟล์)

**1.3 topology 7 ก้อน + descriptor 3 แถว** — คัดลอก `<Object>` ทั้งก้อนของ
`SnpConnect`, `SnpMtxt`, `SnpConnectProp`, `SnpContext`, `SnpLschema`, `SnpPschema`,
`SnpPschemaCont` **ทุก byte รวม `GlobalId` เดิม** แล้วหา `SnpReferencedObject` ที่ `GlobalId`
ตรงกับ `SnpContext` / `SnpLschema` / `SnpPschema` คัดลอกมาด้วย (3 แถว)

**1.4 `SnpFKXRef` ของ topology** — คัดลอกทุกแถวที่ `RefKey` ขึ้นต้นด้วย
`SNP_TECHNO.` `SNP_MTXT.` `SNP_CONNECT.` `SNP_CONTEXT.` `SNP_LSCHEMA.` `SNP_PSCHEMA.`

**1.5 ค่าผูกการรันของ `SnpLineTrt`** — เปิด `SnpLineTrt` ก้อนแรก จดค่าเหล่านี้

| field | ค่าใน reference |
|---|---|
| `DefContextCode` | ___ |
| `DefLschemaName` | ___ |
| `DefTechno` | ___ |
| `ColTechno` | ___ |
| `ExeChannel` | ___ |
| `MapTaskType` | ___ |
| `SqlName` | ___ |
| `LogLevDet` | ___ |
| `AlwaysExe` | ___ |
| `IndErr` | ___ |
| `IndLogFinalCmd` | ___ |

**1.6 `LschemaName` ของ Variable** — เปิด `SnpVar` ก้อนแรก จด `LschemaName`

**1.7 marker metadata** — คัดลอก `SnpGrpState` 3 ก้อน และ `SnpState2` 18 ก้อน **ทั้งก้อน**
เตรียมไว้ ตอนเขียนจะเปลี่ยนแค่ `GlobalId` (ใหม่ทุกก้อน) และ `IProject` (ของเรา)

**1.8 `FolderName`** — เปิด `SnpFolder` จด `FolderName` ไว้เป็น default ของ I7

---

## ขั้น 2 — อ่านกฎ `SqlIndGrp` จาก reference

ทำตาราง: เปิด `SnpTxtHeader` **ทุกก้อน** แล้วบันทึก 3 อย่าง — `ITxtOrig` (บอกว่าเป็น slot ไหน
จากขั้น 1.1), **คำแรกของ `Txt`** (ข้ามบรรทัดว่างและคอมเมนต์ `--` กับ `/* */` ไปก่อน),
และ `SqlIndGrp`

ได้ผลออกมาหน้าตาแบบนี้ (ตัวเลขเป็นของ reference ที่เคยตรวจ — **ของพี่อาจต่าง**)

| slot | คำสั่ง | ค่า | เห็นกี่ครั้ง |
|---|---|---|---|
| `linetrt_sql` | `INSERT` | 2 | 5 |
| `linetrt_sql` | `TRUNCATE` | 0 | 3 |
| `linetrt_sql` | `MERGE` | 2 | 1 |
| `trt_edit_cmd` | (ว่าง) | 0 | 6 |
| `var_query` | `SELECT` | 0 **และ** 2 | 2 + 2 |

**วิธีใช้ตารางนี้**

| ตารางบอกว่า | ทำยังไง |
|---|---|
| ค่าเดียว เห็น ≥ 2 ครั้ง | ใช้ได้เลย เป็นกฎ |
| ค่าเดียว เห็นครั้งเดียว | ใช้ได้ **ไม่ต้องถามผู้ใช้ที่ I2** ใส่ไว้ในรายงานส่งมอบว่ายังไม่ใช่กฎ |
| หลายค่า (เช่น `var_query` ข้างบน) | **หยุด ถามผู้ใช้** ว่าจะใช้ค่าไหน |
| ไม่มีคำสั่งนั้นเลย (`DELETE`, `WITH`, `BEGIN`) | **หยุด ถามผู้ใช้** ห้ามเดาจากคำสั่งอื่น |

**ห้ามคำนวณ `SqlIndGrp` จาก `OrdTrt`** — เหตุผลเต็มอยู่ใน A4 และ L17

 — ถ้าเจอว่า reference ไม่มีตัวอย่างของคำสั่งไหนเลย (`DELETE`, `UPDATE`, `SELECT`
แบบ standalone ที่พบว่าขาดบ่อย) **ห้ามขอไฟล์ตัวอย่างเพิ่มทีละชนิดคำสั่ง** — ให้ส่งสเปก 18 ข้อทั้งชุด
ในหัวข้อ 1 ของ `knowledge/reference/intake-questions.md` ให้ผู้ใช้ทำในรอบเดียว เพราะสเปกนั้นถูก
ออกแบบให้ครอบคลุมทุกชนิดคำสั่งที่เคยขาดมาแล้ว (`TRUNCATE`/`INSERT`/`UPDATE`/`DELETE`/`MERGE`/
`SELECT` standalone) — กันไม่ให้ต้องย้อนขอไฟล์หลายรอบเหมือนที่เคยเกิดขึ้นจริง

---

## ขั้น 3 — อ่านค่า flag ตามธรรมเนียมของ repository

สำหรับแต่ละ class ข้างล่าง ให้ดู **ทุกก้อน** ของ class นั้นใน reference ถ้า field หนึ่ง
มีค่าเหมือนกันทุกก้อน นั่นคือธรรมเนียมของ repository นี้ — ใช้ค่านั้น

**ถ้า field นั้นเป็น `null` ทุกก้อน ก็ต้อง `null` เหมือนกัน นั่นคือคำตอบ ไม่ใช่ช่องว่าง**
(ในไฟล์จริงที่ตรวจ `SnpLineTrt.FirstUser` เป็น null ทุกแถว — เคยมีคนเผลอใส่ชื่อ user ลงไป)

| class | field ที่ต้องอ่าน |
|---|---|
| `SnpProject` / `SnpFolder` / `SnpPackage` | `FirstUser`, `LastUser` |
| `SnpVar` | `FirstUser`, `LastUser`, `IndStore`, `VarDatatype`, `VarType` |
| `SnpTrt` | `FirstUser`, `LastUser`, `CleanupOnError`, `IndGenerateLoad`, `IndIsHidden`, `IsConcurrent`, `KimMultiDserver`, `TrtType` |
| `SnpLineTrt` | `FirstUser`, `LastUser` (ที่เหลืออยู่ในขั้น 1.5 แล้ว) |
| `SnpTxtHeader` | `Enc` |
| `SnpStep` | `FirstUser`, `LastUser`, `IndLogMethod`, `KoExit`, `OkExitCode` |

**class ที่ reference ไม่มีเลย** → ไม่มีธรรมเนียมให้อ่าน ต้องบอกผู้ใช้ว่าใช้ค่าจากที่อื่น
และค่าไหนบ้าง — **ห้ามใส่เงียบๆ**

**ห้ามอ่านค่าเหล่านี้จาก reference** เพราะเป็นของ repository นั้นไม่ใช่ของเรา:
`GlobalId`, `IndChange`, `IntVersion`, `FirstDate`, `LastDate`, `VLastDate`, `IProject`,
`IFolder`, `IPackage`, `ITrt`, `IVar`, `IStep`, `ILineTrt`, `ITxt`, ชื่อทุกชนิด,
`OrdTrt`, `SqlIndGrp`, `Nno`, `PosX`, `PosY`, `OkExit`, `OkNextStep`, `VarOp`

---

## ขั้น 4 — เทียบชุด field กับ`knowledge/reference/odi-object-reference.md`

สำหรับแต่ละ class ที่จะสร้าง เปิดก้อนแรกใน reference แล้วไล่รายชื่อ field กับ `type=`
เทียบกับตารางใน **A7** ทีละตัว

- **ตรงกันหมด** → ใช้ตาราง A7 ได้เลย
- **ต่างกัน** (มี field เกิน/ขาด หรือ `type=` ไม่ตรง) → **ยึด reference เสมอ** แล้วบันทึกไว้
  ว่าต่างตรงไหน เพราะ ODI ปลายทางคนละ build

ขั้นนี้กันบั๊กที่โผล่ไกลจากจุดผิด (A3) — อย่าข้าม

---

## ขั้น 5 — จองเลข local id

local id เป็นเลขในไฟล์ ขอแค่**ไม่ซ้ำกันในชนิดเดียวกัน**และอ้างถึงกันถูกต้อง
ใช้แผนนี้ได้เลย (แต่ละชนิดนับแยกกัน เริ่มที่ 1)

| ชนิด | field | วิธีนับ |
|---|---|---|
| Project / Folder / Package | `IProject` / `IFolder` / `IPackage` | 1 ทั้งสามตัว |
| Variable | `IVar` | 1, 2, 3, … ตามลำดับที่ประกาศ |
| Procedure | `ITrt` | 1, 2, 3, … |
| บรรทัดคำสั่ง | `ILineTrt` | 1, 2, 3, … นับรวมทุก Procedure |
| ข้อความ | `ITxt` | 1, 2, 3, … นับรวมทุกก้อน |
| Step | `IStep` | 1, 2, 3, … ตามลำดับการรัน |

`GlobalId` ของ object ใหม่ทุกก้อน = UUID ตัวใหม่ **ไม่ซ้ำกันเลยสักตัว**
(ยกเว้น topology ที่ลอก GlobalId เดิม และ `SnpReferencedObject` ที่ใช้ GlobalId ของ
object ที่มันอธิบาย)

**ถ้าจะ import ทับของเดิมในอนาคต** ต้องจด GlobalId ชุดนี้เก็บไว้ในแผนการสร้าง
มิฉะนั้นครั้งหน้าจะได้ของซ้ำแทนการอัปเดต

---

## ขั้น 6 — เขียน header + topology + project

เรียงตามนี้

1. บรรทัด prolog: `<?xml version="1.0" encoding="ISO-8859-1"?>`
2. `<SunopsisExport>`
3. `<Admin …/>` จากขั้น 1.2 (เปลี่ยน `Created`)
4. `<Encryption …/>` จากขั้น 1.2 (เปลี่ยน `exportKeySalt`)
5. `<SmartExportList materializeShortcut="false">` แล้วปิด `</SmartExportList>` ทันที
6. **topology 7 ก้อน** จากขั้น 1.3 วางทั้งก้อนไม่แก้อะไร
7. **`SnpReferencedObject` 3 แถว** จากขั้น 1.3
8. **`SnpProject`** — `IProject=1`, `ProjectName` และ `ProjectCode` จาก I5/I6, `IndChange="I"`, `IntVersion=1`, `FirstDate`/`LastDate` = เวลาปัจจุบันรูปแบบ `YYYY-MM-DD HH:MM:SS.0`, `FirstUser`/`LastUser` จากขั้น 3, ที่เหลือ `null`
9. **`SnpFolder`** — `IFolder=1`, `IProject=1`, `FolderName` จาก I7
10. **`SnpPackage`** — `IPackage=1`, `IFolder=1`, `PackName` จาก I8
11. **`SnpGrpState` 3 ก้อน + `SnpState2` 18 ก้อน** จากขั้น 1.7 เปลี่ยน `GlobalId` เป็นตัวใหม่
    ทุกก้อน และ `IProject` เป็น 1 **ค่าอื่นห้ามแตะ**

---

## ขั้น 7 — เขียน Variable และ Procedure

### Variable (ทำซ้ำต่อ 1 ตัว)

```
SnpVar        IVar=<n>  IProject=1  ITxtVarIn=<itxt>  VarName=<ชื่อ>
              LschemaName=<จากขั้น 1.6>  IndChange="I"  IntVersion=1
              VarType/VarDatatype/IndStore/FirstUser/LastUser = จากขั้น 3
SnpReferencedObject   ← แถว Logical Schema จากขั้น 1.3 (1 แถว)
SnpTxtHeader  ITxt=<itxt>  ITxtOrig=<slot var_query>  SqlIndGrp=<ขั้น 2 หรือถามคน>
              Txt=<refresh query>  Enc=<จากขั้น 3>
```

**`SnpOrigTxt` ของ slot `var_query`** เขียนเพียงครั้งเดียวในไฟล์ วางตอนใช้ครั้งแรก

### Procedure (ทำซ้ำต่อ 1 ตัว)

```
SnpTxtHeader  ITxt=<a>  ITxtOrig=<slot trt_edit_cmd>  Txt=null   ← ช่อง editor ที่ไม่ใช้
SnpTrt        ITrt=<n>  IProject=1  IFolder=1  ITxtTrtTxt=<a>  TrtName=<ชื่อ>
              KmTechno/KmSrcTechno = DefTechno จากขั้น 1.5
              TrtType/CleanupOnError/... = จากขั้น 3
   ต่อ 1 บรรทัดคำสั่ง:
     SnpLineTrt  ILineTrt=<m>  ITrt=<n>  OrdTrt=<10, 20, 30 ตามตำแหน่ง>
                 DefITxt=<b>  ค่าผูกการรันทั้งหมดจากขั้น 1.5
     SnpReferencedObject   ← แถว Context  (1 แถว)
     SnpReferencedObject   ← แถว Logical Schema (1 แถว)
     SnpTxtHeader  ITxt=<b>  ITxtOrig=<slot linetrt_sql>
                   SqlIndGrp=<จากขั้น 2 ตามคำแรกของ SQL>  Txt=<SQL>
```

**กติกาที่ผิดบ่อย**

- `OrdTrt` **คือตำแหน่งบรรทัด** บรรทัดแรก = 10 เสมอ ไม่ว่าคำสั่งจะเป็นอะไร
  Procedure แบบ append ที่มีบรรทัดเดียว อยู่ที่ **10 ไม่ใช่ 20**
- `SqlIndGrp` มาจาก **ชนิดคำสั่ง** ตามตารางขั้น 2 ไม่ใช่จาก `OrdTrt`
- overwrite = 2 บรรทัด (`TRUNCATE` ที่ 10, `INSERT` ที่ 20)
  append / upsert = 1 บรรทัดที่ 10
- ชื่อ Procedure และชื่อ Variable **ห้ามซ้ำกันเอง** — Studio ไม่ยอมให้มีชื่อซ้ำใน folder เดียว
  และถ้าซ้ำ step จะผูกไปที่ตัวหลัง ตัวแรกกลายเป็นของที่เข้าไม่ถึง
- `SnpOrigTxt` ของ slot `trt_edit_cmd` และ `linetrt_sql` เขียนอย่างละครั้งเดียวในไฟล์

---

## ขั้น 8 — เขียน Step chain

หนึ่ง `SnpStep` ต่อหนึ่ง step เรียงตามลำดับที่ผู้ใช้ยืนยันใน I13

```
SnpStep  IStep=<k>  IPackage=1  Nno=<k-1>  StepName=<ชื่อ>
         StepType="T" → ITrt=<n>, IVar=null, VarOp=null
         StepType="V" → IVar=<n>, ITrt=null, VarOp="="
         OkNextStep=<IStep ตัวถัดไป  หรือ null ถ้าเป็นตัวสุดท้าย>
         OkExit="0" ถ้ามี OkNextStep · "1" เฉพาะตัวสุดท้าย
         KoExit / OkExitCode / IndLogMethod / FirstUser / LastUser = จากขั้น 3
         PosX / PosY = พิกัดไดอะแกรม (เว้นห่างกันประมาณ 130 แนวนอน 110 แนวตั้ง)
         IndChange="I"  IntVersion=1  FirstDate/LastDate = เวลาปัจจุบัน
```

**สามข้อที่ต้องเป็นจริงเสมอ**

1. มี step ที่ `OkNextStep=null` **เพียงตัวเดียว**
2. step นั้นและเฉพาะตัวนั้นมี `OkExit="1"` ที่เหลือ `"0"` ทั้งหมด
3. `OkNextStep` ทุกค่าชี้ไป `IStep` ที่มีอยู่จริงในไฟล์

ผิดข้อ 2 = ไดอะแกรมไม่มีลูกศรเชื่อมเลย (L14) — เป็นความพังจริงครั้งที่หนึ่ง

---

## ขั้น 9 — เขียน `SnpFKXRef` แล้วห่อ zip

วางท้ายไฟล์ทั้งหมด หนึ่งแถวต่อหนึ่ง object ที่ถูกอ้างถึง

| object | `RefKey` | `RefObjGlobalId` | FQName |
|---|---|---|---|
| topology ทุกตัว | จากขั้น 1.4 | ลอกมา | ลอกมา |
| Project | `SNP_PROJECT.1` | GlobalId ของ project | `[<project>]` |
| Folder | `SNP_FOLDER.1` | ของ folder | `[<project>, <folder>]` |
| Package | `SNP_PACKAGE.1` | ของ package | `[<project>, <folder>, <package>]` |
| Procedure | `SNP_TRT.<n>` | ของ procedure | `[<project>, <ชื่อ procedure>]` |
| Variable | `SNP_VAR.<n>` | ของ variable | `[<project>, <ชื่อ variable>]` |
| Step | `SNP_STEP.<k>` | ของ step | `[<project>, <folder>, <package>, <ชื่อ step>]` |
| `SnpGrpState` | `SNP_GRPSTATE.<IGrpState>` | GlobalId ใหม่ของก้อนนั้น | `[<project>, <GrpStateName>]` |
| `SnpTxtHeader` ทุกก้อน | `SNP_TXTHEADER.<ITxt>` | ของก้อนนั้น | null |
| `SnpOrigTxt` ทุก slot ที่ใช้ | `SNP_ORIGTXT.<ITxtOrig>` | **null** | null |

`SnpState2` **ไม่มีแถว** — ไฟล์จริง index เฉพาะ `SnpGrpState`

### วิธีสร้าง `RefObjFQName` กับ `RefObjFQNameLengths` ให้ถูก

เขียนชื่อเป็น **รายการ segment** ก่อน แล้วค่อยสร้างสองค่าจากรายการเดียวกัน

```
segments = ["ai_test_01", "First Folder", "ai_test_01", "050100_append_ss_esim_valid"]

RefObjFQName        = "ai_test_01.First Folder.ai_test_01.050100_append_ss_esim_valid"
RefObjFQNameLengths = "10.12.10.27"
                       │  │  │  └─ ความยาวของ segment ที่ 4
                       │  │  └──── ของ segment ที่ 3
                       │  └─────── ของ segment ที่ 2 (เว้นวรรคนับด้วย)
                       └────────── ของ segment ที่ 1
```

**ห้ามสร้าง lengths จากการ `split(".")` ของชื่อที่ต่อแล้ว** — ผิดทันทีที่ชื่อไหนมีจุดข้างใน

**ตรวจเองได้:** ผลรวมของตัวเลขใน lengths + (จำนวน segment − 1) = ความยาวของ FQName
ตัวอย่างข้างบน: 10+12+10+27 = 59, +3 = 62 = ความยาวของสตริง ✓

`RefObjFQType` ดูจากตารางใน **A5**

### ปิดไฟล์และห่อ zip

1. ปิดด้วย `</SunopsisExport>`
2. **บันทึกไฟล์เป็น ISO-8859-1** ไม่ใช่ UTF-8 — ถ้าตัวแก้ไขข้อความบันทึกเป็นอย่างอื่น
   ไฟล์จะไม่ตรงกับที่ prolog ประกาศไว้
3. ถ้าโปรแกรมเตือนว่ามีอักขระที่บันทึกเป็น ISO-8859-1 ไม่ได้ → **แก้ข้อความ อย่ายอมให้มัน
   escape ให้** `&#NNNN;` ไม่ถูกตีความข้างใน CDATA จะกลายเป็นข้อความดิบ (L20)
4. **ตรวจตาม checklist ใน `C` ให้ครบทุกข้อ**
5. ห่อเป็น zip ที่มีไฟล์เดียวชื่อ `SmartExport.xml` อยู่ที่ราก ไม่ต้องมีโฟลเดอร์ซ้อน

---

## ขั้น 10 (แนะนำ) — เขียนแผนการสร้างเก็บไว้

เก็บไฟล์ข้อความข้างๆ zip บันทึกสิ่งเหล่านี้ เพื่อให้ครั้งหน้าสร้างใหม่ได้โดยไม่ต้องถาม 17 ข้อซ้ำ

- path ของ reference ที่ใช้
- คำตอบทั้ง 17 ข้อ
- ตาราง `SqlIndGrp` จากขั้น 2 และค่าที่ผู้ใช้ตัดสินเอง
- ลำดับ step ที่ผู้ใช้ยืนยัน
- รายการทาสก์ที่ตัดออกพร้อมเหตุผล
- GlobalId ที่ใช้ (ถ้าตั้งใจจะ import ทับในอนาคต)
- **path ของไฟล์ DDL ที่ใช้ตอน I3** (ถ้ามี) — ครั้งหน้าจะได้ส่งเข้า `--ddl` ตัวเดิมได้ทันที
- **รายชื่อตารางที่ column list มาจากโหมดเดา**
  ถ้าไม่บันทึกตรงนี้ การสร้างซ้ำครั้งหน้าจะไม่มีทางรู้ว่าใบไหน "ตั้งใจเดา" ต่างจาก "ยังไม่ได้ส่ง DDL มา"
  ซึ่งเป็นสองสถานะที่ checklist ข้อ 35 บังคับให้แยกจากกัน
- **คำตอบเรื่อง partition ของทุกทาสก์ overwrite** — ใบไหนตกลงใช้
  `TRUNCATE` ทั้งตาราง ใบไหนใช้ `DELETE … WHERE <partition key>` ใบไหนใช้
  `TRUNCATE PARTITION` การสร้างซ้ำโดยไม่มีข้อมูลนี้จะกลับไปเป็น `TRUNCATE` ทั้งตาราง
  ตาม default แล้วลบข้อมูลย้อนหลังทิ้งเงียบๆ (`knowledge/lessons-learned.md` L29)

รูปแบบแผนการสร้าง (spec) แบบ JSON — ตัวอย่างเดิม spec.example.json ไม่รวมในโปรเจกต์นี้ — เป็นรูปแบบที่ใช้ได้จริง ถ้าเขียนตามนั้นจะสั่งสร้างซ้ำ
ด้วยสคริปต์ได้เลยในอนาคต
