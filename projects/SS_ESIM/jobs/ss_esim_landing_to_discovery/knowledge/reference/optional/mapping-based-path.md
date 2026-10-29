> **อ่านตอนไหน** — เมื่อผู้ใช้สั่งชัดเจนให้ใช้ Mapping แทน Procedure (ค่าเริ่มต้นคือ Procedure)

# เส้นทาง Mapping-based

> **ไฟล์นี้คืออะไร** — วิธีส่งมอบงานเมื่อผู้ใช้เลือกให้ทำเป็น **ODI Mapping** แทน Procedure
> รวมแผนที่แนวคิด Blendata↔ODI, การเลือก Knowledge Module, โครงสร้าง Package/Load Plan,
> การ reverse-engineer Datastore และรูปแบบ build spec ที่ส่งให้คนไปสร้างใน GUI
> **อ่านตอนไหน** — เมื่อ I11 ตอบว่าเลือกเส้นทาง Mapping **หรือ ผสม** (I11 มี 3 ตัวเลือกเป็นทางการ
> ตั้งแต่ v5: Procedure / Mapping / ผสม — ดู`knowledge/reference/migration-rules.md`) เนื้อหาในไฟล์นี้ใช้ได้กับทั้งสองกรณี
> เพราะ F7 สอนวิธีตัดสินรายทาสก์อยู่แล้ว
>
> ⚠️ **ข้อจำกัดที่ต้องบอกผู้ใช้ก่อนเสมอ** — **ทาสก์ที่ทำเป็น Mapping** ไม่ได้ไฟล์ที่ import
> แล้วรันได้ ได้แค่ *สเปก* ให้คนไปสร้าง Mapping ใน ODI Studio เหตุผลอยู่ใน F1 (ทาสก์ที่ทำเป็น
> Procedure ในเส้นทางผสมยังได้ zip import รันได้ตามปกติ)

---

## F1. ทำไมเส้นทางนี้ถึงไม่ generate ไฟล์ให้

ไม่ใช่เพราะขี้เกียจ แต่เพราะหลักฐานบอกว่าอย่าทำ

1. **ไม่มีใครเคย generate Mapping XML ที่ import ผ่าน** — ความพยายามครั้งหนึ่งใช้เวลาหลาย
   สัปดาห์กับ `SnpMapComp` / `SnpMapCp` / `SnpMapAttr` และจบที่ `NullPointerException`
   ใน Studio ที่ EXPRESSION component เพราะรูปร่างของ `MapAttr` ผิด
   (`knowledge/reference/delivery-checklist.md` ข้อ 10)
2. **Mapping ต้องมี Datastore Model ให้ผูก column** — ทุกคอลัมน์ของทุกตารางต้องมีอยู่ใน
   repository ก่อน ซึ่งเป็นงานที่ทำใน Studio (reverse-engineer) ไม่ใช่งานที่เขียน XML ได้
3. **โครง Source→Transform→Target ของ Mapping ไม่ใช่ข้อความ SQL** — มันคือกราฟของ
   component ที่ต่อกัน วางลงไปเป็นข้อความไม่ได้

**สิ่งที่ copy-paste ได้จริง** คือเนื้อ expression: ก้อน `CASE` / `NVL` / `ROUND`
ที่แปลงแล้ว วางลงช่อง Expression ของ component ได้ตรงๆ — ODI รับ SQL ของ
technology ปลายทางในช่องนั้น
**สิ่งที่ copy-paste ไม่ได้** คือส่วน `FROM` / `JOIN` ซึ่งกลายเป็นการเลือก datastore
และเงื่อนไข join ในหน้าจอ ไม่ใช่ข้อความ

---

## F2. แผนที่แนวคิด Blendata ↔ ODI

| Blendata | ODI |
|---|---|
| workflow หนึ่งชุด (เช่น landing-tasks, remap-tasks) | Package หนึ่งอัน หรือ Load Plan ถ้ามีหลายชุด |
| ไฟล์ `.sql` หนึ่งไฟล์ / ทาสก์หนึ่งตัว | Mapping หนึ่งอัน (หรือ Procedure ถ้า logic ไม่เข้ารูป Source→Target) |
| ลำดับรันที่ฝังในชื่อไฟล์ (`040000` → `050000` → …) | ลำดับ step ใน Package |
| `parentTask` ใน workflow JSON | ความสัมพันธ์ที่ต้องแปลงเป็นลำดับ step (ODI เป็นเส้นตรง — ดู I13) |
| connector ไปยัง source (MSSQL ฯลฯ) | Data Server + Physical Schema + Logical Schema ใน Topology |
| logic แปลงข้อมูล (`CASE`/`COALESCE`/`ROUND`) | Expression component ใน Mapping หรือ SQL ใน Procedure |
| metadata ของ workflow (`wf_*.json`) | ไม่มีของเทียบ — ใช้เป็นแหล่งความจริงเรื่องลำดับ dependency ตอนออกแบบ Package |
| ตารางเวลาที่ trigger workflow | Scenario + ODI Scheduler/Agent |
| `sinkOption.mode` = overwrite | IKM ที่ตั้ง truncate/replace หรือ Procedure ที่ `TRUNCATE` นำหน้า |
| `sinkOption.mode` = append | IKM แบบ append ล้วน |
| `sinkOption.mode` = upsert | IKM Incremental Update (ต้องกำหนด key ให้ถูก) |

