# Test data — CDR `ss_esim` (landing → discovery)

สร้างด้วย `node module\blendata\ss_esim\testdata\gen_esim_testdata.js [outDir]` — แก้ค่าที่บล็อก `CFG` หัวไฟล์แล้วรันใหม่ได้

## ค่าที่ใช้ (ยืนยันจาก dev DB จริงเมื่อ 2026-08-27 — connection ดูที่ `env-dev.md` ที่ root)

| ใช้ทำ | partner | owner | sim_type | b_no | ผล |
|---|---|---|---|---|---|
| MAP | `ECP` | `AWN` | `SalesT` | `ECP_ESIM_SalesT` | active, effective 2025-01-16, ไม่มีวันหมด |
| UNMAP (ไม่เจอ mapping) | `ECP` | `AWN` | `Step` | `ECP_ESIM_Step` | เคยใช้จริง แต่ถูกถอดออกจาก master แล้ว |
| UNMAP (owner ผิด) | `ECP` | `3BB` | `SalesT` | `ECP_ESIM_SalesT` | mapping เป็นของ `AWN` |
| UNMAP (ก่อน effective) | `ECP` | `AWN` | `SalesT` | `ECP_ESIM_SalesT` | `first_installed` = 2024-01-01 |
| UNMAP (หมดอายุ) | `ECP` | `AWN` | `Sales_Gable` | `ECP_ESIM_Sales_Gable` | expired 2025-12-31 |

`profile_type` = `Production`, iccid 11 หลัก, eid 9 หลัก — ตามรูปทรงข้อมูลจริงใน
`dss_transaction.tb_transaction_ss_esim_valid`

`tb_master_cdr_type` มี `cdr_type='1'` / `record_status='A'` แถวเดียว → inner join ใน `040000` ปลอดภัย

## ฝั่ง SQL Server — `sqlserver_mapping_seed.sql`

> ## ⛔ Claude ห้ามรันไฟล์นี้เด็ดขาด — **คนต้องรันเอง**
>
> กฎของโปรเจกต์ (2026-08-27): **ฐานข้อมูลเป็น read-only `SELECT` เท่านั้น ทุก env ไม่มีข้อยกเว้น**
> ไฟล์นี้มี `CREATE SCHEMA` / `CREATE TABLE` / `DROP`+`CREATE VIEW` / `INSERT` ⇒ อยู่นอกขอบเขตที่ Claude ทำได้
>
> **ส่วนที่ 3 อันตรายที่สุด** — `vw_service_mapping_bno_key` เป็น view ตัวจริงที่ทีมอื่นใช้อยู่
> **ต้องขออนุญาตเจ้าของ `dss_master.*` ก่อนรัน** (ดู `PLAYBOOK.md` §9 Ownership) และต้องยืนยันว่ารันที่ env ไหน
>
> Claude ทำได้แค่: ตรวจ syntax (`SET PARSEONLY ON`) · อธิบายว่าคำสั่งไหนเปลี่ยนอะไร · ส่งสคริปต์ให้ · รอผลกลับมาแล้ว `SELECT` ตรวจ
>
> **สถานะ:** ยังไม่เคยรันจริง — ผ่านแค่ syntax check 18/18 batch

Script สร้างตาราง + view + insert ข้อมูล mapping ที่ชุดเทสต้องใช้ (DDL และค่าทั้งหมดดึงจาก dev จริง)

| ส่วน | เนื้อหา |
|---|---|
| 1 | `CREATE SCHEMA dss_master` (ถ้ายังไม่มี) |
| 2 | `CREATE TABLE` × 3 — `tb_master_cdr_type` (5 col), `tb_service_profile` (63 col), `tb_service_bno_key` (10 col) พร้อม IDENTITY + PK ตามของจริง |
| 3 | `CREATE VIEW vw_service_mapping_bno_key` — คัดลอกจาก `OBJECT_DEFINITION` ของจริง |
| 4 | `INSERT` — cdr_type 1 แถว, profile 10 แถว, bno_key 11 แถว (ใช้ `SET IDENTITY_INSERT` คง runno เดิม) |
| 5 | `VERIFY` 6 query — ตรวจว่า seed ถูกต้องครบทุกเคส |
| 6 | `ROLLBACK` (คอมเมนต์ไว้) — ลบเฉพาะแถวที่ script นี้ใส่ |

**idempotent** — ทุก INSERT ใช้ `WHERE NOT EXISTS` รันซ้ำได้ ไม่ทับแถวเดิม
ตรวจ syntax แล้วด้วย `SET PARSEONLY ON` ครบ 18 batch ผ่านทั้งหมด

view กรอง 4 เงื่อนไข แถวจะโผล่ต้องผ่านครบ:
`profile.record_status='A'` + `profile.wf_status='AP'` + `profile.service_mkt_type='BNO'` + `bno_key.record_status='A'` + join ติดด้วย `service_profile_runno`

ผลหลังรัน: `b_no LIKE '%_ESIM_%'` ใน view = **8 แถว** บวก negative control อีก 3 แถวที่ต้อง **ตกจาก view**

| b_no | เหตุผลที่ตกจาก view |
|---|---|
| `ECP_ESIM_Service` | `bno_key.record_status='D'` |
| `ECP_ESIM_SalesSAP` | `profile.service_mkt_type='USC'` |
| `ECP_ESIM_Step2` | orphan — ไม่มีแถวใน `tb_service_profile` |

