> **อ่านตอนไหน** — ออกแบบเทสต์ด้วย mock data และผลที่ควรได้จาก Spark SQL เดิม (หลัง import แล้วเท่านั้น)

# วิธีเทสต์: mock data + ผลลัพธ์ที่ถูกต้องจากงาน Blendata เดิม

> อ่านเฉพาะตอนที่`knowledge/reference/migration-rules.md`สั่ง หรือเมื่อจะทดสอบ package ที่ import เข้า ODI แล้ว
> **เอกสารนี้ไม่ใช่ขั้นบังคับของการแปลง** — เป็นวิธีพิสูจน์ว่า package ให้ผลเหมือนงานเดิม

---

## J0. เป้าหมายและหลักการ

เป้าหมายของการเทสต์นี้มีข้อเดียว: **ODI ต้องให้ผลเหมือนงาน Blendata เดิม** — จึงมีกฎที่ห้ามละเมิด

1. **ผลลัพธ์ที่คาดหวัง (expected) ต้องได้จากการรัน Spark SQL ต้นฉบับใน workflow JSON เท่านั้น**
   ห้ามคำนวณจาก Oracle SQL ที่แปลงแล้ว — ถ้าคำนวณจากของที่แปลง ผิดก็ผิดเหมือนกันทั้งคู่ แล้วเทสต์จะ "ผ่าน" โดยไม่พิสูจน์อะไร
2. **ข้อมูลตั้งต้น (seed) ต้องมีแหล่งเดียว** — CSV ชุดเดียวป้อนทั้งรอบอ้างอิง (Spark) และสคริปต์ mock ฝั่ง Oracle
   (`make_mock_sql.py`) ไม่มีการพิมพ์ข้อมูลซ้ำสองที่
3. **agent ไม่รัน DDL/DML กับฐานข้อมูลใดเลย** — สคริปต์ในชุดนี้อ่านไฟล์ CSV เขียนไฟล์ CSV/SQL เท่านั้น
   ผู้ใช้เป็นคนรัน SQL เองบน Oracle แล้ว export ผลมาเทียบ
4. **ห้ามแต่งตัวเลขเอง** — ตัวเลขใน J7 ทั้งหมดมาจากการรันจริงด้วย `spark_reference_run.py` บนข้อมูล esim

### สิ่งที่ชุดนี้ทำและไม่ทำ (ต้องรายงานตรงๆ ทุกครั้ง)

| ทำ | ไม่ทำ |
|---|---|
| รัน SQL ของทุก task ที่มี `aggregationConfig.sql` ตามลำดับ (level, taskName) บน PySpark local | ไม่จำลอง task ที่ไม่ใช่ SQL: `000000` recover, `080000` retention, `999999` export JDBC ไป SQL Server |
| จำลอง sink: Overwrite ไม่มี partition = แทนทั้งตาราง · Overwrite มี partition = ลบ partition นั้นแล้วใส่ใหม่ · Append = ต่อท้าย | ไม่จำลอง Delta/`keyColumns` merge (Append คือต่อท้ายล้วน) |
| dump ตารางทุกตัว **ก่อนและหลังทุก task** | ไม่ยืนยัน Spark config ของ Blendata จริง (ใช้ค่าใน config: `ansi=false`, `timeParserPolicy=CORRECTED` — **สมมติฐาน** ดู `knowledge/reference/oracle-checks-and-spark-config.md` S) |
| เทียบ CSV ผลอ้างอิง กับ CSV ที่ export จาก Oracle | ไม่รู้ว่า ODI จริงทำงานไหม — ต้องมีคนรัน package แล้วส่งผลมา |

**task ที่ไม่ได้จำลอง ต้องเทียบมือกับ Blendata จริง** (เช่น 999999 ส่งออกไป SQL Server จริงหรือไม่ ถูกกรองอย่างไร)
เทสต์ชุดนี้ไม่ได้พิสูจน์ส่วนนั้น

---

## J1. ภาพรวมขั้นตอน