---

## F3. เลือก Knowledge Module

KM คือสิ่งที่ตัดสินว่า ODI จะย้ายข้อมูลและเขียนลงปลายทาง **ยังไง** เลือกผิด = ช้ามาก
หรือผลลัพธ์ผิด

| สถานการณ์ | KM ที่แนะนำ |
|---|---|
| source กับ target อยู่ Oracle เดียวกัน | ไม่ต้องใช้ LKM (ODI ทำงานในฐานเดียว) + IKM Oracle Incremental Update หรือ IKM Oracle Insert |
| load จาก staging คนละ data server (เช่น MSSQL → Oracle) แบบเขียนทับทั้งตาราง | LKM SQL to Oracle + IKM Oracle Incremental Update (ตั้ง truncate) |
| มี filter incremental อยู่ใน SQL ต้นทางแล้ว | LKM เดิม และเก็บ filter ไว้เป็น Mapping filter — **ยังไม่ต้องใช้ ODI Journalizing** เว้นแต่ต้องการ CDC แบบใกล้เรียลไทม์ซึ่งเป็นความต้องการใหม่ |
| upsert ตาม business key | IKM Oracle Incremental Update + ตั้ง Update Key ให้ตรงกับ key จริง ไม่ใช่ primary key ที่ generate |
| logic หลาย statement ที่ไม่เข้ารูป Source→Target | **ใช้ Procedure ไม่ต้องฝืนทำเป็น Mapping** |

**ต้องถามผู้ใช้เสมอ** — ทีมมี KM ที่ customize ไว้เองหรือเปล่า ถ้ามี ให้ใช้ของทีม
อย่าเสนอ KM มาตรฐาน

---

## F4. โครงสร้าง Package และ Load Plan

ให้ mirror การแบ่ง stage ของ Blendata ไว้ เพื่อให้ตรวจสอบย้อนกลับได้

```
Package: PKG_<WORKFLOW>_LANDING
  └─ Mapping/Procedure ต่อหนึ่งไฟล์ของ landing stage เรียงตามลำดับเดิม

Package: PKG_<WORKFLOW>_REMAP
  └─ Mapping/Procedure ต่อหนึ่งไฟล์ของ remap stage เรียงตามลำดับเดิม

Load Plan: LP_<WORKFLOW>
  ├─ Step 1: PKG_<WORKFLOW>_LANDING
  └─ Step 2: PKG_<WORKFLOW>_REMAP
```

**Load Plan ให้อะไรที่ Package เดียวไม่ให้**

- **รันขนานได้จริง** — Load Plan มี serial/parallel step ส่วน Package เป็นเส้นตรงเสมอ
  ถ้า DAG เดิมมี fan-out ที่สำคัญต่อเวลารัน นี่คือเหตุผลเดียวที่ทำให้ Load Plan คุ้ม
- **restart จากจุดที่ล้มได้** ไม่ต้องเริ่มใหม่ทั้งหมด
- **exception handling แยกต่อ step**

**เมื่อไรไม่ต้องใช้ Load Plan** — งานที่มี stage เดียวหรือทุกอย่างต้องรันเรียงกันอยู่แล้ว
Package เดียวจบ อ่านง่ายกว่า

> ⚠️ ถ้าเลือก Load Plan ต้องบอกผู้ใช้ว่า **เอกสารชุดนี้ไม่มีความรู้เรื่องโครงสร้าง XML
> ของ Load Plan** (`SnpLoadPlan*`) — ยังไม่เคยตรวจจากไฟล์จริง ต้องสร้างใน Studio เท่านั้น

---

## F5. Reverse-engineer Datastore ก่อนเสมอ

Mapping ผูกกับ **Datastore** ไม่ใช่ชื่อตาราง ฉะนั้นก่อนสร้าง Mapping ได้ ต้องมี Model
ที่มีทุกตารางที่งานนี้แตะ

ขั้นตอนใน Studio:

1. Designer → Models → New Model — ตั้ง Technology = Oracle, Logical Schema = ตัวที่ใช้จริง
2. แท็บ Reverse Engineer → เลือก Standard → ใส่ mask ของชื่อตาราง (เช่น `TB_STAGING_%`)
3. กด Reverse Engineer แล้วตรวจว่าตารางมาครบ
4. **ตรวจชนิดและความกว้างของคอลัมน์** โดยเฉพาะคอลัมน์ที่ SQL ที่แปลงมาใช้
   `CAST(... AS VARCHAR2(4000))` — ความกว้างจริงมาจากที่นี่ ถ้าตารางแคบกว่าจะตัดข้อมูลเงียบ