> ⚠️ **ห้ามเพิ่ม `ECP_ESIM_Step`** — ตั้งใจให้ไม่มี เพื่อให้เคส UNMAP U01–U03 ทำงาน

## ไฟล์ข้อมูลเทส

| ไฟล์ | บรรทัด | เข้า stream | `file_date` | ใช้ทำ |
|---|--:|:--:|---|---|
| `PGZ_ESIM_INVENTORY1_20260827_100000_1.txt` | 50 | ✅ | `20260827100000` | MAP 10 / UNMAP 10 / MAN 10 / TYP 10 + 10 บรรทัดที่ต้องถูก drop |
| `PGZ_ESIM_INVENTORY1_20260827_101000_2.txt` | 10 | ✅ | `20260827101000` | DUP in-batch 10 (ICCID ซ้ำกับ M01–M10) |
| `PGZ_ESIM_INVENTORY1_20260827_102000_3.txt` | 6 | ✅ | `20260827102000` | Gotcha 6 (ช่องโหว่ validation) |
| `PGZ_ESIM_INVENTORY1_20260827_110000_4.txt` | 10 | ✅ | `20260827110000` | RESEND → cross-run DUP 10 |
| `PGZ_ESIM_INVENTORY1_20260827_103000.txt` | 3 | ✅ | **NULL** | negative: ขาด `_<running>` |
| `ESIM_INVENTORY1_20260827_104000_5.txt` | 3 | ❌ | – | negative: prefix ผิด ตกตั้งแต่ glob |

`expected_results.csv` — 82 เคส พร้อม `expected_streamed` / `expected_status` / `target_table` / `raw_line` / `note`

## ลำดับการวางไฟล์

**รอบที่ 1** — วางพร้อมกัน 5 ไฟล์: `_1`, `_2`, `_3`, ไฟล์ไม่มี running, และไฟล์ prefix ผิด
(ไฟล์ `_2` ต้องเข้ารอบเดียวกับ `_1` ไม่งั้น DUP in-batch จะกลายเป็น cross-run DUP แทน)

**รอบที่ 2** — วางไฟล์ `_4` (RESEND) หลัง workflow รอบแรกจบ

รอ ≥ 5 นาที (`triggerIntervalTime: 300` + หน่วง 5 นาทีของ `020000`) แล้วรอ workflow รอบ `30 * * * *`

## ผลที่คาดหวัง

| ตาราง | เงื่อนไข | จำนวน (รอบ 1) |
|---|---|--:|
| `tb_transaction_ss_esim_valid` | `status='MAP'` | 17 |
| `tb_transaction_ss_esim_temp` | `status='UNMAP'` | 12 |
| `tb_transaction_ss_esim_reject` | `status IN ('MAN','TYP','DUP')` | 30 |

รอบ 2 เพิ่ม 10 แถวใน `reject` (`status='DUP'`)

ไฟล์ prefix ผิด (3 แถว) ต้อง **ไม่โผล่ที่ไหนเลย** และไฟล์ยังต้องค้างอยู่ในโฟลเดอร์ `imports/ss_esim`
(`cleanSource` ไม่แตะไฟล์ที่ไม่แมตช์ pattern → ต้องลบเอง)

## Gotcha ที่ตั้งใจใส่ไว้ (คาดว่า "ผ่าน" ทั้งที่ไม่ควร)

| เคส | เนื้อหา | ผลจริง | ประเด็น |
|---|---|---|---|
| G01 | `eid` ว่าง | MAP | `eid` ไม่อยู่ใน mandatory list |
| G02 | 10 คอลัมน์ | MAP | คอลัมน์เกินถูกทิ้งเงียบ `number_of_cols=10` แต่ไม่มีใครเช็ค |
| G03 | `partner` = space | UNMAP | `nullif(x,'')` ไม่จับ space → ไม่เป็น MAN |
| G04 | `first_installed` 17 หลัก | MAP | `left(...,14)` ตัดส่วนเกินเงียบ ๆ |
| G05 | ICCID มี space ครอบ | MAP ซ้ำ | `chk_duplicate` ไม่ตรง → dedup หลุด |
| G06 | `partner` = `ecp` ตัวเล็ก | UNMAP | join กับ master เป็น case-sensitive |
| FN01–03 | ชื่อไฟล์ขาด `_<running>` | MAP, `file_date` NULL | `ORDER BY file_date` เป็น NULLS FIRST → ชนะ dedup เหนือไฟล์ที่ชื่อถูก |

## ข้อควรระวังตอนรันซ้ำ

เปลี่ยน `STAMP_*` ใน `CFG` ทุกครั้งที่เทสรอบใหม่ — `cleanSource: archive` ย้ายไฟล์ที่ประมวลผลแล้ว
ไป `viewfs://ClusterBDE/bdedatastore/zeus_stg/archive` โดยคงชื่อเดิม ถ้าชื่อซ้ำจะย้ายไม่สำเร็จ

ลบข้อมูลเทสออกได้ด้วย `WHERE cdr_filename LIKE '%\_20260827\_1%' ESCAPE '\'`
(ชื่อไฟล์เก็บเป็น full path ใน `cdr_filename` และไหลไปถึง MSSQL ด้วย)
