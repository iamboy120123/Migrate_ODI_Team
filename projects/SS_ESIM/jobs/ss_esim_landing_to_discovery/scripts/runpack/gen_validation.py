"""
gen_validation.py
------------------
Runbook Phase 7 (Pre-Cutover Validation - 3 ระดับ)

หน้าที่:
    generate query คู่ (Blendata/Spark SQL  vs  Oracle 19c) สำหรับเทียบผลลัพธ์
    หลังรัน ODI Package บน Oracle แล้ว ให้รันทั้งสองฝั่งด้วย "หน้าต่างข้อมูลเดียวกัน"
    แล้ว diff ผลลัพธ์ทีละระดับ:

        L1 Row Count      - จำนวนแถวรวม + แยกตาม partition_date
        L2 Column Profile - ต่อคอลัมน์: non-null count, distinct count (+ MD5 row hash)
        L3 Business Rule  - กฎเชิงธุรกิจที่ต้องเท่ากันเป๊ะ (status distribution, dedup,
                            checkpoint continuity, และเคส known-difference จาก D1)

    ** L1/L2 ที่ไม่ตรงคือ "หยุดแล้วหาสาเหตุ" ไม่ใช่ปรับ threshold **

ข้อควรทราบเรื่อง L2 row hash:
    Spark `md5(...)` กับ Oracle `STANDARD_HASH(..., 'MD5')` ให้ค่าเท่ากันได้
    ก็ต่อเมื่อ "สตริงที่ป้อนเข้าไปเหมือนกันทุก byte" ซึ่งต้อง normalize ก่อน:
      - NULL -> '' ทั้งสองฝั่ง (Spark concat คืน NULL ถ้ามี arg NULL, Oracle || ไม่คืน)
      - ตัวเลข/วันที่ -> แปลงเป็น string ด้วย format เดียวกัน
    script นี้ generate ให้ในรูปแบบที่ normalize แล้ว แต่ SA ต้องตรวจ format ของ
    คอลัมน์ชนิด DATE/TIMESTAMP/NUMBER เป็นราย ๆ ก่อนเชื่อผล

Usage:
    python scripts/runpack/gen_validation.py [--config config/config.json]
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

# ตารางที่ทำ L2 (profile ระดับคอลัมน์) — อ่านจาก config/validation_rules.json "l2_tables"
# ถ้าไม่มี: ใช้ target ที่ชื่อลงท้าย _VALID / _REJECT (ตาราง transaction ที่มีข้อมูลจริง)
L2_TABLES = set()


def src_name(target_table: str) -> str:
    """MYSCHEMA.TB_X -> tb_x (ชื่อตารางฝั่ง Blendata)"""
    return target_table.rsplit(".", 1)[-1].lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    mpath = Path(config["paths"]["dml_manifest"])
    if not mpath.exists():
        sys.exit(f"[ERROR] ไม่พบ {mpath} - รัน gen_dml.py ก่อน")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    # entry readonly (เช่น 000000 precheck) ไม่ได้เขียน target -> ไม่นับเป็น target table
    manifest = [e for e in manifest if not e.get("readonly")]
    vpath = Path(config.get("paths", {}).get("validation_rules", "config/validation_rules.json"))
    vrules = json.loads(vpath.read_text(encoding="utf-8")) if vpath.exists() else {}
    L2_TABLES.update(t.upper() for t in vrules.get("l2_tables", []))

    out = Path("output/validation")
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().isoformat(timespec="seconds")

    # dedupe target + เก็บ column list ที่ยาวที่สุดของแต่ละตาราง
    tables = {}
    for e in manifest:
        t = e["target_table"]
        if t not in tables or len(e["columns"]) > len(tables[t]):
            tables[t] = e["columns"]
    if not L2_TABLES:
        L2_TABLES.update(src_name(t).upper() for t in tables if src_name(t).upper().endswith(("_VALID", "_REJECT")))

    hdr = lambda side, lvl: (
        f"-- {lvl} ({side})  generated {stamp}\n"
        f"-- รันด้วยหน้าต่างข้อมูลเดียวกันทั้งสองฝั่ง แล้ว diff ผลลัพธ์\n"
        f"-- &WF_DATE = workflow_process_date ของรอบที่ต้องการเทียบ (เช่น 20260922093000)\n\n"
    )

    # ---------------- L1: row count ----------------
    ora, spk = [hdr("Oracle 19c", "L1 Row Count")], [hdr("Blendata / Spark SQL", "L1 Row Count")]
    for t, cols in tables.items():
        s = src_name(t)
        has_wf = "WORKFLOW_PROCESS_DATE" in cols
        has_pd = "PARTITION_DATE" in cols
        where_o = " WHERE workflow_process_date = '&WF_DATE'" if has_wf else ""
        ora.append(f"SELECT '{s}' AS tbl, COUNT(*) AS row_cnt FROM {t}{where_o};")
        spk.append(f"SELECT '{s}' AS tbl, COUNT(*) AS row_cnt FROM {s}{where_o};")
        if has_pd:
            grp = (f"SELECT '{s}' AS tbl, partition_date, COUNT(*) AS row_cnt\n"
                   f"FROM   {{tbl}}{where_o}\nGROUP  BY partition_date ORDER BY partition_date;")
            ora.append(grp.format(tbl=t))
            spk.append(grp.format(tbl=s))
        ora.append("")
        spk.append("")
    (out / "L1_row_count_oracle.sql").write_text("\n".join(ora), encoding="utf-8")
    (out / "L1_row_count_spark.sql").write_text("\n".join(spk), encoding="utf-8")

    # ---------------- L2: column profile + row hash ----------------
    ora, spk = [hdr("Oracle 19c", "L2 Column Profile")], [hdr("Blendata / Spark SQL", "L2 Column Profile")]
    for t, cols in tables.items():
        s = src_name(t)
        if s.upper() not in L2_TABLES:
            continue
        has_wf = "WORKFLOW_PROCESS_DATE" in cols
        where = " WHERE workflow_process_date = '&WF_DATE'" if has_wf else ""

        # per-column: non-null count + distinct count  (type-agnostic เทียบได้ทุก engine)
        sel = ",\n       ".join(
            f"COUNT({c}) AS nn_{c.lower()}, COUNT(DISTINCT {c}) AS dc_{c.lower()}" for c in cols
        )
        ora.append(f"-- {s}: per-column profile\nSELECT COUNT(*) AS row_cnt,\n       {sel}\nFROM   {t}{where};\n")
        spk.append(f"-- {s}: per-column profile\nSELECT COUNT(*) AS row_cnt,\n       {sel}\nFROM   {s}{where};\n")

        # row hash: normalize NULL -> '' แล้ว MD5 ต่อแถว, รวมด้วย COUNT(DISTINCT)
        ora_cat = " || '|' || ".join(f"NVL(TO_CHAR({c}), '')" for c in cols)
        # concat_ws ใส่ separator ให้เองแล้ว ห้ามแทรก '|' ซ้ำ (จะได้ '||' ไม่ตรงกับฝั่ง Oracle)
        spk_cat = ", ".join(f"coalesce(cast({c} as string), '')" for c in cols)
        ora.append(
            f"-- {s}: row hash (ต้องตรวจ format ของคอลัมน์ DATE/NUMBER ก่อนเชื่อผล)\n"
            f"SELECT COUNT(DISTINCT STANDARD_HASH({ora_cat}, 'MD5')) AS distinct_row_hash,\n"
            f"       COUNT(*) AS row_cnt\nFROM   {t}{where};\n")
        spk.append(
            f"-- {s}: row hash (ต้องตรวจ format ของคอลัมน์ DATE/NUMBER ก่อนเชื่อผล)\n"
            f"SELECT COUNT(DISTINCT md5(concat_ws('|', {spk_cat}))) AS distinct_row_hash,\n"
            f"       COUNT(*) AS row_cnt\nFROM   {s}{where};\n")
    (out / "L2_column_profile_oracle.sql").write_text("\n".join(ora), encoding="utf-8")
    (out / "L2_column_profile_spark.sql").write_text("\n".join(spk), encoding="utf-8")

    # ---------------- L3: business rules ----------------
    # L3: business rules ของ workflow อ่านจาก config/validation_rules.json (kit 2.3.0 — K3 ย้ายออกจาก script)
    #     {"rules": [{"name", "desc", "oracle", "spark"|null, "expected"}]} · {p} = schema prefix
    rules = [(r["name"], r.get("desc", ""), r["oracle"], r.get("spark"), r.get("expected", ""))
             for r in vrules.get("rules", [])]
    if not rules:
        print("[WARN] ไม่มี L3 rules — เขียนกฎใน config/validation_rules.json (ดูตัวอย่างใน config/config.example.json หรือโปรเจกต์ก่อน)")
    ora_prefix = (config.get("target_table_prefix") or "").upper()
    for side, prefix, fname in (("Oracle 19c", ora_prefix, "L3_business_rules_oracle.sql"),
                                ("Blendata / Spark SQL", "", "L3_business_rules_spark.sql")):
        L = [hdr(side, "L3 Business Rules")]
        for name, desc, sql_ora, sql_spk, expect in rules:
            sql = sql_ora if (side.startswith("Oracle") or not sql_spk) else sql_spk
            if not side.startswith("Oracle"):
                sql = sql.replace(" FROM dual", "")
            L += [f"-- {'='*70}", f"-- {name}", f"-- {desc}", f"-- EXPECTED: {expect}",
                  f"-- {'='*70}", sql.format(p=prefix), ""]
        (out / fname).write_text("\n".join(L), encoding="utf-8")

    rd = [f"# Phase 7 — Pre-Cutover Validation ({config.get('project_name','')})", "",
          f"Generated: {stamp}", "",
          "## วิธีใช้", "",
          "1. รัน ODI Package บน Oracle ให้จบ 1 รอบ จด `workflow_process_date` ของรอบนั้น",
          "2. รันฝั่ง Blendata ด้วยหน้าต่างข้อมูลเดียวกัน (checkpoint ช่วงเดียวกัน)",
          "3. รันไฟล์คู่ L1 → L2 → L3 แล้ว diff ผล **ห้ามข้ามระดับ**",
          "4. L1 หรือ L2 ไม่ตรง = หยุดแล้วหาสาเหตุ ไม่ใช่ปรับ threshold", "",
          "## ไฟล์", "",
          "| ระดับ | Oracle | Blendata |", "|---|---|---|",
          "| L1 Row Count | `L1_row_count_oracle.sql` | `L1_row_count_spark.sql` |",
          "| L2 Column Profile | `L2_column_profile_oracle.sql` | `L2_column_profile_spark.sql` |",
          "| L3 Business Rules | `L3_business_rules_oracle.sql` | `L3_business_rules_spark.sql` |", "",
          "## ⚠️ ข้อจำกัดที่ต้องรู้ก่อนอ่านผล", "",
          "- **R3 อาจไม่ตรง** — known difference Q6 (empty string = NULL ใน Oracle → MAN) ใช้ยืนยันขนาดผลกระทบ",
          "- **cdr_id เทียบค่าไม่ได้** — generate ใหม่ทุก run เทียบได้แค่ format และจำนวน; raw_temp ว่างหลังจบรอบ (070200 TRUNCATE) จึงตรวจจาก valid/reject",
          "- **row hash (L2)** — Spark `md5()` กับ Oracle `STANDARD_HASH(...,'MD5')` เท่ากันได้ต่อเมื่อ",
          "  string ที่ป้อนเหมือนกันทุก byte ต้องตรวจ format ของคอลัมน์ DATE/TIMESTAMP/NUMBER ก่อน",
          "  ถ้าไม่มั่นใจ ให้ยึด per-column profile (non-null + distinct) เป็นหลัก",
          "- **`SYSDATE` ต่างกันทุก run** — `process_date` จะไม่มีวันเท่ากัน อย่าใส่ใน hash ที่คาดว่าจะตรง",
          ""]
    (out / "README.md").write_text("\n".join(rd), encoding="utf-8")

    print(f"[OK] L1: {len(tables)} ตาราง")
    print(f"[OK] L2: {len([t for t in tables if src_name(t).upper() in L2_TABLES])} ตาราง")
    print(f"[OK] L3: {len(rules)} rules")
    print(f"[OK] output/validation/ (7 ไฟล์)")


if __name__ == "__main__":
    main()