5. ถ้าตารางปลายทางยังไม่มีในฐานข้อมูล **หยุด** — ต้องให้ DBA สร้างก่อน (คำถามข้อ 7 ใน `knowledge/reference/validation-and-cutover.md E4`)

**รายการที่ต้องเตรียมส่งให้คนทำขั้นนี้**

| ตาราง | เป็น source หรือ target | schema | มีอยู่จริงแล้วไหม | ใครสร้างถ้ายังไม่มี |
|---|---|---|---|---|
| `<ชื่อ>` | | | | |

ดึงรายชื่อตารางจาก SQL ทุกไฟล์: `INSERT INTO` / `MERGE INTO` / `TRUNCATE TABLE` /
`UPDATE` = target · `FROM` / `JOIN` = source

---

## F6. build spec ที่ส่งมอบ

ส่งเป็นตารางหนึ่งไฟล์ (CSV หรือ markdown) หนึ่งแถวต่อหนึ่ง Mapping/Procedure

| คอลัมน์ | ใส่อะไร |
|---|---|
| `order` | ลำดับรัน ตามที่ผู้ใช้ยืนยันใน I13 |
| `stage` | landing / remap / control — ตามการแบ่งของ Blendata |
| `object_name` | ชื่อ Mapping หรือ Procedure ที่จะสร้าง |
| `object_type` | `Mapping` หรือ `Procedure` (ดู F7 ว่าเลือกยังไง) |
| `source_datastore` | ตาราง source ทั้งหมด คั่นด้วย `;` |
| `target_datastore` | ตาราง target |
| `load_mode` | overwrite / append / upsert (มาจาก `sinkOption.mode`) |
| `update_key` | เฉพาะ upsert — คอลัมน์ที่ใช้เป็น key |
| `suggested_km` | ตาม F3 |
| `filter_expression` | เงื่อนไข `WHERE` ที่กลายเป็น Mapping filter |
| `join_condition` | เงื่อนไข join ระหว่าง source |
| `expression_sql` | เนื้อ expression ที่ copy-paste ได้ตรงๆ |
| `needs_human_review` | ใช่/ไม่ใช่ + เหตุผล — มาจากรายการ "ต้องให้คนตัดสิน" ใน `knowledge/reference/spark-to-oracle-sql.md` |
| `notes` | quirk ที่จงใจคงไว้ ข้อสมมติที่ยังไม่ยืนยัน |

**ส่งคู่กับ SQL ที่แปลงแล้วเสมอ** — spec บอกว่าจะสร้างอะไร SQL คือเนื้อของจริง
คนที่สร้างใน Studio ต้องเปิดดูทั้งสองอย่าง

---

## F7. Mapping หรือ Procedure — ตัดสินรายทาสก์

แม้เลือกเส้นทาง Mapping แล้ว **ไม่ใช่ทุกทาสก์ที่ควรเป็น Mapping**

| ทำเป็น Mapping เมื่อ | ทำเป็น Procedure เมื่อ |
|---|---|
| logic เข้ารูป source → transform → target ตรงๆ | มีหลาย statement ต่อกัน (`TRUNCATE` แล้ว `INSERT`) |
| ต้องการ lineage / impact analysis ใน Studio | มี correlated subquery หรือ window function หนักๆ |
| ทีมจะมาแก้ logic ผ่านหน้าจอในอนาคต | เป็น control task ที่แค่เขียนธง status |
| ตารางปลายทางมี Datastore แล้ว | logic ที่วาดเป็นกราฟแล้วอ่านยากกว่าเดิม |

**เกณฑ์ตัดสินง่ายๆ** — ถ้าวาดเป็น Mapping แล้วต้องยัด SQL ทั้งก้อนลงช่อง Expression
อยู่ดี แปลว่ามันควรเป็น Procedure ตั้งแต่แรก

---

## F8. สิ่งที่ต้องบอกผู้ใช้ตอนส่งมอบเส้นทางนี้

1. **ไม่มีไฟล์ zip ที่ import แล้วรันได้** — ส่ง spec + SQL ให้คนไปสร้างใน Studio
2. **ต้อง reverse-engineer Datastore ก่อน** ไม่งั้นสร้าง Mapping ไม่ได้เลย (F5)
3. **เวลาที่ใช้อยู่ที่คน** — ประมาณได้จากจำนวนแถวใน build spec คูณเวลาต่อ Mapping ของทีม
4. **ถ้าจุดประสงค์คือ "ได้ของที่รันได้เร็วที่สุด" เส้นทาง Procedure ตอบโจทย์กว่า**
   และย้ายมาเป็น Mapping ทีหลังได้ — ดูเกณฑ์ตัดสินใน`knowledge/reference/migration-rules.md`หัวข้อ 7
