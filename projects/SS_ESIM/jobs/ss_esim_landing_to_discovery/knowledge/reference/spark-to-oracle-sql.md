> **อ่านตอนไหน** — แปลง/รีวิว SQL Phase 2–4 (กฎ D-R1–D-R8, กลุ่ม mapping A) — ใช้คู่กับ skill `spark-oracle-dialect`

# แปลง Spark SQL → Oracle SQL

> **ไฟล์นี้คืออะไร** — กติกาแปลง Spark SQL เป็น Oracle SQL: ตารางแปลงที่ใช้ได้อัตโนมัติ,
> รายการที่ห้ามแปลเองต้องให้คนตัดสิน, house style และ checklist ก่อนรับ SQL ที่แปลงแล้ว
> **อ่านตอนไหน** — เฉพาะเมื่อ SQL ต้นทางยังเป็น Spark ดิบ (I10 ตอบว่ายังไม่แปลง)
> ถ้าแปลและเทสกับ Oracle มาแล้วข้ามไฟล์นี้ได้เลย

**ก่อนแปลง ให้แจกแจงงานต้นทางก่อนเสมอ** — อ่าน SQL และเอกสารออกแบบให้เข้าใจ business
logic, ตารางและ status code ที่เกี่ยวข้อง, dependency ภายนอก และจุดที่ยังคลุมเครือ
แล้วค่อยลงมือแปลง ไฟล์นี้เป็นคู่มือ**การแปลง** ไม่ใช่ตัววิเคราะห์ว่างานต้นทางทำอะไร

**เหตุผลที่ต้องจริงจัง** — SQL ที่แปลงผิดจะ import ผ่านเงียบๆ แล้วไปพังตอน runtime
หรือแย่กว่านั้นคือรันผ่านแต่ได้ตัวเลขผิด ตัวตรวจไฟล์ตรวจโครงสร้าง XML เท่านั้น
ไม่มีอะไรตรวจ SQL ให้

**ที่มาของข้อมูล** — กลุ่ม A มาจากงาน ss_esim ที่แปลงและรันจริงแล้ว (ยังคงเลข
`[C#]` ไว้ตามที่ฝังอยู่ในคอมเมนต์ของ SQL จริง) กลุ่ม B มาจากโปรเจกต์ migration
คู่ขนานบน repository เดียวกัน ซึ่งเจอเคสที่งาน esim ไม่มี — **กลุ่ม B ยังไม่ได้
ผ่านการยืนยันด้วยตาเราเอง** ให้เช็คกับข้อมูลจริงก่อนใช้ในงานสำคัญ

เก็บเลข `[C#]` ไว้ในคอมเมนต์ของ SQL ที่แปลงแล้วเสมอ — เป็นทางเดียวที่คนรีวิว
จะย้อนกลับไปหาโค้ด Spark ต้นฉบับได้

---

## กลุ่ม 0 — เหมือนกันอยู่แล้ว อย่าไปแตะ

การ "แปลง" สิ่งที่ไม่ต้องแปลงทำให้ diff โตโดยเปล่าประโยชน์ และทำให้คนรีวิวต้องอ่าน
บรรทัดที่ไม่มีอะไรเปลี่ยน

| Spark | สถานะใน Oracle |
|---|---|
| `SUBSTR(str, start, len)` | เหมือนกัน นับตำแหน่งเริ่มที่ 1 ทั้งคู่ |
| `ROUND(number, decimals)` | เหมือนกัน |
| `CASE WHEN … THEN … ELSE … END` | เหมือนกัน |
| `UPPER` / `LOWER` / `TRIM` | เหมือนกัน |
| `TO_CHAR(...)` ที่ใช้อยู่แล้ว | เหมือนกัน — แต่เช็คก่อนว่าต้นทางไม่ได้เขียนเป็น `CAST(... AS STRING)` |
| `COALESCE(a, b, c, …)` 3 argument ขึ้นไป | ใช้ได้ตรงๆ (ANSI) — แปลงเป็น `NVL` เฉพาะตอนมี 2 argument ตาม house style |
| `\|\|` ต่อสตริง | เหมือนกัน (แต่ระวังเรื่อง NULL — ดู L15) |

**การหารจำนวนเต็ม** — Spark ที่หารคอลัมน์ `INT` สองตัวอาจตัดเศษ ส่วน Oracle `NUMBER`
หารแล้วได้ทศนิยมอยู่แล้ว **ต้องดูชนิดจริงของคอลัมน์ก่อน** อย่าเติม `CAST` ป้องกันไว้ก่อน
เพราะจะเปลี่ยนผลลัพธ์ในทางกลับกัน

---

## กลุ่ม A — แปลงแล้วพิสูจน์กับงานจริง (ss_esim)

| # | Spark | Oracle | ทำไมสำคัญ |
|---|---|---|---|
| L14 | `concat(a, b, c)` | `a \|\| b \|\| c` | Oracle `CONCAT` รับได้แค่ 2 argument ส่วน `concat` argument เดียวให้ตัดทิ้ง |
| L15 | NULL propagation ของ `concat()` | `CASE WHEN a IS NULL OR b IS NULL THEN NULL ELSE a \|\| b END` | Spark คืน NULL ถ้ามี argument ไหนเป็น NULL แต่ `\|\|` ของ Oracle มอง NULL เป็นค่าว่าง — ต้องรักษา semantic เดิมทุกที่ที่ค่านั้นเป็น key ของ join หรือ filter |
| L16 | `format_string('%09d', n)` | `LPAD(TO_CHAR(n), 9, '0')` | Oracle ไม่มี printf |
| L18 | `row_number() over (order by 1)` | `ROW_NUMBER() OVER (ORDER BY NULL)` | Oracle ไม่รับเลขลำดับใน `ORDER BY` ของ analytic (`ORA-01785`) — แปลงเฉพาะที่อยู่ใน `OVER(...)` เท่านั้น นอก `OVER` เป็นไวยากรณ์ที่ถูกต้องอยู่แล้ว |
| L17 | `reverse(split(path,'/'))[0]` | `REGEXP_SUBSTR(path, '[^/]+$')` | เอา segment สุดท้ายของ path |
| L17 | `regexp_extract(s, pattern, 3)` | `REGEXP_SUBSTR(s, pattern, 1, 1, NULL, 3)` | argument ของ Oracle คือ position/occurrence/match-param/group |
| L17 | `x = ''` / `x <> ''` | `x IS NULL` / `x IS NOT NULL` | Oracle เก็บ `''` เป็น NULL การเทียบกับ `''` จึงเป็นเท็จ/จริงเสมอ ไม่ขึ้นกับค่า — **เป็นบั๊กความถูกต้องเงียบๆ ไม่ใช่เรื่องสไตล์** เจอตอน audit `040000` ของ esim ซึ่งทำให้การคำนวณ `status` ทั้งก้อนพัง |
| L20 | `LIKE '%\_ESIM\_%'` | ต่อท้าย `ESCAPE '\'` | ถ้าไม่ใส่ Oracle ไม่ถือว่า backslash เป็น escape — filter จะไม่แมตช์อะไรเลย โดยไม่ error |
| L20 | `left(x, 14)` + `to_timestamp(...,'yyyyMMddHHmmss')` (parse text เป็น timestamp) | `CASE WHEN REGEXP_LIKE(SUBSTR(x, 1, 14), '^[0-9]{14}$') THEN TO_TIMESTAMP(SUBSTR(x, 1, 14) DEFAULT NULL ON CONVERSION ERROR, 'YYYYMMDDHH24MISS') END` (`{14}` = ความยาวของ pattern) | Spark คืน NULL เมื่อ parse ไม่ได้ Oracle โยน `ORA-01858` ทำให้ทั้ง statement ตาย — `DEFAULT NULL ON CONVERSION ERROR` (12.2+) แก้ส่วนนี้ **แต่ไม่ทำให้ parse เข้มงวด**: ค่าที่สั้นกว่า pattern (เช่น `'20260827'`) Oracle เติมศูนย์ให้ได้ `2026-08-27 00:00:00` ไม่ใช่ NULL ขณะที่ Spark ได้ NULL — แถวที่ควรเป็น type-error จึงหลุดเป็นแถวดี **เงียบๆ ไม่มี error** จึงต้องมี `REGEXP_LIKE` ครอบเสมอ ดูกฎ **D-R8** และ `knowledge/lessons-learned.md` L34 |
| L21 | regex `\S`, `\(` | `[^[:space:]]`, `\(` (backslash เดี่ยว) | regex ของ Oracle เป็น POSIX ไม่ใช่ Perl |
| L20 | `nullif(x, '')` | ตัดทิ้ง | ใน Oracle `''` เป็น NULL อยู่แล้ว **และ Oracle ไม่รับ NULL literal เป็น argument ที่สองของ `NULLIF`** — ผลคือไม่ใช่แค่ไม่จำเป็น แต่เขียนไว้แล้วอาจ error ด้วย ⚠️ ผลข้างเคียงที่ต้องบอกผู้ใช้: ค่าที่เป็น `' '` (เว้นวรรค) ยังไม่เป็น NULL อยู่ดี — งานเดิมก็มีช่องโหว่นี้ จึงคงไว้ตามเดิมโดยตั้งใจ |
| L19 | `to_date(x)` | ถ้าคอลัมน์เป็น `DATE`/`TIMESTAMP` อยู่แล้ว: **ไม่ต้องห่อ** ใช้คอลัมน์ตรงๆ — ถ้าเป็น text: `TO_DATE(x, '<mask จากข้อมูลจริง>')` | **ต้องเช็คชนิดจริงของ column จาก DDL ก่อนเสมอ ห้ามเดา** — ดูขั้นตอนเต็มที่กฎ **D-R6** ด้านล่าง (เคสที่พังจริงคือห่อ `TO_DATE` รอบคอลัมน์ที่เป็น `TIMESTAMP` อยู่แล้ว ไม่ใช่กรณี text ที่ไม่มี mask) |
| L17 | `coalesce(x, '')` | ตัดทิ้ง | เหตุผลเดียวกับ L20 |
| L21 | parameter ของ workflow | `#PROJECTCODE.VARIABLE_NAME` | ใน ODI ค่ามาจาก Variable step ฉีดเป็น bind ตอนรัน ในงานจริงพามาด้วย `CROSS JOIN (SELECT '#CODE.V_X' AS col FROM DUAL)` |