```
  testdata ของงานนั้น (ไฟล์ดิบ)
        │  (1) adapter ต่องาน — สคริปต์เล็กๆ เขียนเอง (ตัวอย่าง: make_landing_seed.py)
        ▼
  seed/*.csv  ◄──────── แหล่งข้อมูลเดียว ────────┐
        │                                         │
        │ (2) spark_reference_run.py              │ (3) make_mock_sql.py
        │     รัน SQL ต้นฉบับ                     │     สร้าง INSERT สำหรับ Oracle
        ▼                                         ▼
  ref_out/  (ผลที่ถูกต้อง ทุก task)         mock_sql/  (คนรันบน Oracle)
        │                                         │
        │                          (4) คนรัน producer ตามลำดับ + export ผล
        │                                         ▼
        └────────────► (5) compare_tables.py ◄── oracle_export/*.csv
                               PASS / FAIL
```

เครื่องที่ต้องมี: Python 3, `pyspark` (`pip install pyspark`), Java runtime (สำหรับขั้น 2 เท่านั้น)
ขั้น 3 และ 5 ใช้ Python มาตรฐานอย่างเดียว

---

### เลือกสคริปต์ตามสถานการณ์ (`scripts/testing/`)

| ลำดับ | สคริปต์ | ใช้เมื่อ | ได้อะไร |
|---|---|---|---|
| 1 | `run_d1.py` | ยังไม่รู้ Spark config ของ Blendata (ansi / timeParserPolicy / escapedStringLiterals) และอยากรู้ว่ากฎแปลงเสี่ยงไหม | รัน Spark SQL เดียวกันทุก config ใน matrix แล้วรายงานว่าผลของแต่ละ task คงที่ไหม (D1 → G5.M1) |
| 2 | `spark_reference_run.py` | ต้องการผลอ้างอิง "ค่าที่ควรได้" จาก Spark SQL ต้นฉบับ บน seed ที่กำหนด | CSV ผลของทุกตารางก่อน/หลังทุก task (config เดียว) |
| 3 | `compare_tables.py` | ตอนพัฒนา: เทียบตารางที่ ODI สร้างกับผลอ้างอิงข้อ 2 แบบเร็ว ไม่ต้องมี spec | PASS / FAIL + รายการแถวหรือคอลัมน์ที่ต่าง |
| 4 | `compare_results.py` (ผ่าน `/compare-d2`) | ตัดสินปิด gate: เทียบ valid/reject ของ Blendata กับ Oracle ระดับแถว (D2 seed / D3 backtest) | `D2_REPORT.md` + `D2_DIFF.csv` · ต้องมี spec และ Q ที่ปิดแล้วรองรับก่อนยอมรับส่วนต่าง (G5.M2) |

เสริม: `make_mock_sql.py` ใช้ก่อนขั้น 3 — แปลง seed CSV ชุดเดียวกับขั้น 2 เป็นสคริปต์ INSERT สำหรับ Oracle

## J2. ขั้น 1 — เตรียม seed จาก testdata (adapter ต่องาน)

landing table ของแต่ละงานมี layout ต่างกัน จึง**ต้องเขียน adapter เล็กๆ ต่องาน** (ในชุดนี้มีตัวอย่าง esim:
`references/example/mock-test/make_landing_seed.py`)

### รูปแบบ seed CSV (บังคับ)

| กรณี | เขียนใน CSV | ผลใน Spark | ผลใน Oracle |
|---|---|---|---|
| ค่า NULL | `\N` (เปลี่ยนได้ที่ `null_token`) | NULL | NULL |
| สตริงว่าง | ช่องว่างเปล่า (`,,`) | สตริงว่าง `''` | **NULL** (Oracle เก็บ `''` เป็น NULL) |
| ค่ามีช่องว่างหน้า/หลัง | เขียนตามจริง `" 26081000001 "` | คงช่องว่าง | คงช่องว่าง |
| boolean | `true` / `false` | boolean | `1` / `0` |
| timestamp | `YYYY-MM-DD HH24:MI:SS` | timestamp | `TIMESTAMP '...'` |

