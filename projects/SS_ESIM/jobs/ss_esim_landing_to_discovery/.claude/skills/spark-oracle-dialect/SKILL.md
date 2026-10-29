---
name: spark-oracle-dialect
description: ตาราง mapping Spark SQL (Blendata) → Oracle 19c พร้อม edge case ของ semantics (NULL vs '', ANSI mode, time parser, escaped literals, integer division, implicit cast) — ใช้เมื่อแปลง/รีวิว SQL ใน Phase 4 หรือเมื่อ sql-reviewer / semantic-verifier / conversion-auditor ต้องการ reference กลาง
---
# Spark SQL → Oracle 19c — reference สำหรับ Phase 4

ใช้คู่กับ `.claude/rules/odi-step-sql.md` · ผลของ Spark ขึ้นกับ config ใน Q "Spark config" (หัวข้อ Spark config ใน `status/PHASE4_REVIEW_LOG.md`) — ถ้ายังไม่ยืนยัน ให้ระบุว่า "ขึ้นกับ config"

## 1. Semantics ที่ต่างโดยไม่มี error (อันตรายที่สุด)

| หัวข้อ | Spark | Oracle | ทำอย่างไร |
|---|---|---|---|
| empty string | `''` ≠ NULL | `''` = NULL | `col = ''` → `col IS NULL`; `col <> ''` ใน Spark ไม่รวม NULL แต่รวม `' '` — แปลงเป็น `col IS NOT NULL` แล้วยืนยันว่า landing มี `''` หรือไม่ |
| `concat(a, b)` | NULL ถ้ามีตัวใด NULL | `a \|\| b` ข้าม NULL | ถ้าต้องการผลแบบ Spark: `CASE WHEN a IS NULL OR b IS NULL THEN NULL ELSE a \|\| b END` |
| `concat_ws(sep, …)` | ข้าม NULL | — | ต่อด้วย `\|\|` + `NVL2` ต่อ argument |
| integer division `a / b` | double เสมอ | NUMBER (ทศนิยม) | ปกติเท่ากัน; `a DIV b` → `TRUNC(a / b)` |
| `x / 0` | NULL (ANSI off) / error (ANSI on) | ORA-01476 | `x / NULLIF(0, 0)` → NULL |
| string compare | case-sensitive, binary | ขึ้นกับ `NLS_COMP`/`NLS_SORT` (ปกติ binary) | ตรวจ NLS จาก `/preflight` P1 |
| trailing space | `'a ' <> 'a'` | VARCHAR2 เหมือน Spark; CHAR pad | ระวังคอลัมน์ CHAR |
| `round(x, n)` | HALF_UP | HALF_UP สำหรับ NUMBER, BINARY_DOUBLE = banker's | ใช้ NUMBER |
| `current_timestamp()` / `now()` | session timezone Spark (`spark.sql.session.timeZone`) | `SYSTIMESTAMP` = timezone ของ DB server, `CURRENT_TIMESTAMP` = session | ยืนยัน timezone (L10) |
| `substring(s, 0, n)` | pos 0 = 1 | `SUBSTR(s, 0, n)` = 1 เช่นกัน | เท่ากัน; ติดลบ = นับจากท้ายทั้งคู่ |
| `length()` | จำนวนตัวอักษร | `LENGTH` ตัวอักษร / `LENGTHB` byte | DDL: `VARCHAR2(n CHAR)` ถ้ามีภาษาไทย |
| boolean | `true/false` | ไม่มี BOOLEAN ใน SQL 19c | `'Y'/'N'` หรือ `1/0` — ต้องตกลงชนิดกับ downstream (Q) |
| `ROW_NUMBER() ORDER BY` ไม่ unique | ลำดับไม่แน่นอน | ไม่แน่นอนเช่นกัน | เพิ่ม tie-breaker ทั้งสองฝั่งหรือบันทึกเป็นความเสี่ยง |
| `GROUP BY` / `DISTINCT` กับ NULL | NULL เป็นกลุ่มเดียว | เหมือนกัน | — |
| `OR` / `CASE` short-circuit | ไม่รับประกัน | ไม่รับประกัน | ห้ามพึ่งลำดับเพื่อกัน error (`TO_NUMBER` ใน WHERE) |

## 2. ขึ้นกับ Spark config (L7–L9)