## กลุ่ม B — จากโปรเจกต์คู่ขนาน (เรายังไม่ได้ยืนยันเอง)

| Spark | Oracle | หมายเหตุ |
|---|---|---|
| `IFNULL(a, b)` | `NVL(a, b)` | Oracle ไม่มี `IFNULL` |
| `now()` / `current_timestamp()` | `SYSDATE` | แมปทั้งคู่เป็น `SYSDATE` โดยตั้งใจ ถ้าแมปตัวหนึ่งเป็น `SYSTIMESTAMP` งานสองงานที่เจตนาเดียวกันจะได้ความละเอียดต่างกัน |
| `get_user()` | `USER` | pseudo-column ไม่มีวงเล็บ |
| `bigint(expr)` | `TO_NUMBER(expr)` | cast แบบเรียกเป็นฟังก์ชัน |
| `CAST(x AS long)` | `CAST(x AS NUMBER)` | Oracle ไม่รับ `LONG` เป็น target type ของ `CAST` เลย |
| `CAST(x AS STRING / DOUBLE / FLOAT / BIGINT / INT)` | `VARCHAR2(4000)` / `NUMBER` / `NUMBER` / `NUMBER(19)` / `NUMBER(10)` | ชื่อชนิดของ Spark ไม่มีใน Oracle จะพังตั้งแต่ parse — ตั้งความกว้างเผื่อไว้มาก เพราะความกว้างจริงมาจาก datastore ปลายทาง ถ้าบีบตรงนี้จะตัดข้อมูลเงียบๆ |
| `TRY_CAST(x AS t)` | `CAST(x AS <ชนิด Oracle> DEFAULT NULL ON CONVERSION ERROR)` | กลไก fail-soft เดียวกับ L20 และต้องแปลชื่อชนิดไปพร้อมกัน ถ้าเจอชนิดที่ไม่รู้จักให้ flag ห้ามเดา |
| `LIMIT n` | `FETCH FIRST n ROWS ONLY` | Oracle 12.1+ แปลงเฉพาะ `LIMIT` ตัวเลขล้วนท้าย query ถ้ามี `OFFSET` หรือเป็น expression ให้ปล่อยไว้ เพราะลำดับ clause ต่างกัน |
| `date_sub(x, n)` / `date_add(x, n)` | `(TRUNC(x) - n)` / `(TRUNC(x) + n)` | Spark รับจำนวนวันและคืน DATE — `TRUNC` ให้ผลชนิดเดียวกัน ซึ่งแปลว่า argument ที่เป็น timestamp จะเสียส่วนเวลาไป เหมือน Spark เป๊ะ ⚠️ ระวังเมื่อผลไปเทียบกับค่าที่ละเอียดกว่าวัน เช่น partition key แบบ `yyyyMMddHHmm` — guard 30 วันจะเริ่มนับที่เที่ยงคืน |
| `INTERVAL 5 MINUTE` | `INTERVAL '5' MINUTE` | Oracle บังคับให้ใส่ quote รอบตัวเลข |
| `TRUE` / `FALSE` literal | ตามชนิดจริงของคอลัมน์ปลายทางใน DDL: `VARCHAR2` -> `'TRUE'` / `'FALSE'` · `NUMBER(1)` -> `1` / `0` · ไม่มี DDL -> ถามก่อน (house style `'TRUE'`/`'FALSE'` เป็นแค่ค่าตั้งต้นเมื่อไม่มีหลักฐาน) | Oracle ก่อน 23c ไม่มี boolean literal นอก PL/SQL — **ชนิดจริงของคอลัมน์ใน DDL ชนะ house style เสมอ** ใส่ผิดชนิดแล้วได้ `ORA-01722` หรือค่าถูกแปลงเงียบ ๆ |
| `SELECT` ที่ไม่มี `FROM` เลย | เติม `FROM DUAL` | พบบ่อยใน control-task ที่เขียนธง status |
| `date_format(x,'yyyyMMdd')` / `to_timestamp(x,'fmt')` | `TO_CHAR(x,'YYYYMMDD')` / `TO_TIMESTAMP(x,'fmt')` | ⚠️ token ของ Spark เป็น SimpleDateFormat: `MM`=เดือน `mm`=นาที **แยกด้วยตัวพิมพ์** แต่ Oracle ไม่มีกฎ case แบบนั้นและใช้ `MI` แทนนาที — แปลงเฉพาะ pattern ที่รู้จักเท่านั้น ที่เหลือให้ flag ⚠️ **ถ้า `x` เป็น text ที่ parse ด้วย `to_timestamp` ต้องครอบ `REGEXP_LIKE` shape guard ตามกฎ D-R8 / แถว L20 ด้วยเสมอ** — `TO_TIMESTAMP` เดี่ยวๆ ผ่านได้เฉพาะเมื่อ `x` เป็น `DATE`/`TIMESTAMP` อยู่แล้ว (ซึ่งตามกฎ D-R6 ไม่ต้องห่ออยู่แล้ว) |

## ต้องให้คนตัดสิน — ห้ามแปลอัตโนมัติ

| Spark | ทำไมถึงห้ามเดา |
|---|---|
| `concat()` 3 argument ขึ้นไป | ต้องเรียง `\|\|` เอง และต้องตัดสินใจเรื่อง NULL propagation (L15) ซึ่งต้องอ่านเจตนาเดิม |
| `format_string(...)` | ต้องเลือก `LPAD`/`TO_CHAR` ตาม format spec |
| `reverse(...)`, `split(x,sep)[n]` | Oracle ไม่มี array ต้องออกแบบ `REGEXP_SUBSTR` ใหม่ ไม่ใช่เปลี่ยนชื่อฟังก์ชัน |
| `regexp_extract(...)` | ลำดับ/ความหมายของ argument ต่างจาก `REGEXP_SUBSTR` มากพอที่จะคืน group ผิดเงียบๆ |
| `\d \s \S \w` ใน regex | ต้องเลือก POSIX class ให้ตรงกับแต่ละ pattern |
| `to_date(...)` ทุกรูปแบบ | format model ของ Spark case-sensitive ของ Oracle ไม่ใช่ — mask อย่าง `'yyyy-mm-dd'` จะเปลี่ยนความหมายหลังแปลง และฝั่ง Spark มักเป็นฝั่งที่เขียนผิดอยู่แล้ว |
| `CAST` ธรรมดาที่ไม่มี `DEFAULT NULL ON CONVERSION ERROR` | Spark `CAST` นอก ANSI mode คืน NULL เมื่อแปลงไม่ได้ Oracle โยน error แล้วหยุดทั้ง statement — แต่การใส่ clause นี้ทุกจุดก็จะกลบ error ที่ schema ตั้งใจให้ปฏิเสธ ⚠️ ระวังเป็นพิเศษเมื่อ `CAST` ธรรมดาอยู่ใน OR-chain เดียวกับ `TRY_CAST` guard เพราะ SQL ไม่รับประกันการประเมินจากซ้ายไปขวา ตัวที่ strict อาจทำงานก่อน guard |
| `SELECT *, expr ...` | Spark ยอม Oracle ไม่ยอม (`ORA-00936`) — ต้องมี table alias (`SELECT t.*, expr FROM tbl t`) การตั้ง alias เองคือการเขียนใหม่ ไม่ใช่การแทนที่ |
| `NVL(x,'')` / `COALESCE(x,'')` | เจตนา "แทนที่ด้วย string ว่าง" เขียนใน Oracle ไม่ได้เลย มักไม่มีผลเพราะ `\|\|` มอง NULL เป็นว่างอยู่แล้ว แต่เปลี่ยนสิ่งที่การเปรียบเทียบหรือ join key เห็น |
| วงเล็บเกิน/ขาดจากการ copy-paste | เจอในไฟล์จริง เช่น `round(coalesce(x,0), 0) / 1000000, 2)` — ห้าม "แก้ให้" โดยเดาเจตนา ให้ถามว่าบรรทัดนี้ควรตามรูปแบบของ CASE ไหน |
| upsert ที่ `USING` อาจคืนคีย์ซ้ำ | Oracle ปฏิเสธทั้ง statement ด้วย `ORA-30926` ส่วน Spark ยอม — การเติม dedup (`ROW_NUMBER()` + `WHERE rn = 1`) ต้องตัดสินว่า**แถวไหนชนะ** ซึ่งเป็น business logic ห้ามเลือกเอง **[`knowledge/lessons-learned.md` L31 — ใหม่ใน v10]** |
| `TO_DATE` / `TO_NUMBER` ที่ไม่มี format mask | ผลขึ้นกับ NLS ของ session ที่ **ODI agent** รัน ไม่ใช่ของคนที่เทส — ต้องเติม mask ทุกจุด และ mask ที่ถูกต้องคือสิ่งที่ต้องอ่านจากข้อมูลจริง ไม่ใช่เดาจากตัวอย่างแถวเดียว **[`knowledge/lessons-learned.md` L30 — ใหม่ใน v10]** |