> ⚠️ ตัวอ่าน CSV ของ Spark เองจะเปลี่ยนช่องว่างเปล่าเป็น NULL — สคริปต์จึงอ่านด้วย Python `csv`
> แล้วแปลงชนิดตาม DDL เอง เพื่อให้ `''` ยังเป็น `''` ใน Spark ตรงกับต้นฉบับ

### หลักการออกแบบข้อมูลเทสต์ (ใช้กับทุกงาน)

- ต้องมี **แถวที่ผ่าน** ครบทุกเส้นทาง (ถึง valid / ถึง temp ฯลฯ)
- ต้องมี **แถวที่ตกทุกเงื่อนไขที่ SQL ตรวจ** อย่างน้อยเงื่อนไขละ 1 แถว (NULL ของแต่ละคอลัมน์, รูปแบบวันที่ผิด, ซ้ำ, ไม่พบใน mapping, mapping หมดอายุ ฯลฯ)
- ต้องมี **แถวขอบ**: ช่องว่างหน้า/หลังค่า, สตริงว่าง, แถวที่ขาดคอลัมน์ท้าย, วันที่ผิดรูป
- ต้องมี **รอบที่ 2** (ส่งไฟล์เดิมซ้ำ) เพื่อพิสูจน์ checkpoint / การตัดแถวซ้ำข้ามรอบ
- เก็บ **expected_results.csv ของ testdata** (ถ้ามี) ไว้เทียบกับ ref_out ด้วย — ถ้าสองอันนี้ไม่ตรงกัน แปลว่า adapter หรือข้อมูลผิด

---

## J3. ขั้น 2 — รันงานเดิมเพื่อได้ผลอ้างอิง

เตรียม `test-config.json` (ดู `references/example/mock-test/test-config.example.json`):

| คีย์ | ความหมาย |
|---|---|
| `spark.ansi` / `timeParserPolicy` / `timeZone` | ค่า Spark — **ต้องตรงกับ Blendata จริง** ถ้าไม่รู้ให้ถามผู้ใช้ที่ขั้น S แล้วบันทึกเป็น "สมมติฐาน" |
| `udfs` | UDF ที่ SQL เรียกโดยไม่มี argument เช่น `get_user` → ค่าที่ Blendata คืน |
| `tables.<ชื่อ>.ddl` | คอลัมน์ + ชนิดแบบ Spark ของตารางที่ SQL อ่าน/เขียน (ทุกตัว) |
| `tables.<ชื่อ>.seed` | ไฟล์ CSV เริ่มต้น หรือ `null` = ตารางว่าง |
| `tables.<ชื่อ>.oracle_columns` | (ถ้าตาราง Oracle มีคอลัมน์น้อยกว่า seed) รายชื่อคอลัมน์ที่จะ INSERT |
| `skip_tasks` | prefix ของ task ที่ไม่รัน (recover/retention/export) |
| `rounds` | รอบการรัน — แต่ละรอบ append ข้อมูลเพิ่ม (ถ้ามี) แล้วรัน DAG หนึ่งครั้ง |

```bash
python3 -I scripts/testing/spark_reference_run.py \
    --workflow <export_workflow.json> --config test-config.json --out ref_out
```

ผลลัพธ์ใน `ref_out/`:

```
ref_out/<round>/00_before/<table>.csv        สถานะทุกตารางก่อนรัน DAG
ref_out/<round>/NN_<task6หลัก>/<table>.csv   สถานะทุกตารางหลังแต่ละ task
ref_out/<round>/99_final_<table>.csv         สถานะสุดท้าย (ใช้เทียบ)
ref_out/<round>/run-log.json                 task ไหนรัน/ข้าม/error
ref_out/<round>/SUMMARY.md                   จำนวนแถวต่อตารางต่อ task
```

### กฎที่ทำให้ผลอ้างอิงเชื่อถือได้

- **`now()` เป็นเวลาจริงของเครื่องที่รัน** — คอลัมน์ที่มาจากเวลา (`process_date`, `cdr_id` ที่ฝังเวลา, `workflow_process_date`,
  `filter_dtm` ถ้ามาจาก `now()`) จะไม่เท่ากันเสมอ → **ห้ามเทียบ ต้อง `--ignore`**
