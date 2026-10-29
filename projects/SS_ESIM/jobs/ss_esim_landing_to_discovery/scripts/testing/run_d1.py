"""
run_d1.py  (kit K14, 2026-10-01) — D1 differential test: รัน raw Spark SQL ของ workflow บน PySpark
ด้วย seed เดียวกันในทุกค่า Spark config ที่มีผลต่อ semantics (matrix) แล้วรายงานว่าผลของแต่ละ task
**คงที่ทุก config หรือไม่** (เงื่อนไขของ Q3 = B / waiver ของ G2) และเก็บผลไว้เทียบกับ Oracle (D2)

ใช้เมื่อ: ยังไม่รู้ Spark config ของ Blendata และอยากรู้ว่ากฎแปลงเสี่ยงไหม (ขั้น 1 ของ test-method)

ทำไม: เมื่อไม่รู้ค่า spark.sql.ansi.enabled / legacy.timeParserPolicy / parser.escapedStringLiterals
ของ Blendata กฎแปลงจะถือว่าถูกได้เฉพาะเมื่อผลของ Spark เหมือนกันทุกแบบ (task ที่ผลต่างกัน = ต้องยืนยัน config)

Input (ระดับโปรเจกต์):
    input/d1_spec.json      ลำดับ task, sink mode, ค่า freeze now(), UDF ที่ต้องแทน, คอลัมน์ที่ไม่เทียบ, matrix, type override
    input/d1_seeds/<table>.csv   seed ต่อตาราง (header = ชื่อคอลัมน์, ค่า \\N = NULL, ช่องว่าง = '')
    schema_csv (ผล all_tab_columns เช่น rp00 P3.csv)   ใช้กำหนดชนิดของ seed
Output:
    output/d1/<combo>/<task>.csv     ผลของแต่ละ task ต่อ config
    output/d1/D1_REPORT.md           ตาราง task × combo (hash ของผล / error) + สรุป STABLE / CONFIG-DEPENDENT / ERROR

Usage:
    python scripts/testing/run_d1.py [--spec input/d1_spec.json] [--only 040000,050100]
ต้องมี PySpark (pip install pyspark) + Java 11/17 · บน VM ที่ resolve hostname ไม่ได้ให้ตั้ง SPARK_LOCAL_IP=127.0.0.1
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")
os.environ.setdefault("SPARK_LOCAL_HOSTNAME", "localhost")


def ora_to_spark(dtype: str, prec: str, scale: str) -> str:
    t = (dtype or "").upper()
    if t.startswith(("VARCHAR", "CHAR", "NVARCHAR", "NCHAR", "CLOB", "NCLOB")):
        return "string"
    if t.startswith(("TIMESTAMP", "DATE")):
        return "timestamp"
    if t == "NUMBER":
        p = int(prec) if (prec or "").strip() else None
        s = int(scale) if (scale or "").strip() else 0
        if p is None:
            return "double"
        if s == 0:
            return "int" if p <= 9 else "bigint" if p <= 19 else f"decimal({p},0)"
        return f"decimal({p},{s})"
    if t.startswith(("BINARY_DOUBLE", "FLOAT", "BINARY_FLOAT")):
        return "double"
    return "string"


def load_schema(path: Path, overrides: dict) -> dict:
    """{table_lower: [(col_lower, spark_type)]} จาก all_tab_columns CSV"""
    out = {}
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    rows.sort(key=lambda r: (r["TABLE_NAME"], int(r.get("COLUMN_ID") or 0) if (r.get("COLUMN_ID") or "").strip().isdigit() else 0))
    for r in rows:
        if r["COLUMN_NAME"].strip() == "MISSING_OBJECT":
            continue
        t, c = r["TABLE_NAME"].strip().lower(), r["COLUMN_NAME"].strip().lower()
        st = overrides.get(f"{t}.{c}") or ora_to_spark(r["DATA_TYPE"], r.get("DATA_PRECISION", ""), r.get("DATA_SCALE", ""))
        out.setdefault(t, []).append((c, st))
    return out


def prepare_sql(sql: str, spec: dict) -> str:
    fz = spec.get("freeze_now")
    if fz:
        sql = re.sub(r"\b(now|current_timestamp)\s*\(\s*\)", f"timestamp'{fz}'", sql, flags=re.I)
    for a, b in (spec.get("replace") or {}).items():
        sql = sql.replace(a, b)
    return sql


def canon(df, ignore):
    cols = [c for c in df.columns if c.lower() not in ignore]
    # cast เป็น string ใน Spark (session timezone) — ไม่ให้ timezone ของเครื่องที่รันเปลี่ยนค่า timestamp
    rows = sorted(tuple("\\N" if v is None else v for v in r)
                  for r in df.selectExpr(*[f"CAST(`{c}` AS STRING) AS `{c}`" for c in cols]).collect())
    h = hashlib.sha1(json.dumps([cols, rows]).encode()).hexdigest()[:10]
    return cols, rows, h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default="input/d1_spec.json")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    spec = json.loads((ROOT / a.spec).read_text(encoding="utf-8"))
    cfg = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / cfg["paths"]["raw_manifest"]).read_text(encoding="utf-8"))
    by_code = {m["task_name"][:6]: m for m in manifest if m.get("raw_sql_file")}
    order = [str(c) for c in spec["order"]]
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    ignore = {c.lower() for c in spec.get("ignore_columns", [])}
    schema = load_schema(ROOT / spec["schema_csv"], spec.get("type_overrides") or {})
    seeds_dir = ROOT / spec.get("seeds_dir", "input/d1_seeds")
    matrix = spec["matrix"]
    keys = list(matrix)
    combos = [dict(zip(keys, v)) for v in product(*[matrix[k] for k in keys])]

    from pyspark.sql import SparkSession, functions as F
    spark = (SparkSession.builder.master("local[1]").appName("d1")
             .config("spark.ui.enabled", "false").config("spark.driver.host", "127.0.0.1")
             .config("spark.sql.session.timeZone", spec.get("timezone", "UTC"))
             .config("spark.sql.shuffle.partitions", "1").getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    def seed_tables():
        for t, cols in schema.items():
            ddl = ", ".join(f"`{c}` {st}" for c, st in cols)
            f = seeds_dir / f"{t}.csv"
            if f.exists():
                raw = spark.read.option("header", True).option("nullValue", "\\N").option("emptyValue", "") \
                    .option("inferSchema", False).csv(str(f))
                exprs = [(F.col(c).cast(st) if c in raw.columns else F.lit(None).cast(st)).alias(c) for c, st in cols]
                df = raw.select(*exprs)
            else:
                df = spark.createDataFrame([], ddl)
            df.createOrReplaceTempView(t)

    out_dir = ROOT / "output" / "d1"
    results = {}   # code -> {combo_id: hash | 'ERR: ..'}
    for ci, combo in enumerate(combos):
        cid = "-".join(f"{k.split('.')[-1]}={v}" for k, v in combo.items())
        for k, v in combo.items():
            spark.conf.set(k, v)
        seed_tables()
        failed = None
        for code in order:
            tr = (spec.get("truncate_tasks") or {}).get(code)
            if tr:
                cur = spark.table(tr)
                spark.createDataFrame([], cur.schema).createOrReplaceTempView(tr)
                continue
            m = by_code.get(code)
            if not m:
                continue
            if failed:
                results.setdefault(code, {})[cid] = f"SKIP (หลัง {failed} ล้ม)"
                continue
            sql = prepare_sql((ROOT / m["raw_sql_file"]).read_text(encoding="utf-8"), spec)
            target = (m.get("target_table") or "").lower()
            mode = (spec.get("sink_mode") or {}).get(code) or m.get("sink_mode") or "Overwrite"
            try:
                df = spark.sql(sql)
                if target in [t.name for t in spark.catalog.listTables()]:
                    cur = spark.table(target)
                    types = dict(cur.dtypes)
                    df = df.select(*[(F.col(c).cast(types[c]) if c in types else F.col(c)).alias(c) for c in df.columns])
                    if mode.lower().startswith("append"):
                        df = cur.unionByName(df, allowMissingColumns=True)
                df = df.localCheckpoint(eager=True)
                df.createOrReplaceTempView(target)
                cols, rows, h = canon(df, ignore)
                if not only or code in only:
                    d = out_dir / cid
                    d.mkdir(parents=True, exist_ok=True)
                    with open(d / f"{code}.csv", "w", newline="", encoding="utf-8") as fh:
                        w = csv.writer(fh); w.writerow(cols); w.writerows(rows)
                results.setdefault(code, {})[cid] = f"{h} ({len(rows)} แถว)"
            except Exception as ex:
                msg = str(ex).splitlines()[0][:140]
                results.setdefault(code, {})[cid] = f"ERR: {type(ex).__name__}: {msg}"
                failed = code
        print(f"[{ci + 1}/{len(combos)}] {cid} {'FAIL at ' + failed if failed else 'ok'}", flush=True)
    spark.stop()

    combo_ids = list(next(iter(results.values())).keys()) if results else []
    lines = ["# D1 REPORT — Spark config matrix", "",
             f"spec: `{a.spec}` · combos: {len(combos)} ({' × '.join(f'{k}={matrix[k]}' for k in keys)}) · freeze now = `{spec.get('freeze_now')}` · ignore: {sorted(ignore)}", "",
             "| Task | ผล | กลุ่มผล (hash → combo) |", "|---|---|---|"]
    verdicts = {}
    for code in order:
        if code not in results or (only and code not in only):
            continue
        r = results[code]
        errs = [c for c, v in r.items() if v.startswith(("ERR", "SKIP"))]
        groups = {}
        for c, v in r.items():
            groups.setdefault(v, []).append(c)
        v = "ERROR-IN-SOME" if errs and len(errs) < len(r) else "ERROR" if errs else ("STABLE" if len(groups) == 1 else "CONFIG-DEPENDENT")
        verdicts[code] = v
        g = "<br>".join(f"`{k}` ← {len(cs)} combo" + (f": {', '.join(cs[:3])}{'…' if len(cs) > 3 else ''}" if len(groups) > 1 else "") for k, cs in groups.items())
        lines.append(f"| {code} | **{v}** | {g} |")
    lines += ["", "STABLE = ผล Spark เหมือนกันทุก config (กฎแปลงไม่ขึ้นกับ Q3) · CONFIG-DEPENDENT / ERROR-IN-SOME = ต้องรู้ค่า config จริงหรือยอมรับเป็นความเสี่ยง (SA)",
              "ผลต่อ combo อยู่ใน `output/d1/<combo>/<task>.csv` — ใช้เทียบกับผล Oracle จาก seed ชุดเดียวกัน (`scripts/testing/compare_results.py`)"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "D1_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "d1_results.json").write_text(json.dumps({"verdicts": verdicts, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[OK] output/d1/D1_REPORT.md ·", ", ".join(f"{k}={v}" for k, v in verdicts.items()))


if __name__ == "__main__":
    main()