## กฎบังคับของทุก statement

### D-R1. `INSERT` ทุกก้อนต้องมี column list ห้ามพึ่งลำดับคอลัมน์

⚠️ **"ทุกก้อน" หมายถึงทุกรูปของ `INSERT` ไม่ใช่เฉพาะที่ขึ้นต้นด้วย `INSERT INTO`** — v10
ขยายถ้อยคำข้อนี้หลังพบว่ากฎเดิมกับตัวตรวจเดิมมองข้ามสองรูปที่งานนี้ใช้จริง

| รูป | ตัวอย่าง | สถานะก่อน v10 |
|---|---|---|
| `INSERT INTO t (…) SELECT …` | รูปปกติ | ตรวจอยู่แล้ว |
| `INSERT INTO t (…) VALUES (…)` | control task | ตรวจ column list แต่ **ไม่เคยตรวจ arity** |
| `MERGE … WHEN NOT MATCHED THEN INSERT (…) VALUES (…)` | **ทุก upsert ตาม house style** | **ไม่ถูกตรวจเลย** |
| `INSERT ALL INTO t1 (…) … INTO t2 (…) … SELECT …` | multi-table insert | **ไม่ถูกตรวจเลย** |

สองรูปล่างคือความพังตัวเดียวกับL24 เป๊ะๆ แค่เขียนด้วยไวยากรณ์อื่น
**[`knowledge/lessons-learned.md` L24 — ใหม่ใน v10]**

```sql
-- ผิด — positional insert ผูกกับลำดับคอลัมน์ของตาราง
INSERT INTO dssdev.tb_transaction_valid
SELECT a, b, c FROM …

-- ถูก — จับคู่ด้วยชื่อ ลำดับเปลี่ยนก็ไม่กระทบ
INSERT INTO dssdev.tb_transaction_valid
    (partition_date, cdr_id, cdr_type)
SELECT a, b, c FROM …
```

**ทำไมถึงต้องเขียนเป็นกฎ** — Spark เขียน `INSERT OVERWRITE TABLE x SELECT …` ซึ่งเป็น
positional โดยธรรมชาติ ถ้าแปลงแบบ 1:1 จะได้ positional insert ออกมาเสมอ ในงานจริงที่ทดสอบ
มี 9 `INSERT` โดย 4 ตัวไม่มี column list เพราะต้นทางไม่มี — ตัวหนึ่งทำให้ package ตายที่
`ORA-00947` ตอนรัน **[เกิดขึ้นจริงมาแล้ว — `knowledge/lessons-learned.md` L24]**

- ชื่อคอลัมน์เอามาจาก **DDL ที่ได้จาก I3** เป็นค่าเริ่มต้นเสมอ — ใช้ alias ของ `SELECT` แทนได้
  **เฉพาะเมื่อผู้ใช้เลือกโหมดเดาที่ I3 อย่างชัดเจนแล้วเท่านั้น** ไม่ใช่สิ่งที่ AI ตัดสินใจเอง
  เมื่อขี้เกียจไปถามหรือไม่มีเวลารอ
- **ถ้าเลือกโหมดเดา** ต้องใส่คอมเมนต์กำกับทุกบรรทัดตามรูปแบบใน I3 (`-- GUESSED COLUMN LIST: …`)
  และต้องเป็นเงื่อนไขที่คุยกับผู้ใช้ไว้แล้ว ไม่ใช่สิ่งที่ AI ตัดสินใจกลางทางระหว่างแปลง SQL
- คอลัมน์ที่ไม่ได้ระบุต้องเป็น nullable หรือมี DEFAULT — ถ้าเป็น `NOT NULL` ไม่มี DEFAULT
  ต้องกลับไปหาว่างานเดิมเติมค่าอะไร **ห้ามเดาแล้วใส่เอง** (ถ้าไม่มี DDL จะไม่รู้ด้วยซ้ำว่ามีคอลัมน์
  แบบนี้อยู่หรือไม่ — เป็นความเสี่ยงที่โหมดเดายังปิดไม่ได้ ต้องบอกผู้ใช้ตรงๆ)
- ⚠️ อันตรายกว่า `ORA-00947` คือกรณีจำนวนคอลัมน์บังเอิญเท่ากันแต่ลำดับต่างกัน —
  รันผ่าน ไม่มี error แต่ข้อมูลลงผิดคอลัมน์ (โหมดเดาเสี่ยงกับเคสนี้มากกว่าปกติ เพราะไม่มี DDL
  มายืนยันว่าลำดับคอลัมน์จริงของตารางเรียงยังไง)

### D-R2. ชื่อตารางทุกตัวต้อง qualify ด้วย schema

```sql
-- ผิด
FROM tb_landing_ss_esim

-- ถูก (schema มาจาก I4)
FROM dssdev.tb_landing_ss_esim
```

**ทำไม** — ODI **ไม่เติม schema ให้อัตโนมัติใน SQL ดิบของ Procedure** ตารางที่ไม่ qualify จะ
resolve ตาม default schema ของ user ที่ Data Server ใช้ต่อ ซึ่งมักไม่ใช่ schema ของตาราง
**[เกิดขึ้นจริงมาแล้ว — `knowledge/lessons-learned.md` L25]**

- ครอบคลุมทั้งตารางที่เขียน (`INSERT INTO` / `MERGE INTO` / `TRUNCATE TABLE` / `UPDATE`)
  และตารางที่อ่าน (`FROM` / `JOIN`) รวมถึงที่อยู่ใน subquery ทุกชั้น
- **ไม่ต้องเติม** ให้ `DUAL`, alias ของ inline view, และ CTE ที่ประกาศด้วย `WITH`
- ตารางที่ชื่อขึ้นต้นต่างจากกลุ่มหลัก (เช่น `ext_`, `vw_`) ต้องยืนยัน schema แยกทีละตัวที่ I4
  **ห้ามเหมาว่าอยู่ schema เดียวกันหมด**
- ถ้าผู้ใช้เลือกข้อ 2 ที่ I4 (ตั้ง `CURRENT_SCHEMA` ที่ Data Server) ให้ **ไม่ต้อง**
  qualify แต่ต้องบันทึกเป็น open item ในรายงานปิดงานว่าคนต้องไปตั้งค่านั้นก่อนรัน
- ⚠️ คำว่า `FROM` ที่อยู่ข้างในวงเล็บของ `EXTRACT(… FROM x)`, `TRIM(… FROM x)`,
  `SUBSTRING(… FROM …)` **ไม่ใช่การอ้างตาราง** อย่าไปเติม schema ให้ชื่อที่ตามมา
  (ตัวตรวจเองเคยพลาดข้อนี้แล้วปฏิเสธ SQL ที่ถูกต้อง — `knowledge/lessons-learned.md` L35)

### D-R3. หนึ่ง statement ต่อหนึ่งบรรทัดคำสั่ง ไม่มี `;` ปิดท้าย ไม่ว่างเปล่า

```sql
-- ผิด — ; เป็นตัวจบคำสั่งของเครื่องมือ ไม่ใช่ของ SQL
INSERT INTO dssdev.tgt (a) SELECT x FROM dssdev.src;

-- ถูก
INSERT INTO dssdev.tgt (a) SELECT x FROM dssdev.src
```

**ทำไม** — ODI ส่งข้อความในบรรทัดคำสั่งเข้า JDBC ตรงๆ ซึ่งไม่มีตัวจบคำสั่ง `;` จึงกลายเป็น
อักขระแปลกปลอม → `ORA-00911: invalid character` ตอนรัน **ทั้งที่ SQL ก้อนเดียวกันรันผ่าน
ใน SQL Developer มาแล้ว** (เครื่องมือที่ใช้เทส**ต้องมี** `;` ถึงจะรันได้ จึงเป็นตัวที่ทำให้
บั๊กนี้มองไม่เห็น) **[`knowledge/lessons-learned.md` L26]**