- **คอลัมน์ `partition_date` ของ checkpoint / raw_temp / reject = วันที่รัน** — รอบอ้างอิงกับรอบ ODI ต้องรันใน**วันปฏิทินเดียวกัน**
  ไม่เช่นนั้นตัวเลขต่างกัน (ตัวอย่างที่เคยเจอ: checkpoint 6 แถว แทนที่จะเป็น 4 และ raw_temp 69 แทน 59 เพราะรอบหนึ่งข้ามวัน)
  ถ้ารอบสองของ ODI จะรันคนละวัน ให้รันรอบอ้างอิงใหม่ในวันนั้น
- **ลำดับรัน = (level, taskName)** — task ระดับเดียวกันใน Blendata รัน**ขนาน** ถ้ามีสอง task ระดับเดียวกันอ่าน/เขียนตารางเดียวกัน
  ผลอาจขึ้นกับจังหวะ → ต้องแจ้งผู้ใช้ ไม่ใช่เลือกลำดับเอาเอง

---

## J4. ขั้น 3 — สร้างสคริปต์ mock สำหรับ Oracle

```bash
python3 scripts/testing/make_mock_sql.py --config test-config.json --schema <SCHEMA_ที่ใช้เทสต์> --out mock_sql \
    [--rows-per-insert 50] [--table-map map.json]
```

ได้ไฟล์ (ผู้ใช้รันตามลำดับเลขบน Oracle เอง แล้ว COMMIT):

| ไฟล์ | ทำอะไร |
|---|---|
| `00_reset.sql` | `TRUNCATE` ทุกตารางในชุดเทสต์ — **รันเฉพาะใน schema เทสต์ที่ยืนยันแล้ว** ตรวจชื่อ schema ซ้ำก่อนกด |
| `NN_seed_<table>.sql` | INSERT ข้อมูลเริ่มต้นของตาราง |
| `NN_<round>_<table>.sql` | INSERT ข้อมูลที่เพิ่มก่อนรอบนั้น (เช่นส่งไฟล์ซ้ำ) |
| `99_check_counts.sql` | SELECT นับแถวทุกตารางเทียบกับ expected — **รันก่อนรัน producer** ถ้าไม่ตรง = mock โหลดไม่ครบ |

กฎที่สคริปต์ใช้ (ได้จากบทเรียนใน J8): รายชื่อคอลัมน์ชัดเจนทุก INSERT · ใช้ `INSERT ... SELECT ... FROM dual UNION ALL` ไม่ใช้ CTE ·
เตือนถ้าชื่อคอลัมน์เป็นคำสงวนของ Oracle · `''` → NULL · ข้อความทั้งหมดอยู่ใน ISO-8859-1 (ถ้ามีอักขระนอกชุด สคริปต์ปฏิเสธ)

> ⚠️ **ตารางที่ไม่รู้ DDL จริง** (เช่น landing ที่ไม่มี DDL, ตาราง/วิว `ext_*` ที่เป็น view/synonym) —
> ก่อนรัน mock ให้รัน `SELECT column_name, data_type FROM all_tab_columns WHERE table_name = '...'` (query เดียวกับ I3 — `knowledge/reference/oracle-checks-and-spark-config.md` I2)
> แล้วใช้ `oracle_columns` ให้ตรงกับของจริง ห้ามเดาคอลัมน์ ถ้าเดาผิด จะ ORA-00904 ตั้งแต่ INSERT แรก

---

## J5. ขั้น 4 — รัน producer และเก็บผล (รูปแบบ "ก่อน / รัน / หลัง" ต่อ producer)

ทำเป็นตารางต่อ producer (ลำดับเดียวกับ DAG ต้นฉบับ: 000000 → 999999) — สร้างอัตโนมัติจาก `ref_out/<round>/SUMMARY.md`
และ `NN_<task>/` ได้ ไม่ต้องคำนวณมือ

**รูปแบบสำหรับแต่ละ producer**

