> **อ่านตอนไหน** — ต้องอ่านโครงสร้าง workflow export JSON หรือตรวจทาสก์ที่ไม่มี SQL

# โครงสร้างจริงของ workflow export JSON

> **ไฟล์นี้คืออะไร** — field path จริงของ `export_workflow*.json` ที่ Blendata export ออกมา
> (ทาสก์, dependency, SQL, target table) อ่านตอน I1 (หาไฟล์ที่ถูกตัว) และ I12 (หาว่าทาสก์
> ไหนไม่มี SQL) จะได้ไม่ต้องไล่เปิดดูทีละทาสก์เอง
>
> **ระดับความเชื่อถือ** — ทั้งไฟล์นี้เป็น **[เห็นในไฟล์จริง]**: อ่านจากไฟล์ export จริงหนึ่งไฟล์
> (`ss_esim_landing_to_discovery`) ยังไม่มีไฟล์ export ที่สองมายืนยันว่า field ชื่อเดียวกันนี้
> คงที่ทุกเวอร์ชันของ Blendata **ห้ามเชื่อว่า field ทุกตัวต้องอยู่ครบเสมอ** — เช็คด้วยโค้ด
> ก่อนสรุป อย่าอนุมานจากไฟล์นี้เพียงไฟล์เดียว

---

## G1. โครงร่างระดับบนสุด

```
{
  "airflowExportModels": [
    {
      "workflowName": "<ชื่อ workflow — ใช้เป็น default ของ I5>",
      "airflowTags": [...],
      "versions": [
        {
          "taskDetailString": "<STRING ที่เป็น JSON ซ้อนอีกชั้น — ต้อง parse สองรอบ>"
        }
      ]
    }
  ],
  "failedModel": ...,
  "realmId": ...
}
```

⚠️ **จุดพลาดที่พบบ่อยที่สุด** — `taskDetailString` เป็น **string** ไม่ใช่ object ต้อง
`json.loads()` (หรือเทียบเท่าในภาษาอื่น) อีกรอบถึงจะได้ list ของทาสก์ ถ้า parse รอบเดียว
จะเห็นแค่ข้อความดิบและคิดว่าไฟล์เสีย

```python
import json
with open(path, encoding="utf-8") as f:
    data = json.load(f)
wf = data["airflowExportModels"][0]
tasks = json.loads(wf["versions"][0]["taskDetailString"])   # <- parse รอบที่สอง
```

---

## G2. โครงสร้างทาสก์หนึ่งตัว (ตัวอย่าง mock — ใช้ตาราง A/B/C แทนของจริง)

```json
{
  "taskName": "040000_overwrite_table_a",
  "taskId": "task_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "serviceTemplate": "service-job-aggregate",
  "description": "",
  "parentTask": ["task_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"],
  "level": 5,
  "retry": true,
  "retryRound": 2,
  "body": {
    "realmId": 3,
    "zeusId": 3,
    "aggregationConfig": {
      "dataType": "time series",
      "sinkOption": { "mode": "Overwrite", "partitions": [], "format": "parquet" },
      "tableName": "table_a",
      "serviceName": "job-aggregate",
      "sql": "SELECT col1, col2 FROM table_b JOIN table_c ON table_b.id = table_c.id"
    }
  }
}
```

**field ที่ต้องใช้จริง (ยืนยันจากไฟล์จริงแล้ว)**

| field | อยู่ตรงไหน | ใช้ทำอะไร |
|---|---|---|
| `taskName` | top-level ของแต่ละทาสก์ | ชื่อทาสก์ — ใช้ตั้งชื่อ Procedure/Mapping |
| `taskId` | top-level | id ภายใน ใช้จับคู่กับ `parentTask` ของทาสก์อื่น (ไม่ใช่ชื่อที่อ่านง่าย ต้อง map เป็น `taskName` เองก่อนแสดงให้ผู้ใช้ดู) |
| `serviceTemplate` | top-level | ใช้เดาว่าทาสก์นี้มี SQL หรือเป็น infra-only (ดู G3) |
| `parentTask` | top-level | **array** ของ `taskId` ต้นทาง — ใช้สร้าง dependency graph สำหรับ I13 (ถ้าเป็น `null`/ไม่มี key = ทาสก์ต้นทาง ไม่มี parent) |
| `level` | top-level | ลำดับชั้นที่ scheduler เดิมจัดไว้ — ใช้อ้างอิงตอนแสดงตาราง I13 เทียบ level เดิม/ใหม่ |
| `body.aggregationConfig.sql` | ซ้อนใน body | SQL ของทาสก์ประเภท aggregate — **นี่คือที่ SQL ส่วนใหญ่อยู่** |
| `body.sql` | อยู่ตรงๆ ใน body (ไม่ผ่าน aggregationConfig) | พบในทาสก์ประเภท export/ส่งออกไปปลายทางอื่น — ต้องเช็คทั้งสองที่ อย่าเช็คแค่ `aggregationConfig.sql` |
| `body.aggregationConfig.tableName` หรือ `body.tableName` | ซ้อนใน body | ชื่อตาราง **target** ของทาสก์นี้ |
| `body.aggregationConfig.sinkOption.mode` | ซ้อนใน body | `Overwrite` / `Append` / อื่นๆ — ป้อนเข้า I14 (overwrite/append/upsert) |
| `body.aggregationConfig.sinkOption.partitions` | ซ้อนใน body ข้างใน `sinkOption` | **array** ของคีย์ที่งานเดิมใช้แบ่ง partition — **ต้องอ่านทุกครั้งที่ `mode = Overwrite`** ⚠️ ใหม่ใน v10 |