| config | ค่า | ผลต่อการแปลง |
|---|---|---|
| `spark.sql.ansi.enabled` | false (default ≤3.x) | CAST ที่แปลงไม่ได้ = NULL → Oracle `CAST(x AS T DEFAULT NULL ON CONVERSION ERROR)` / `VALIDATE_CONVERSION` |
| | true | CAST ผิด = **ล้มทั้งรอบ** → Oracle `CAST` ธรรมดา (error เหมือนกัน) — ห้ามใส่ DEFAULT NULL เพราะเปลี่ยนพฤติกรรม |
| `spark.sql.legacy.timeParserPolicy` | EXCEPTION (default 3.x) | วันที่ผิดรูป → error ทั้ง workflow |
| | LEGACY | parse แบบ lenient (SimpleDateFormat) — `2024-2-30` ได้ค่า → Oracle strict จะ error/NULL = DIFF |
| | CORRECTED | ผิดรูป = NULL → `TO_DATE(x DEFAULT NULL ON CONVERSION ERROR, fmt)` |
| `spark.sql.parser.escapedStringLiterals` | false (default) | Spark ตีความ `\` ใน literal → `'\\d'` = `\d`; `'\S'` = `S` (backslash หาย!) → regex ใน Oracle ต้องใช้สตริงหลังตีความ |
| | true | literal ตรงตามตัวอักษร |

## 3. ฟังก์ชัน

| Spark | Oracle 19c | หมายเหตุ |
|---|---|---|
| `nvl(a,b)` / `coalesce` / `ifnull` | `NVL` / `COALESCE` | NVL ประเมินทั้งสองข้าง |
| `nvl2(a,b,c)` | `NVL2(a,b,c)` | มีใน Oracle (V1 flag เพื่อให้ตรวจชนิด) |
| `if(c, a, b)` | `CASE WHEN c THEN a ELSE b END` | |
| `date_format(ts, 'yyyy-MM-dd HH:mm:ss')` | `TO_CHAR(ts, 'YYYY-MM-DD HH24:MI:SS')` | `mm`=นาทีใน Spark, `MM`=เดือน · `SSS` → `FF3` |
| `to_date(s, 'yyyyMMdd')` | `TO_DATE(s, 'YYYYMMDD')` | ดูชนิดจริงของ s ก่อน (L1) |
| `to_timestamp(s, fmt)` | `TO_TIMESTAMP(s, fmt)` | s เป็น TIMESTAMP อยู่แล้ว = ห้ามครอบ (V6) |
| `unix_timestamp(ts)` | `(CAST(ts AS DATE) - DATE '1970-01-01') * 86400` | timezone! |
| `from_unixtime(n)` | `DATE '1970-01-01' + n/86400` | |
| `date_add(d, n)` / `date_sub` | `d + n` / `d - n` | Spark คืน DATE (ตัดเวลา) → `TRUNC(d) + n` |
| `datediff(a, b)` | `TRUNC(a) - TRUNC(b)` | |
| `add_months` / `last_day` / `trunc(d,'MM')` | เหมือนกัน (`TRUNC(d,'MM')`) | |
| `regexp_extract(s, p, i)` | `REGEXP_SUBSTR(s, p, 1, 1, NULL, i)` | ไม่เจอ: Spark `''` / Oracle NULL |
| `regexp_replace` / `rlike` | `REGEXP_REPLACE` / `REGEXP_LIKE` | syntax POSIX ต่างจาก Java (lookahead, `\d` ใช้ได้, `(?i)` → match param `'i'`) |
| `split(s, p)[i]` | `REGEXP_SUBSTR(s, '[^'||p||']+', 1, i+1)` | index Spark เริ่ม 0 · ช่องว่างระหว่าง delimiter หาย |
| `explode` / `LATERAL VIEW` | `CROSS APPLY` / `JSON_TABLE` | ต้องออกแบบใหม่ → flag |
| `collect_list` / `collect_set` | `LISTAGG(... ) WITHIN GROUP` / `LISTAGG(DISTINCT ...)` | ลำดับ/ความยาว 4000 |
| `a <=> b` | `DECODE(a, b, 1, 0) = 1` | null-safe equal |
| `CAST(x AS string/long/int/double)` | `TO_CHAR` / `CAST AS NUMBER(19)` / `NUMBER(10)` / `BINARY_DOUBLE` | |
| `LIMIT n` | `FETCH FIRST n ROWS ONLY` | |
| `INSERT OVERWRITE t` | TRUNCATE step + `INSERT` (gen_dml ทำให้) | |
| `` `col` `` | `"COL"` หรือไม่ quote | quote = case-sensitive |
| `md5(s)` | `STANDARD_HASH(s, 'MD5')` (RAW → `LOWER(RAWTOHEX(...))`) | normalize NULL ก่อน |

## 4. เช็กลิสต์ต่อ task

1. ชนิดจริงของทุกคอลัมน์ที่อ่าน (P3) · 2. ทุก `''` / `<> ''` / `concat` · 3. ทุก CAST / TO_DATE ภายใต้ ANSI + timeParserPolicy · 4. regex literal ภายใต้ escapedStringLiterals · 5. timezone ของ now() · 6. ความ deterministic ของ window/dedup · 7. บันทึกทุกข้อใน `status/PHASE4_REVIEW_LOG.md`

## 5. กฎแปลงแบบเต็ม

กฎ D-R1–D-R8 และตัวอย่างอยู่ที่ `knowledge/reference/spark-to-oracle-sql.md` · ตรวจอัตโนมัติด้วย `python scripts/checks/check_sql.py <โฟลเดอร์>` (คำสั่ง `/sql-check`)