- ไฟล์ `.sql` หนึ่งไฟล์ = หนึ่ง statement เสมอ (กฎเดิมของเส้นทาง B อยู่แล้ว แค่บังคับให้ตรวจ)
- ไฟล์ว่างหรือมีแต่คอมเมนต์ = step ที่ import ผ่านแล้วไม่ทำอะไร **[`knowledge/lessons-learned.md` L22]**
- ข้อยกเว้นเดียว: บล็อก PL/SQL (`BEGIN … END;`) ซึ่ง `;` ข้างในเป็นไวยากรณ์ของภาษา
  — แต่ `SqlIndGrp` ของคำสั่งที่ขึ้นต้นด้วย `BEGIN` ต้องให้คนระบุ (`knowledge/reference/optional/manual-build-procedure.md` ขั้น 2) · `TO_DATE`/`TO_TIMESTAMP` แบบ 1 argument (ไม่มี format mask) ตรวจอัตโนมัติได้แล้วด้วย `check_sql.py` rule D-R6 (checklist ข้อ 43) — `TO_CHAR`/`TO_NUMBER` แบบ 1 argument ยังอยู่ใน must-ask เดิม ต้องตรวจด้วยตา

### กฎชื่อคอลัมน์ — ทุกชื่อในลิสต์ต้องใช้ได้แบบไม่มี double quote

สำคัญเป็นพิเศษกับโหมดเดาของ I3 เพราะชื่อ field ของ Spark ถูกคัดลอกมาตรงๆ

- **ห้ามใส่ double quote รอบชื่อที่เดามาเด็ดขาด** — การ quote ไม่ได้ปลอดภัยกว่า มันทำให้ชื่อ
  กลายเป็น case-sensitive และจะแมตช์เฉพาะคอลัมน์ที่ถูก `CREATE` ด้วยชื่อในเครื่องหมายคำพูด
  สะกดเหมือนกันเป๊ะ ซึ่งตารางส่วนใหญ่ไม่ได้เป็นแบบนั้น
- **ชื่อที่ชนคำสงวนของ Oracle คือสัญญาณว่าเดาผิด ไม่ใช่ปัญหาการ escape** —
  `date`, `level`, `number`, `comment`, `size`, `uid`, `user`, `row` เป็นชื่อคอลัมน์ธรรมดา
  ฝั่ง Spark แต่ใช้แบบไม่มี quote ใน Oracle ไม่ได้เลย เจอแล้วต้องกลับไปขอ DDL จริงของใบนั้น
- **ความยาว** — เกิน 30 ไบต์ใช้ไม่ได้บน 11g และเก่ากว่า (12.2+ ขยายเป็น 128) ต้องรู้เวอร์ชัน
  ของ database ปลายทางก่อน
- ถ้า DDL จริงยืนยันว่ามีคอลัมน์ชื่อที่ชนคำสงวนอยู่จริง แปลว่าตารางถูกสร้างด้วย quoted
  identifier ตั้งแต่แรก — กรณีนั้น**ต้อง** quote และสะกดตรงตัวพิมพ์ ให้บันทึกเป็น open item

**[`knowledge/lessons-learned.md` L24, L27 · `delivery-checklist.md` ข้อ 40]**

### D-R4. ชื่อ alias ที่ตั้งเอง (table alias / subquery alias / CTE) ต้องไม่ชนคำสงวนของ Oracle

```sql
-- ผิด — RAW เป็นชื่อ datatype ในตัวของ Oracle เอง (อยู่ใน reserved words)
SELECT raw.cdr_id, raw.iccid
FROM ( SELECT cdr_id, iccid FROM dssdev.tb_landing_ss_esim ) raw

-- ถูก — เปลี่ยนชื่อ alias เป็นอย่างอื่น ไม่กระทบผลลัพธ์
SELECT landing_raw.cdr_id, landing_raw.iccid
FROM ( SELECT cdr_id, iccid FROM dssdev.tb_landing_ss_esim ) landing_raw
```

**ทำไม** — alias ที่ตั้งเองระหว่างแปลง SQL (ไม่ได้มาจาก DDL เหมือนชื่อคอลัมน์) ก็ชนคำสงวนของ
Oracle ได้เหมือนกัน เช่น `raw`, `date`, `level`, `row`, `user` — พอเขียนอ้างเป็น `<alias>.column`
parser จะตีความชื่อนั้นเป็นคำสงวนแทนที่จะเป็น alias ทำให้ `ORA-00936: missing expression`
**[เกิดขึ้นจริงมาแล้ว — `knowledge/lessons-learned.md` L27]**

- เช็คทุกชื่อ alias ที่จะตั้งเอง (table alias, subquery alias, ชื่อ CTE) กับ Oracle Reserved
  Words list **ก่อน**ใช้เสมอ — คนละรายการกับกฎชื่อคอลัมน์ด้านบน เพราะ alias ไม่เคยมาจาก DDL
  จึงเกิดได้แม้ตารางทุกใบมี DDL จริงครบ
- ชนคำสงวน = เปลี่ยนชื่อ alias เป็นอย่างอื่นที่สื่อความหมายใกล้เคียงเดิม ไม่กระทบผลลัพธ์
  เพราะเป็นแค่ชื่อเรียกชั่วคราว ไม่ใช่ column/table จริง — ต่างจากชื่อคอลัมน์ที่ชนคำสงวน (ต้อง
  กลับไปขอ DDL จริง ไม่ใช่เปลี่ยนชื่อเอง)

**[`knowledge/lessons-learned.md` L27 · `delivery-checklist.md` ข้อ 50]**

### D-R5. `UNION`/`UNION ALL` ของคอลัมน์ชื่อเดียวกันจากคนละตาราง ต้องเช็ค datatype ให้ตรงกันก่อนเสมอ

```sql
-- ผิด — CHK_DUPLICATE เป็น CLOB ใน VALID แต่เป็น VARCHAR2 ใน TEMP
SELECT chk_duplicate FROM dssdev.tb_transaction_ss_esim_valid
UNION
SELECT chk_duplicate FROM dssdev.tb_transaction_ss_esim_temp

-- ถูก — cast ฝั่งที่เป็น LOB ก่อนเข้า UNION
SELECT TO_CHAR(chk_duplicate) AS chk_duplicate FROM dssdev.tb_transaction_ss_esim_valid
UNION
SELECT chk_duplicate FROM dssdev.tb_transaction_ss_esim_temp
```

**ทำไม** — ชื่อคอลัมน์ตรงกันไม่ได้แปลว่า datatype ตรงกัน Oracle ปฏิเสธทั้ง statement ด้วย
`ORA-01790` ถ้ามี expression ตำแหน่งเดียวกันคนละชนิด **[เกิดขึ้นจริงมาแล้ว — `knowledge/lessons-learned.md`
L28]**

- เช็ค datatype จริงของทุกคอลัมน์ที่จะเอามา `UNION`/`UNION ALL` จาก DDL/reference ก่อนเสมอ
  ไม่ใช่เช็คแค่ว่าชื่อตรงกัน
- ถ้า mismatch และฝั่งใดฝั่งหนึ่งเป็น LOB (`CLOB`/`NCLOB`) ให้ cast ฝั่งนั้นด้วย `TO_CHAR()`
  ก่อนเข้า `UNION` — ⚠️ ต้องยืนยันก่อนว่าเนื้อหาจริงในคอลัมน์นั้นไม่มีทางยาวเกิน limit ที่
  `TO_CHAR` แปลงได้ (ปกติ 4000 ตัวอักษร) เพราะเกินแล้วจะถูกตัดทอนเงียบๆ ถ้าไม่แน่ใจต้องถาม
  ผู้ใช้ ไม่ใช่ประมาณเอง
- คอลัมน์ชื่อเดียวกันคนละ datatype ในตารางที่ควรเก็บข้อมูลแบบเดียวกัน เป็นสัญญาณ DDL
  ไม่สอดคล้องกันเชิงโครงสร้าง ควรแจ้งทีมที่ดูแล DDL ให้รู้ไว้ด้วย

### D-R6. `TO_DATE`/`TO_TIMESTAMP` ต้องมี format mask เสมอ **และ** ห้ามห่อคอลัมน์ที่เป็นวันที่อยู่แล้ว

⚠️ **(เช็คทั้ง "มี mask ไหม" และ "mask นั้นควรมีอยู่จริงไหม")
ขยายอีกใน v16 (ปิดเคสเทียบ string ตรงๆ โดยไม่มี `TO_DATE` เลย + `TO_CHAR`/`TO_NUMBER`)**
หลัง `TO_DATE(effective_date, 'YYYY-MM-DD')` ใน `TEST_AI_GEN_13` รันจริงแล้วได้ `ORA-01858`
ทั้งที่มี format mask อยู่แล้ว — สาเหตุคือ `effective_date`/`expired_date` เป็น `TIMESTAMP`
อยู่แล้วจริงๆ (ยืนยันจาก DDL ทีหลัง) การห่อด้วย `TO_DATE(...,'YYYY-MM-DD')` บังคับให้ Oracle
แปลง `TIMESTAMP -> VARCHAR2` ตาม `NLS_TIMESTAMP_FORMAT` ของ session ก่อน แล้วค่อยพาร์สกลับด้วย
mask ที่ไม่ตรงรูปแบบ **[เกิดขึ้นจริงมาแล้ว]**