⚠️ **`sinkOption.partitions` คือ field ที่กันข้อมูลหายถาวร — ห้ามข้าม**

`mode = Overwrite` เพียงอย่างเดียว **ไม่ได้แปลว่าเขียนทับทั้งตาราง** ถ้า `partitions`
ไม่ใช่ array ว่าง แปลว่างานเดิมเขียนทับเฉพาะ partition ที่ระบุ การแปลงเป็น
`TRUNCATE TABLE <ตาราง>` ตรงๆ ตาม house style จะลบข้อมูลของ partition อื่น**ทั้งหมด
อย่างถาวร โดยไม่มี error และไม่มีอะไรฟ้อง** — ต้องหยุดถามที่ I14
(`knowledge/lessons-learned.md` L29 · `delivery-checklist.md` ข้อ 41)

```python
def overwrite_scope(task):
    """คืน (mode, partitions) ของทาสก์หนึ่งตัว -- None ถ้าไม่มี sinkOption"""
    cfg = task.get("body", {}).get("aggregationConfig", {})
    sink = cfg.get("sinkOption") or task.get("body", {}).get("sinkOption")
    if not isinstance(sink, dict):
        return None
    return sink.get("mode"), sink.get("partitions") or []
```

**ถ้าไฟล์ไม่มี field `partitions` เลย** — ห้ามสรุปว่า "แปลว่าทั้งตาราง" ไฟล์ตัวอย่างที่เรา
เคยเห็นมีแค่หนึ่งไฟล์ (ดูป้ายความเชื่อถือด้านบน) ให้ถามผู้ใช้ตรงๆ ว่างานเดิมเขียนทับทั้งตาราง
หรือเฉพาะบางช่วง

**วิธีดึง SQL ให้ครบทุกทาสก์แบบไม่พลาด (recursive)** — อย่า assume ว่า `sql` อยู่ที่เดียว
เสมอ ให้ไล่หา key ชื่อ `sql` แบบ recursive ทั้ง object:

```python
def find_sql(obj):
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "sql" and isinstance(v, str) and v.strip():
                results.append(v)
            else:
                results.extend(find_sql(v))
    elif isinstance(obj, list):
        for v in obj:
            results.extend(find_sql(v))
    return results
```

**วิธีหาตาราง source/target แบบคร่าวๆ ก่อนถาม I1/I12 (ไม่แม่นยำ 100% — ใช้เป็นจุดเริ่มต้น
ให้ผู้ใช้ยืนยัน ไม่ใช่คำตอบสุดท้าย):**

- target ≈ `tableName` ของทาสก์นั้น
- source ≈ ชื่อตารางที่ตามหลัง `FROM` / `JOIN` ใน SQL ของทาสก์นั้น (regex คร่าวๆ พอ
  เพราะ subquery ซ้อนกันจะทำให้ปนกับ alias — ต้องให้ผู้ใช้ยืนยันอยู่ดี)

---

## G3. วิธีเดาว่าทาสก์ไหน "ไม่มี SQL" (สำหรับ I12)

**อย่าเชื่อ `serviceTemplate` เพียงอย่างเดียว — ใช้ประกอบกับการเช็คว่ามี SQL จริงไหม**

จากไฟล์จริงที่เจอ:

| `serviceTemplate` | มี SQL ไหม | ความหมาย |
|---|---|---|
| `service-job-aggregate` | มี (ใน `body.aggregationConfig.sql`) | ทาสก์ประมวลผลข้อมูลปกติ |
| `service-job-recover` | ไม่มี | recover ข้อมูลจากจุดที่ค้าง — infra ล้วน |
| `service-job-table-retention` | ไม่มี | ลบ/เก็บกวาดข้อมูลเก่าตามอายุ — infra ล้วน |

**ขั้นตอนที่แนะนำ** — สำหรับทุกทาสก์ ตรวจว่ามี `body.aggregationConfig.sql` หรือ `body.sql`
เป็น string ไม่ว่างไหม (ใช้ `find_sql()` ด้านบน) ถ้า**ไม่มีเลย** ให้จัดเป็นผู้สมัคร "ตัดออก
เพราะไม่มี SQL" แล้วเสนอ `serviceTemplate` ของมันประกอบเป็นหลักฐานให้ผู้ใช้ดูตอน I12
(อย่าตัดสินใจเงียบๆ โดยไม่แสดงหลักฐาน)

**ถ้าเจอ `serviceTemplate` ที่ไม่อยู่ในตารางนี้** — เช็คด้วยโค้ดว่ามี SQL จริงไหมเท่านั้น
อย่าเดาความหมายจากชื่อ

---

## G4. สิ่งที่ไฟล์นี้ยังไม่ครอบคลุม

- ยังไม่เห็น field ของทาสก์ประเภทอื่นที่ไม่ใช่ `service-job-aggregate` / `service-job-recover`
  / `service-job-table-retention` — ถ้าเจอ serviceTemplate ใหม่ ให้บันทึกโครงสร้างที่เจอเพิ่ม
  ในไฟล์นี้เพื่องานถัดไป
- ยังไม่เห็นตัวอย่างที่ `parentTask` มีมากกว่า 1 ค่า (fan-in) ในรูปแบบอื่นนอกจากที่เจอในงาน
  `ss_esim_landing_to_discovery` (ควรใช้ได้เหมือนกันเพราะเป็นแค่ array แต่ยังไม่เจอเคสซับซ้อนกว่านี้)