```
Producer <n>: <taskName>
  อ่านจาก : <ตารางต้นทาง + เงื่อนไขกรอง>
  เขียนไป : <ตารางปลายทาง + โหมด (TRUNCATE+INSERT / DELETE partition+INSERT / INSERT)>
  ก่อนรัน : <ตาราง: จำนวนแถว>   (จาก ref_out/<round>/<NN-1>_.../ )
  รัน     : <ชื่อ ODI procedure/scenario>
  หลังรัน : <ตาราง: จำนวนแถว + ตัวอย่างค่าสำคัญ>   (จาก ref_out/<round>/NN_<task>/ )
  ตรวจ    : SELECT ที่ผู้ใช้รัน + ผลที่ควรได้
  หมายเหตุ: เงื่อนไขที่ต้องระวัง (วันที่, ช่องว่าง, mapping หมดอายุ ฯลฯ)
```

ลำดับปฏิบัติการสำหรับคนรัน:

1. `00_reset.sql` → mock `01..` → `99_check_counts.sql` (ต้องตรง expected ทุกบรรทัด)
2. รัน producer ทีละตัวตามลำดับ **แล้วหยุดตรวจ SELECT นับแถวทุกตารางหลังแต่ละตัว** เทียบ `SUMMARY.md` — เจอตัวแรกที่เพี้ยนให้หยุด
   ไม่ต้องรันต่อ (ตัวหลังเพี้ยนตามอยู่แล้ว)
3. จบรอบ → export ตารางผลลัพธ์เป็น CSV (header เป็นชื่อคอลัมน์, ตัวคั่น `,`, quote ด้วย `"`) ใส่ `oracle_export/<round>/<table>.csv`
4. ถ้ามีรอบ 2 (`round2_*`): รัน mock ของรอบ 2 แล้วรัน producer ทั้ง DAG อีกครั้ง **ในวันเดียวกับรอบ 1** (ดู J3) แล้ว export อีกชุด

> task ที่เป็น placeholder ใน ODI (`SELECT 1 FROM DUAL` — 000000, 080000, 999999) ให้รันได้ แต่**ไม่มีผลที่ต้องเทียบ**

---

## J6. ขั้น 5 — เทียบผล

```bash
python3 scripts/testing/compare_tables.py \
   --ref ref_out/round1/99_final_<table>.csv \
   --actual oracle_export/round1/<table>.csv \
   --ignore <คอลัมน์ที่มาจากเวลา/ตัวนับ> [--key <คอลัมน์คีย์>]
```

PASS = exit 0 · FAIL = exit 1 พร้อมรายการแถวที่มีเฉพาะฝั่งใดฝั่งหนึ่ง (ไม่ใส่ `--key`) หรือรายการคอลัมน์ที่ต่างต่อคีย์ (ใส่ `--key`)

**แนะนำ:** เทียบสองแบบต่อตาราง — (ก) ไม่ใส่ `--key` เพื่อดูภาพรวม (ข) ใส่ `--key` เมื่อ FAIL เพื่อดูว่าคอลัมน์ไหนต่าง

### ค่าที่ normalize ให้ (ไม่นับเป็นความต่าง)

`NULL == ''` · `10000049.0 == 10000049` · timestamp เทียบถึงวินาที · `true/false == 1/0` · ลำดับแถว

### ค่าที่ **ไม่** normalize (เจอต่างเมื่อไรคือ finding จริง)

ช่องว่างหน้า/หลังค่า · ตัวพิมพ์เล็ก/ใหญ่ของข้อมูล · ความแม่นยำทศนิยม

### ความต่างที่ยอมรับได้ (ใส่ใน `--ignore` และเขียนเหตุผลลงรายงาน)