```sql
-- ผิด -- effective_date เป็น TIMESTAMP อยู่แล้วจริง (ยืนยันจาก DDL)
-- การห่อ TO_DATE ไม่ได้ "แปลงวันที่" แต่บังคับให้เกิด TIMESTAMP -> VARCHAR2 -> TO_DATE
-- โดยพึ่ง NLS_TIMESTAMP_FORMAT ของ session ที่ ODI agent ใช้รันเงียบๆ
SELECT TO_DATE(effective_date, 'YYYY-MM-DD') FROM dssdev.ext_dss_vw_service_mapping_bno_key

-- ถูก -- เป็น TIMESTAMP อยู่แล้ว ไม่ต้องแปลงเลย ใช้คอลัมน์ตรงๆ
SELECT effective_date FROM dssdev.ext_dss_vw_service_mapping_bno_key

-- ถูก (อีกกรณี) -- ถ้า DDL ยืนยันว่าเป็น VARCHAR2/text จริง ถึงจะใส่ mask
-- และ mask ต้องมาจากรูปแบบข้อมูลจริง ไม่ใช่เดาจาก pattern ทั่วไปอย่าง 'YYYY-MM-DD'
SELECT TO_DATE(some_text_col, 'YYYYMMDDHH24MISS') FROM dssdev.some_table
```

**ขั้นตอนบังคับก่อนห่อ `TO_DATE`/`TO_TIMESTAMP` ทุกครั้ง**

1. **เช็คชนิดจริงของคอลัมน์ก่อนเสมอ** จาก DDL ที่ได้ที่ I3 (รวมตารางฝั่ง READ ตามขอบเขตที่ขยาย
   ใน v14) หรือจากโครงสร้าง reverse-engineer ที่ชื่อตรงเป๊ะในไฟล์ reference ของ I2
2. **ถ้าชนิดจริงเป็น `DATE`/`TIMESTAMP` อยู่แล้ว -> ห้ามห่อด้วย `TO_DATE`/`TO_TIMESTAMP` เด็ดขาด**
   ใช้คอลัมน์ตรงๆ (หรือ `TRUNC(x)` ถ้าต้องการตัดเวลาออกจริงๆ) -- การห่อซ้ำไม่ใช่การ "ป้องกันไว้
   ก่อน" แต่เป็นการสร้างช่องทางแปลงชนิดที่ไม่จำเป็นและเสี่ยง `ORA-01858`
3. **ถ้าชนิดจริงเป็น text (`VARCHAR2`/`CHAR`) -> ใส่ format mask ที่ตรงกับรูปแบบข้อมูลจริง**
   (ดูรูปแบบนี้จากข้อมูลตัวอย่างจริง ไม่ใช่เดาจาก pattern ที่ "ดูน่าจะเป็น")
4. **ถ้าหาชนิดจริงไม่ได้เลย (ไม่มี DDL และไม่มีชื่อตรงในโครงสร้าง reverse-engineer)** ต้องถามผู้ใช้
   ตรงๆ ตามกฎ "ต้องให้คนตัดสิน -- ห้ามแปลอัตโนมัติ" ด้านบน **ห้ามเดา mask แล้วใส่ไปเงียบๆ**
   แม้จะดูเป็น format ที่พบบ่อยแค่ไหนก็ตาม -- ถ้าผู้ใช้เลือกยอมรับความเสี่ยงให้เดา ต้องบันทึกเป็น
   "เดา -- ยังไม่ยืนยัน" เหมือนโหมดเดาของ I3 ทุกประการ รวมคอมเมนต์กำกับในบรรทัด SQL ด้วย

**ตรวจอัตโนมัติได้บางส่วน** -- `check_sql.py` rule D-R6 มีสามชั้น บวกอีกหนึ่ง
check แยกที่ไม่ใช่ D-R6 แต่ปิด checklist ข้อ 43 ส่วนที่เหลือ:
- **ชั้นที่ 1 (ไม่ต้องมี `--ddl`, เช็คตลอด)**: `TO_DATE`/`TO_TIMESTAMP` ที่เรียกแบบ 1 argument
  (ไม่มี mask เลย) -> `[WARN]`
- **ชั้นที่ 2 (ต้องมี `--ddl`)**: `TO_DATE`/`TO_TIMESTAMP` ไม่ว่าจะมี mask หรือไม่ ถ้า
  argument แรกตรงกับชื่อคอลัมน์ใน DDL ที่ชนิดเป็น `DATE`/`TIMESTAMP` อยู่แล้ว -> `[ERROR]`
  (นี่คือจุดที่จับเคสจริงของ `TEST_AI_GEN_13` ได้ -- mask มีอยู่แล้วแต่ผิด ชั้นที่ 1 เพียงอย่างเดียว
  จับไม่ได้) **จับคู่ด้วยชื่อคอลัมน์ล้วนๆ ไม่ได้ resolve join/alias** ถ้าชื่อคอลัมน์ชนกันข้ามตาราง
  ที่ไม่เกี่ยวข้องกันใน `--ddl` เดียวกัน อาจ false positive ได้ -- ข้อความ error จะระบุชื่อตารางที่
  แมตช์ไว้เสมอเพื่อให้ตรวจสอบได้ว่าใช่ตัวที่ตั้งใจหรือไม่
- **ชั้นที่ 3 (ต้องมี `--ddl`)**: คอลัมน์ที่ DDL ยืนยันว่าเป็น `DATE`/`TIMESTAMP` ถูกเทียบ
  กับ string literal ตรงๆ (`=`, `<>`, `!=`, `<`, `<=`, `>`, `>=`, หรือ `BETWEEN`) โดยไม่มี
  `TO_DATE`/`TO_TIMESTAMP` ห่อเลยสักฝั่ง -> `[ERROR]` นี่คือครึ่งหลังของสิ่งที่ checklist ข้อ 43
  และ `knowledge/lessons-learned.md` L30 เขียนไว้เป็นข้อความอยู่แล้ว ("ห้ามเทียบ string กับคอลัมน์ DATE ตรงๆ")
  แต่ v1.5.0 ยังไม่ได้ปิด เพราะชั้นที่ 2 มองหาแค่ภายในวงเล็บของ `TO_DATE`/`TO_TIMESTAMP` เท่านั้น
  ประโยค `WHERE effective_date = '20250101'` ที่ไม่มี `TO_DATE` อยู่เลยจึงหลุดรอดไปก่อนหน้านี้
  จับคู่ด้วยชื่อคอลัมน์ล้วนๆ เหมือนชั้นที่ 2 ทุกประการ (caveat เดียวกัน)
- **ไม่ใช่ D-R6 แต่ปิด checklist ข้อ 43 ที่เหลือ (ไม่ต้องมี `--ddl`)**: `TO_CHAR`/
  `TO_NUMBER` แบบ 1 argument -> `[WARN]` (ไม่ใช่ `[ERROR]` เพราะแยกไม่ออกว่าเป็นตัวเลขธรรมดา
  หรือวันที่โดยไม่มีชนิดคอลัมน์จริงมาเทียบ จึงยกระดับเป็น error ไม่ได้ ต้องให้คนดูเอง)
- **ยังตรวจไม่ได้เลยและต้องดูด้วยตา**: กรณี mask ผิดที่ argument ไม่ใช่ simple identifier
  (เช่น ซ้อนอยู่ในฟังก์ชันอื่นหรือเป็น expression) -- เครื่องมือข้ามให้เงียบๆ ตามเจตนา

**[เกิดขึ้นจริงมาแล้ว -- `ORA-01858` ใน `TEST_AI_GEN_13`, ดู `HANDOVER.md` ข้อ 43]
(checklist ข้อ 43)**

### D-R7. overwrite ไม่ได้แปลว่า `TRUNCATE` ทั้งตารางเสมอไป

⚠️ **ใหม่ใน v16 -- ยกระดับเป็น D-R7 พร้อมตัวตรวจอัตโนมัติ (เดิมเป็นกฎที่ตรวจด้วยตาล้วน)**
นี่คือความเสี่ยงที่ `knowledge/lessons-learned.md` ให้คะแนนสูงสุดในทั้งชุดบทเรียน (L29) และก่อน v16 ไม่มี
automated backstop ใดๆ เลยสักจุด

house style แปลง `sinkOption.mode = Overwrite` เป็น `TRUNCATE TABLE` + `INSERT`
ซึ่ง**ถูกต้องเฉพาะเมื่อ `sinkOption.partitions` ว่าง** ถ้าไม่ว่าง งานเดิมเขียนทับเฉพาะ partition
ที่ระบุ การ `TRUNCATE` ทั้งใบจะลบข้อมูลของ partition อื่นทั้งหมด **ถาวร ไม่มี error
ไม่มีอะไรฟ้อง** และ validation ระดับ 1 (`knowledge/reference/validation-and-cutover.md E1`, เทียบจำนวนแถว) จะยังดูเหมือนผ่านอยู่ดี
เพราะเทียบแค่แถวที่โหลดรอบนี้ ไม่เทียบยอดรวมทั้งตารางก่อน/หลัง ต้องหยุดถามที่ I14 ก่อนเสมอ
**[`knowledge/lessons-learned.md` L29 · `delivery-checklist.md` ข้อ 41]**

### overwrite เฉพาะ partition: รูปแบบมาตรฐาน DELETE + INSERT (เมื่อผู้ใช้เลือกทางที่ 1 ใน I14)

ก่อนเลือกทาง ต้องยืนยัน `spark.sql.sources.partitionOverwriteMode` ของ workflow (ถาม/ดูจาก config ของ Spark job):
`dynamic` = เขียนทับเฉพาะ partition ที่มีในผลลัพธ์ SELECT · `static` (ค่าเริ่มต้น) = `INSERT OVERWRITE` ลบทุก partition
ที่ตรงเงื่อนไข ถ้าไม่ระบุ partition spec อาจเท่ากับทั้งตาราง — ผลต่างกันมาก จึงห้ามเดา

**v18: `gen_dml.py` สร้างรูปแบบนี้ให้เมื่อ `DECISION=delete_by_partition` ใน `config/partitions_check.csv` (ใช้ SELECT เดียวกันทั้งสอง step; ยังไม่ใช้ `V_NOW` — ดูข้อควรระวังเรื่อง SYSDATE ข้างล่าง)**

รูปแบบมาตรฐาน (2 command line ใน Procedure เดียว, ใช้ ODI variable ตัวเดียวเป็นเวลาอ้างอิงของทั้งสองบรรทัด):

```sql
-- command 1: ลบเฉพาะ partition ที่จะถูกเขียนใหม่ (ค่าเดียวกับที่ SELECT ของ command 2 จะผลิต)
DELETE FROM <schema>.<target>
WHERE <partition_col> IN (
    SELECT DISTINCT <partition_expr>
    FROM ( <SELECT เดียวกับ command 2 โดยใช้ #<PROJECT>.V_NOW แทน SYSDATE> )
)

-- command 2: เขียนกลับ (มี column list ครบ)
INSERT INTO <schema>.<target> (<col1>, <col2>, ...)
SELECT ... FROM ... -- ใช้ #<PROJECT>.V_NOW ตัวเดียวกัน
```

- `V_NOW` ต้อง refresh ครั้งเดียวก่อนทั้งสองบรรทัด (step ก่อนหน้าใน package) — ถ้าแต่ละบรรทัดเรียก `SYSDATE` เอง partition ที่ลบกับที่เขียนอาจต่างวันเมื่อรันคร่อมเที่ยงคืน
- ลบเฉพาะ partition ที่ **มีอยู่ใน SELECT** ไม่ใช่ทุก partition ในตาราง และไม่ใช่ `WHERE <partition_col> = <วันนี้>` ที่เดาเอง
- ถ้า SELECT คืน 0 แถว จะไม่ลบอะไร (ตรงกับ `dynamic`) — ถ้างานเดิมต้องการให้ล้าง partition ว่าง ให้ถามผู้ใช้
- DELETE ย้อนกลับได้ใน transaction เดียวกัน (ต่างจาก `TRUNCATE`) แต่ ODI Procedure ปกติ commit ต่อ command — ระบุ transaction/commit ใน build spec

> **ตรวจ D-R1 / D-R2 / D-R3 / D-R4 / D-R6 (ชั้นที่ 1) / D-R7 และกฎชื่อคอลัมน์ได้โดยไม่ต้องต่อฐานข้อมูล**
> `python scripts/checks/check_sql.py <โฟลเดอร์ sql>`
>
> **D-R4 (alias ชนคำสงวน) ตรวจอัตโนมัติแล้วตั้งแต่ v12 (`check_sql.py` 1.3.0)** ไม่ต้องมี
> `--ddl` เลย ส่วน **D-R5 (datatype ของ `UNION`) ก็ตรวจอัตโนมัติแล้วเช่นกัน** แต่ต้องมี `--ddl`
> ที่มีคอลัมน์ `DATA_TYPE` เพิ่ม (เหมือนกลุ่ม checklist ข้อ 32–34 ที่ต้องมี DDL) — เทียบตามตำแหน่ง
> ใน `SELECT` list ไม่ใช่ตามชื่อคอลัมน์ และหา `UNION`/`UNION ALL` ทุกระดับความลึก ไม่ใช่แค่บรรทัด
> บนสุด รายละเอียดอยู่ที่ `README.md`
>
> **D-R6 ตรวจอัตโนมัติสามชั้นแยกกัน (`check_sql.py` 1.6.0)** — ชั้นที่ 1 (ไม่ต้อง `--ddl`:
> `TO_DATE`/`TO_TIMESTAMP` แบบ 1 argument) ตรวจเสมอเหมือนเดิมตั้งแต่ v1.4.0 ชั้นที่ 2 (ต้องมี
> `--ddl`: มี mask แต่ผิดเพราะคอลัมน์เป็น `DATE`/`TIMESTAMP` อยู่แล้ว) มาจาก v1.5.0 ชั้นที่ 3
> (ต้องมี `--ddl`: เทียบ string literal ตรงๆ กับคอลัมน์ `DATE`/`TIMESTAMP` โดยไม่มี `TO_DATE`
> ห่อเลย) — **ถ้าไม่ใส่ `--ddl` ชั้นที่ 2 และ 3 จะไม่ทำงานเงียบๆ เหมือน D-R5**
> ต้องใส่ `--ddl` ที่ครอบคลุมตารางฝั่ง READ ที่ใช้กับ `TO_DATE`/`TO_TIMESTAMP`/`WHERE` ด้วย ไม่ใช่
> แค่ตารางที่ `INSERT`/`MERGE` ลงไป (ตามขอบเขต I3) ถึงจะได้ความคุ้มครองเต็มที่
> `TO_CHAR`/`TO_NUMBER` แบบ 1 argument ได้ `[WARN]` แยกต่างหากแล้วเช่นกัน (v1.6.0) ไม่ต้องมี
> `--ddl`
>
> **D-R7 (`sinkOption.partitions` vs `TRUNCATE`) ตรวจอัตโนมัติบางส่วนแล้วตั้งแต่ v1.6.0** —
> ต้องมีไฟล์ `--partitions` ที่สร้างเองจากคำตอบ I14 (คอลัมน์ `TABLE_NAME`, `PARTITIONS_EMPTY`
> เป็น Y/N) ตัวตรวจจึงจะยืนยันได้ว่า `TRUNCATE` แต่ละจุดถูกหรือผิด (`[ERROR]` ถ้าตารางนั้น
> partitions ไม่ว่างตามไฟล์) **ต่างจาก D-R5/D-R6 ชั้นที่ 2-3 ตรงที่ D-R7 ไม่เงียบเลยถ้าไม่ใส่
> `--partitions`** -- ทุก `TRUNCATE TABLE` จะได้ `[WARN]` ให้ไปยืนยันด้วยตาเสมอ เพราะนี่คือ
> ความเสี่ยงสูงสุดในชุดบทเรียนทั้งชุด การสร้างไฟล์ `--partitions` อัตโนมัติแล้วบางส่วนตั้งแต่ v16
> รอบ 3 ผ่าน `scripts/checks/extract_partitions.py` ซึ่งอ่าน `sinkOption.partitions` จาก DAG JSON ตรงๆ
> สำหรับทุกตารางที่ field นี้มีอยู่จริง เหลือให้คนตัดสินเองเฉพาะทาสก์ที่ field หายไปทั้ง field
> หรือตารางเดียวกันถูกเขียนทับจากหลายทาสก์ด้วยผลขัดกัน (สคริปต์แยกพิมพ์เป็นรายการให้ถามผู้ใช้
> ตรงๆ ไม่เดาให้) การตรวจ cross-reference กับ SQL จริงหลังจากนั้นเป็นอัตโนมัติเหมือนเดิม

---

### D-R8. `to_timestamp`/`to_date` ที่ parse text ต้องมี shape guard — `DEFAULT NULL ON CONVERSION ERROR` ไม่ได้ทำให้ Oracle เข้มงวดเท่า Spark

**ที่มา** — เทส package ที่ build จาก md 14 เทียบกับ Blendata พบว่า `tb_transaction_ss_esim_valid` ได้ 18 แถว
ทั้งที่ควรได้ 17 แถวที่เกินคือแถวที่ `first_installed = '20260827'` (มีแต่วันที่ ไม่มีเวลา) Spark คืน NULL
จึงเข้า `TYP` ส่วน Oracle คืน `2026-08-27 00:00:00` จึงเข้า `MAP` รายละเอียดเต็มที่ `knowledge/lessons-learned.md` L34

**กฎ**

1. ทุกครั้งที่แปล `to_timestamp(...)`/`to_date(...)` ของ Spark ที่ **parse text** เป็นวันที่/เวลา ให้ครอบด้วย
   shape guard ที่ตรงกับ pattern ของ Spark:

   ```sql
   CASE WHEN REGEXP_LIKE(SUBSTR(x, 1, 14), '^[0-9]{14}$')
        THEN TO_TIMESTAMP(SUBSTR(x, 1, 14) DEFAULT NULL ON CONVERSION ERROR, 'YYYYMMDDHH24MISS')
   END
   ```

   - เลขใน `{N}` = จำนวนตัวอักษรที่ pattern ต้องการ (`yyyyMMddHHmmss` = 14, `yyyyMMdd` = 8)
   - pattern ที่มีตัวคั่น (`yyyy-MM-dd HH:mm:ss`) ให้เขียน regex ที่มีตัวคั่นตรงตามนั้น
     (`'^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$'`) ห้ามใช้ `{N}` ตัวเลขล้วน
   - `DEFAULT NULL ON CONVERSION ERROR` ยังต้องคงไว้ เพื่อจับค่าที่ครบความยาวแต่เป็นวันที่ที่เป็นไปไม่ได้
     (เดือน 13, วันที่ 32) ให้ได้ NULL แบบ Spark