| คอลัมน์ | เหตุผล |
|---|---|
| `process_date`, `filter_dtm` (ถ้าได้จาก `now()`), `workflow_process_date`, `cdr_id` (ถ้าฝังเวลา) | เวลาจริงของการรันต่างกัน — แต่**ต้องตรวจรูปแบบ** (ความยาว/format) ด้วยตาด้วย SELECT |
| `create_by` | ค่าจาก UDF `get_user` — ODI อาจคืนค่าต่างจาก `blendata` (ต้องตกลงกับผู้ใช้ว่าค่าที่ถูกคืออะไร) |
| `partition_date` ที่มาจากวันที่รัน | ถ้ารันคนละวัน — แต่ควรรันวันเดียวกันแทนการ ignore |

ความต่างอื่นใดที่ไม่อยู่ในตารางนี้ **ต้องอธิบายด้วยหลักฐานก่อนจึงจะยอมรับได้** ห้ามใส่ `--ignore` เพื่อให้ PASS

---

## J7. ตัวอย่างจริง: งาน `ss_esim_landing_to_discovery` (ผลอ้างอิงจาก Spark SQL เดิม)

ข้อมูล: testdata esim 4 ไฟล์รอบ 1 (59 แถว body_tag `02`) + 1 ไฟล์รอบ 2 (10 แถว) · config: `ansi=false`, `timeParserPolicy=CORRECTED` (**สมมติฐาน ไม่ได้ยืนยันกับ Blendata**)

| ตาราง | รอบ 1 | รอบ 2 (ส่งซ้ำ) |
|---|---|---|
| `tb_staging_ss_esim_landing_to_discovery_workflow_status_temp` หลัง 010000 | 1 (SUCCESS=TRUE) | — |
| `tb_staging_ss_esim_checkpoint_temp` | 4 (1000/1010/1020/1030) | 2 |
| `tb_staging_ss_esim_raw_temp` | 59 = MAP 17 + DUP 10 + UNMAP 12 + TYP 10 + MAN 10 | 10 (ทั้งหมด DUP) |
| `tb_transaction_ss_esim_valid` | 17 (`partition_date` 20260827; แถวที่ first_installed ผิดรูปได้ `file_date` NULL) | 17 |
| `tb_transaction_ss_esim_reject` | 30 = DUP 10 + MAN 10 + TYP 10 | 40 |
| `tb_transaction_ss_esim_temp` | 12 (`partition_date` 20240101) | 12 |
| `tb_staging_ss_esim_checkpoint` | 4 | 2 |
| `..._workflow_status` ตอนจบ | (SUCCESS=TRUE, RUNNING=NULL, WORKFLOW_PROCESS_DATE=NULL) | — |

หมายเหตุสำคัญของข้อมูลชุดนี้ (ที่ต้องรู้ก่อนอ่านผล):

- iccid `' 26081000001 '` (กรณี G05) **มีช่องว่างจริงและ SQL เดิมไม่ trim** → ถูกจัดเป็น MAP ไม่ใช่ DUP ถ้า ODI ให้ผลต่าง (เช่นมี TRIM) คือความต่างจริง
- partner `' '` (กรณี G03) ไม่ถูก trim เช่นกัน
- mapping ที่หมดอายุ (`Sales_Gable` หมดอายุ 2025-12-31) ต้องไม่ถูกจับคู่ → UNMAP
- รอบ 2: ส่ง 10 แถวซ้ำ → ทั้งหมดเป็น DUP, valid ไม่เพิ่ม, reject เพิ่ม 10

ตัวเลขข้างบนมาจากการรัน `spark_reference_run.py` ซ้ำ ได้ผลตรงกับ harness รุ่นก่อนในตาราง raw_temp, valid, temp ทุกแถว และ reject
ตรงทุกแถวเมื่อไม่นับคอลัมน์ที่มาจากเวลา

---

## J8. บทเรียนจากการเทสต์จริง (ทำไมกฎข้างบนถึงเป็นแบบนี้)