2. ถ้าใช้ expression เดียวกันซ้ำหลายจุด (ค่า + เงื่อนไข type_error) ให้ใช้ expression **เดียวกันทุกจุด**
   หรือคำนวณครั้งเดียวใน inline view ชั้นใน แล้วอ้างชื่อคอลัมน์ ห้ามให้สองจุดนิยามต่างกัน
3. ทางเลือกแทน `REGEXP_LIKE`: format mask แบบ `FX` (`'FXYYYYMMDDHH24MISS'`) บังคับให้ input ตรง
   format เป๊ะ ใช้ได้ถ้ายืนยันกับข้อมูลจริงแล้วว่าไม่มี whitespace ปนมา
4. **ไม่ต้องใส่** ถ้าคอลัมน์ต้นทางเป็น `DATE`/`TIMESTAMP` อยู่แล้ว (D-R6 ห้ามห่ออยู่แล้ว)
5. ข้อมูลทดสอบ (`knowledge/reference/validation-and-cutover.md`) ต้องมีแถวที่ค่า**สั้นกว่า pattern** อย่างน้อยหนึ่งแถวสำหรับทุกคอลัมน์ที่
   parse text — แถวที่ผิดรูปแบบแต่ยังอ่านได้ (เช่น `20260827`) คือแถวที่จับบั๊กนี้ได้ ส่วนแถวที่เป็นตัวอักษรล้วน
   จับไม่ได้เพราะ Oracle โยน error อยู่แล้ว

**ตัวตรวจ** — `check_sql.py` 1.7.0 ออก `[WARN]` (ไม่ใช่ `[ERROR]`) เมื่อพบ `TO_TIMESTAMP`/`TO_DATE` ที่มี
numeric mask แต่ทั้ง statement ไม่มี `REGEXP_LIKE(` และ mask ไม่ใช่ `FX` ข้อจำกัดที่ต้องรู้:
(ก) ตรวจระดับ statement — ถ้ามี `REGEXP_LIKE` ที่ไหนก็ตามใน statement ตัวตรวจจะเงียบทั้ง statement
แม้บางจุดยังไม่มี guard ต้องไล่ตาเองว่าทุกจุดที่ parse text มี guard (ข) ตัวตรวจไม่รู้ว่าคอลัมน์ต้นทางเป็น
text หรือ timestamp จึงเป็น WARN ไม่ใช่ ERROR และห้ามแก้ SQL เพียงเพื่อให้ WARN หาย

### D-R9. ผลของ SQL ฝั่ง Spark ขึ้นกับ Spark config — ต้องรู้ค่าก่อนเลือกวิธีแปลง

⚠️ **กฎนี้ตรวจด้วยตาเท่านั้น** `check_sql.py` ไม่รู้ว่า Blendata ตั้งค่าอะไร ค่าที่ใช้ตัดสินมาจากขั้นเสริม S
(`knowledge/reference/oracle-checks-and-spark-config.md` I4) และต้องบันทึกใน `status/MIGRATION_STATUS.md` ทุกครั้งที่ใช้ค่านั้นเลือกวิธีแปลง

| config | ค่า | ผลต่อการแปลง |
|---|---|---|
| `spark.sql.ansi.enabled` | `false` | `CAST` ที่แปลงไม่ได้ = NULL → ฝั่ง Oracle ใช้ `CAST(x AS T DEFAULT NULL ON CONVERSION ERROR)` ได้ (ต้องมี shape guard ตาม D-R8 ถ้า parse text เป็นวันที่) |
| | `true` | `CAST` ที่แปลงไม่ได้ **ล้มทั้งงาน** → ฝั่ง Oracle ใช้ `CAST` ธรรมดา (error เหมือนกัน) ห้ามใส่ `DEFAULT NULL ON CONVERSION ERROR` เพราะเปลี่ยนพฤติกรรมจาก "ล้ม" เป็น "ผ่านเงียบ" |
| `spark.sql.legacy.timeParserPolicy` | `EXCEPTION` | วันที่ผิดรูป → error (ล้มงาน) — ถ้า SQL มี shape guard แล้วแถวเหล่านั้นจะเข้าสาขา type-error แทนที่จะล้ม ความต่างนี้ต้องบันทึกเป็นความต่างที่ยอมรับ และทดสอบด้วยแถวผิดรูป (E7) |
| | `CORRECTED` | วันที่ผิดรูป = NULL → ตรงกับ `DEFAULT NULL ON CONVERSION ERROR` + shape guard |
| | `LEGACY` | parse แบบ lenient (ค่าที่ strict ปฏิเสธอาจ parse ได้) — Oracle จะต่าง ต้องบันทึกเป็นความต่างและทดสอบ |
| `spark.sql.parser.escapedStringLiterals` | `false` | Spark ตีความ `\` ใน string literal ก่อนส่งให้ regex — แปลง regex ตามสตริงที่ Spark ใช้จริงหลังตีความ ไม่ใช่ตามที่ตาเห็น |
| | `true` | literal ตรงตามตัวอักษร |
| `spark.sql.session.timeZone` | เช่น `Asia/Bangkok` | `now()`/`current_timestamp()` ใช้ timezone นี้ ส่วน `SYSDATE` ใช้นาฬิกาของเครื่อง DB — เทียบกับผล timezone ของ DB ที่ถามที่ I10 ข้อ 6 (`knowledge/reference/oracle-checks-and-spark-config.md` I2) ถ้าไม่ตรงต้องถามผู้ใช้ก่อน |
| `spark.sql.storeAssignmentPolicy` | เช่น `LEGACY` | กำหนดว่า `INSERT` จะ cast ชนิดข้อมูลให้เองแค่ไหน — ฝั่ง Oracle เป็นการแปลงโดยปริยายตามกติกาของ Oracle เอง ถ้าคอลัมน์ปลายทางชนิดต่างจากต้นทางให้ cast ชัดเจน และตรวจในชุดทดสอบ (ผลจริงของแต่ละค่าให้ตรวจกับเอกสารของ Spark เวอร์ชันที่ใช้ — เอกสารนี้ยังไม่ได้ยืนยันรายละเอียด) |
| `spark.sql.legacy.sizeOfNull` | `true`/`false` | ถ้า SQL ใช้ `size(...)`/`cardinality(...)` กับค่า NULL ผลต่างกัน (ตามเอกสารของ Spark: `true` คืน -1, `false` คืน NULL) — ตรวจกับเอกสารของเวอร์ชันที่ใช้ ถ้า SQL ไม่ใช้ฟังก์ชันนี้ ไม่ต้องสนใจ |

**ค่าที่ "ไม่ทราบ"** — ห้ามเดา บันทึกเป็นสมมติฐานที่ยังไม่ยืนยัน และบังคับให้ชุดทดสอบ E7 มีแถวขอบของเรื่องนั้น

## House style ของทีม

- ใช้ `NVL` เมื่อมี 2 argument, ใช้ `COALESCE` เมื่อ 3 ตัวขึ้นไป
- ชื่อตารางและ column เป็นตัวพิมพ์เล็กทั้งหมด **รวม prefix schema** (`dssdev.tb_xxx`)
- upsert เขียนเป็น `MERGE INTO tgt USING (…) ON (…) WHEN MATCHED … WHEN NOT MATCHED …`
- watermark ใช้ `DENSE_RANK` / `NTH_VALUE` แทน `MAX(partition)` เฉยๆ เพื่อไม่ให้ partition ที่มาช้าถูกข้าม
- overwrite กลายเป็น `TRUNCATE TABLE …` เป็นบรรทัดแรก แล้ว `INSERT` เป็นบรรทัดที่สอง
  (Oracle ไม่มี `INSERT OVERWRITE`) — เลข `OrdTrt` คือตำแหน่งบรรทัด builder ใส่ให้เอง
  ส่วน append/upsert มีบรรทัดเดียว จึงอยู่ที่บรรทัดแรกเหมือนกัน
  ⚠️ **ใช้ได้เฉพาะเมื่อ `sinkOption.partitions` ว่างเท่านั้น** — ดูหัวข้อ "overwrite ไม่ได้แปลว่า
  `TRUNCATE` ทั้งตารางเสมอไป" ด้านบน

⚠️ **ถ้าจะใช้เส้นทาง B (scripts) — แยกไฟล์ตั้งแต่ตอนแปลงนี้เลย ห้ามรวมทีหลัง**
`scripts/odi_builder/build_from_spec.py` (เรียกผ่าน `build_odi_export.py`) ต้องการ **1 command line ต่อ 1 ไฟล์ `.sql`** (ดู `README.md`
หัวข้อ "รูปแบบแผนการสร้าง") ทาสก์ที่เป็น overwrite (TRUNCATE + INSERT) ต้องได้ไฟล์แยก
`<task>_truncate.sql` กับ `<task>_insert.sql` ตั้งแต่แปลงเสร็จ **ห้ามเขียน TRUNCATE กับ INSERT
รวมไว้ไฟล์เดียวแล้วค่อยมาตัดแยกทีหลัง** — เคยทำแบบนั้นมาแล้วต้องเสียเวลาเขียนสคริปต์ตัดไฟล์
ย้อนหลังก่อนประกอบ spec ได้ **[เกิดขึ้นจริงมาแล้ว]** ทาสก์ที่เป็น append/upsert มีบรรทัดเดียวอยู่แล้ว
ไม่ต้องแยก

## ก่อนรับ SQL ที่แปลงแล้ว

1. ทุกเลข `[C#]` มีคำอธิบายกำกับว่าเปลี่ยนอะไร
2. ทุก column ที่โดน L19 ถูกเช็คชนิดจริงแล้ว ไม่ใช่เดา — ถ้าเช็คแล้วเป็น `DATE`/`TIMESTAMP`
   อยู่แล้ว ต้องไม่มี `TO_DATE`/`TO_TIMESTAMP` ห่ออยู่เลย (ดูกฎ D-R6)
3. พฤติกรรมของ Spark ที่จงใจคงไว้ไม่แก้ (เช่นเรื่องเว้นวรรคใน L20, ลำดับ dedup ที่มี NULL) ต้องบอกผู้ใช้ — เอกสารเทสของงานพวกนี้มักเขียน quirk พวกนี้ไว้เป็นผลลัพธ์ที่คาดหวัง การ "แก้ให้" เงียบๆ จะทำให้จำนวนแถวที่คาดหวังเพี้ยน
4. เช็ค `NULLS FIRST`/`NULLS LAST` ทุกที่ที่ dedup ขึ้นกับ `ORDER BY` — Oracle กับ Spark ต่างกัน และผู้ชนะของ `ROW_NUMBER()` เปลี่ยนตามนั้น
5. รัน SQL จริงกับ Oracle dev ก่อนเอาไปห่อเป็น Procedure — ตัว import ตรวจโครงสร้าง ไม่ได้ตรวจ SQL ถ้าผิดจะไปโผล่ตอนรัน
6. **ถ้าใช้เส้นทาง B:** ไฟล์ `.sql` ที่จะอ้างใน `procedures[].lines[].sql_file` ต้องเป็นไฟล์ต่อ
   1 command line แล้ว (ดูคำเตือนด้านบน) ก่อนเริ่มประกอบ `spec.json`
7. **ทุก `INSERT` มี column list ครบ** (D-R1) และจำนวนชื่อในลิสต์เท่ากับจำนวน expression
   ชั้นนอกของ `SELECT` — **ถ้าไม่ผ่านข้อนี้ห้ามรับงานแปลง**
8. **ทุก column list เทียบกับ `all_tab_columns` ของตารางจริงแล้ว** (เฉพาะตารางที่มี DDL จาก I3)
   และแนบผลการเทียบมาด้วย คอลัมน์ที่ไม่ได้ระบุต้อง nullable หรือมี DEFAULT — **ตารางที่ใช้โหมดเดา
   ข้ามข้อนี้ไม่ได้ด้วยการแกล้งบอกว่า "เทียบแล้ว"** ต้องรายงานว่า "เดา — ยังไม่ยืนยัน" แทน
9. **ชื่อตารางทุกตัว qualify ด้วย schema แล้ว** (D-R2) ไม่เหลือชื่อเปล่าสักตัว ยกเว้น `DUAL`
   alias และ CTE
10. รัน `python scripts/checks/check_sql.py <โฟลเดอร์ sql> --ddl <DDL จาก I3>` แล้วไม่มี `[ERROR]` เหลือ
    (ถ้ารัน python ได้) — คำสั่งเดียวกันนี้ตรวจ D-R4 (checklist ข้อ 50) ให้อัตโนมัติเสมอ ไม่ต้องมี
    `--ddl` และตรวจ D-R5 (checklist ข้อ 51) ให้ด้วยถ้า DDL มีคอลัมน์ `DATA_TYPE` — ถ้าตารางไหน
    เลือกโหมดเดา ให้รันโดยไม่ใส่ `--ddl` ของตารางนั้น (หรือไม่ใส่ `--ddl` เลยถ้าทั้งหมดเป็นโหมดเดา)
    แล้วรู้ไว้ว่า `ORA-00904`, `ORA-01400` และ `ORA-01790` ของใบนั้นยังไม่ถูกตรวจโดยเครื่องมือ —
    ต้องพึ่งการเปิดเผยในรายงานปิดงานแทน
    ⚠️ **อ่านบรรทัดที่สคริปต์พิมพ์ตอนโหลด DDL ด้วย** มันจะบอกว่า checklist ข้อ 32/33/51 เปิดจริงไหม
    ไฟล์ DDL ที่ไม่มีคอลัมน์ `NULLABLE` จะทำให้ข้อ 33 (`ORA-01400`) ปิดไปโดยปริยาย และไม่มีคอลัมน์
    `DATA_TYPE` จะทำให้ข้อ 51 (`ORA-01790`) ปิดไปโดยปริยายเช่นกัน
11. **ทุก `MERGE` ยืนยันแล้วว่า subquery ใน `USING` คืนหนึ่งแถวต่อหนึ่งคีย์** (`knowledge/lessons-learned.md` L31)
    และประโยค `INSERT` ข้างในมี column list ครบเหมือน `INSERT INTO` ทั่วไป
12. **ไม่มี `;` ปิดท้ายไฟล์ และหนึ่งไฟล์มี statement เดียว** (D-R3) — ไฟล์ที่เทสใน SQL Developer
    มาแล้วมักติด `;` มาด้วย ต้องตัดออกก่อนส่ง
13. **`TO_DATE` / `TO_CHAR` / `TO_TIMESTAMP` / `TO_NUMBER` ทุกจุดมี format mask ที่ถูกกับชนิด
    จริงของคอลัมน์** (ไม่ใช่แค่ "มี mask" — คอลัมน์ที่เป็น `DATE`/`TIMESTAMP` อยู่แล้วต้องไม่ถูกห่อ
    ด้วย `TO_DATE`/`TO_TIMESTAMP` เลย ดูกฎ **D-R6**) และไม่มีการเทียบ string กับคอลัมน์ `DATE`
    ตรงๆ (`knowledge/lessons-learned.md` L30 · `delivery-checklist.md` ข้อ 43) — `check_sql.py` ตรวจให้อัตโนมัติได้แค่
    `TO_DATE`/`TO_TIMESTAMP` เท่านั้น (ชั้นที่ 2 ต้องมี `--ddl`) ส่วน `TO_CHAR`/`TO_NUMBER`
    แบบ 1 argument ยังต้องตรวจด้วยตาเสมอ
14. **ทาสก์ overwrite ทุกตัวอ่าน `sinkOption.partitions` แล้ว** และใบที่ไม่ว่างได้คำตอบจากผู้ใช้
    ว่าจะเคลียร์ข้อมูลด้วยวิธีไหน (`knowledge/lessons-learned.md` L29 · `delivery-checklist.md` ข้อ 41)
    — **ข้อนี้ห้ามข้าม ย้อนกลับไม่ได้**
15. **scalar subquery ทุกก้อนถูกระบุไว้ในรายงานปิดงานว่ายังไม่ได้ทดสอบครบทุกสภาพข้อมูล** —
    ไม่มีเครื่องมือไหนบอกได้ว่ามันจะคืนมากกว่าหนึ่งแถวเมื่อไร ต้องอาศัย `knowledge/reference/validation-and-cutover.md` ระดับ 3–4
    (`knowledge/lessons-learned.md` L31 — `ORA-01427`)
16. **alias ทุกตัวที่ตั้งเอง (table alias, subquery alias, ชื่อ CTE) เช็คกับ Oracle Reserved
    Words list แล้ว** (D-R4) — คนละรายการกับชื่อคอลัมน์ เพราะ alias ไม่ได้มาจาก DDL
    (`knowledge/lessons-learned.md` L27 · `delivery-checklist.md` ข้อ 50)
17. **ทุก `UNION`/`UNION ALL` ที่รวมคอลัมน์ชื่อเดียวกันจากคนละตาราง เทียบ datatype จาก DDL
    แล้ว** (D-R5) และ cast ฝั่งที่เป็น LOB ด้วย `TO_CHAR()` ก่อนเข้า `UNION` ถ้า mismatch —
    ตรวจด้วยว่าเนื้อหาจริงไม่มีทางยาวเกิน limit ที่ `TO_CHAR` แปลงได้ (`knowledge/lessons-learned.md` L28 ·
    checklist ข้อ 51)
18. **ทุกจุดที่ parse text เป็นวันที่/เวลาด้วย `TO_TIMESTAMP`/`TO_DATE` มี `REGEXP_LIKE` shape guard** และข้อมูลทดสอบ
    มีแถวที่ค่าสั้นกว่า pattern (D-R8 · `knowledge/lessons-learned.md` L34 · `delivery-checklist.md` ข้อ 53) —
    `check_sql.py` 1.7.0 เตือนเป็น `[WARN]` ให้ แต่ตรวจระดับ statement ต้องไล่ตาซ้ำ