| ที่เคยพลาด | ผล | กฎที่ได้ |
|---|---|---|
| mock SQL ใช้ชื่อ CTE/คอลัมน์ `raw` | ORA-00904 — `RAW` เป็นคำสงวน | `make_mock_sql.py` เตือนชื่อคำสงวน · ไม่ใช้ CTE |
| เดาคอลัมน์ของ landing (`raw_data`, `number_of_cols`, `partition_date`, `partition_hour`) ที่ไม่มีใน Oracle | INSERT ล้ม | ใช้เฉพาะคอลัมน์ที่ SQL อ่านจริง + ตรวจ `all_tab_columns` ก่อน (`oracle_columns`) |
| เชื่อว่า iccid G05 ถูก trim | expected ผิด | ผลต้องได้จากการรัน SQL เดิมเท่านั้น ห้ามเดาจากความคาดหวัง |
| Spark CSV reader เปลี่ยนช่องว่างเป็น NULL | b_no ของแถว partner ว่างเพี้ยน | อ่าน seed ด้วย Python `csv` แล้ว cast เอง |
| ตาราง `ext_dss_*` อาจเป็น view/synonym และไม่รู้ DDL | เสี่ยง INSERT ลงของที่ INSERT ไม่ได้ | ตรวจ `all_objects` ก่อน (`knowledge/reference/oracle-checks-and-spark-config.md`) ถ้าเป็น view ให้ผู้ใช้แจ้งว่าจะ mock อย่างไร |
| เปลี่ยนวันระหว่างสองรอบ | checkpoint 6 / raw_temp 69 แทน 4 / 59 | รันสองรอบในวันเดียวกัน |
| คำนวณ expected จาก Oracle SQL ที่แปลงเอง | ผู้ใช้ปฏิเสธถูกต้อง — เทสต์ไม่ได้พิสูจน์อะไร | J0 ข้อ 1 |

---

## J9. สิ่งที่ยังไม่ครอบคลุม (ต้องเขียนในรายงานส่งมอบทุกครั้ง)

1. `000000` / `080000` / `999999` ไม่ถูกจำลอง — พฤติกรรมเดิม (retention `olderThan=-1`, export JDBC ไป SQL Server append batch 10000
   พร้อมกรอง 7 วัน + checkpoint) ต้องเทียบมือกับ Blendata จริง
2. Spark config เป็นสมมติฐานจนกว่าผู้ใช้ยืนยัน (`knowledge/reference/oracle-checks-and-spark-config.md` S) — แถวขอบ (วันที่ผิดรูป, backslash, ข้ามเที่ยงคืน) ต้องเทียบกับ Blendata รายแถว
3. สคริปต์ชุดนี้**ยังไม่เคยรันกับ Oracle จริง** — SQL ที่ gen ผ่านการตรวจ syntax แบบ Oracle ด้วย `sqlglot` เท่านั้น
4. ยังไม่มีการยืนยัน import end-to-end ของ package ที่ build ด้วยชุดนี้ (ตามกฎโครงการ)
5. Delta/`keyColumns` merge ไม่ถูกจำลอง — ถ้า task ใดใช้ ต้องแจ้งก่อนแล้วใช้วิธีอื่น
6. ถ้า workflow มีหลาย task ระดับเดียวกันที่แตะตารางเดียวกัน ผลลำดับขนานไม่ถูกจำลอง

---

## J10. เช็กลิสต์ก่อนบอกว่า "เทสต์ผ่าน"

- [ ] ผลอ้างอิงมาจาก `spark_reference_run.py` บน SQL ต้นฉบับ (ไม่ใช่จาก Oracle ที่แปลง)
- [ ] seed ใช้ CSV ชุดเดียวกันทั้งรอบอ้างอิงและ mock Oracle
- [ ] `99_check_counts.sql` ตรง expected ก่อนรัน producer
- [ ] รันสองรอบในวันปฏิทินเดียวกัน
- [ ] เทียบครบทุกตารางผลลัพธ์ทุกรอบ ไม่ข้ามตารางที่ไม่เปลี่ยน
- [ ] ทุก `--ignore` มีเหตุผลเขียนไว้ และคอลัมน์ที่ถูก ignore ตรวจรูปแบบด้วยตาแล้ว
- [ ] แถวขอบ (ช่องว่าง, ว่าง, วันที่ผิดรูป) ถูกเทียบแล้วและไม่ถูก normalize หาย
- [ ] J9 ทุกข้อถูกเขียนในรายงานส่งมอบ
