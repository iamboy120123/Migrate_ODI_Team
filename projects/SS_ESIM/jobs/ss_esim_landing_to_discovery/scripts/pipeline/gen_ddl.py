"""
gen_ddl.py
-----------
Runbook Phase 6 (Target DDL — DRAFT)

สร้าง CREATE TABLE ของ Oracle target จาก 3 แหล่ง เรียงตามความน่าเชื่อถือ:

    [0] existing- K16: ชนิดจริงของตารางที่มีอยู่แล้วใน Oracle (ผล all_tab_columns ใน
                  input/run_results/*/*.csv เช่น rp00 P3) — ตรงกับ Dev 100% ใช้ก่อนแหล่งอื่น
    [1] schema  - schema block ใน export_workflow.json (task 999999 export→MSSQL)
                  เป็น data type จริงจาก Blendata แต่ครอบคลุมแค่คอลัมน์ของ
                  tb_transaction_ss_esim_valid เท่านั้น
    [2] expr    - อนุมานจาก expression ใน converted SQL
                  (TO_NUMBER(TO_CHAR(..)) -> NUMBER(8), TO_TIMESTAMP -> TIMESTAMP,
                   SYSDATE -> DATE, TO_CHAR(..,'YYYYMMDDHH24MISS') -> VARCHAR2(14), ...)
    [3] fallback- เดาไม่ได้ -> VARCHAR2(4000) พร้อม TODO

** นี่คือ DRAFT ไม่ใช่ DDL สำหรับ production **
คอลัมน์ที่ขึ้น [3] fallback ทุกตัว SA/DBA ต้องกำหนดชนิดและความยาวจริงเอง
โดยเทียบกับ schema ฝั่ง Blendata หรือ profile จากข้อมูลจริง
(ดู 03_profile_source_lengths.sql ที่ script นี้ generate ให้)

Usage:
    python scripts/pipeline/gen_ddl.py [--config config/config.json]
"""

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path
from datetime import datetime

SPARK_TO_ORACLE = {
    "string": ("VARCHAR2(4000)", False),   # False = ความยาวยังไม่ยืนยัน
    "timestamp": ("TIMESTAMP", True),
    "int": ("NUMBER(10)", True),
    "bigint": ("NUMBER(19)", True),
    "long": ("NUMBER(19)", True),
    "double": ("NUMBER", True),
    "boolean": ("NUMBER(1)", True),
    "date": ("DATE", True),
}

# อนุมานจาก expression ใน SELECT list ของ converted SQL
EXPR_RULES = [
    (r"TO_NUMBER\(TO_CHAR\([^,]+,'YYYYMMDD'\)\)", "NUMBER(8)", True,  "partition_date จาก TO_CHAR YYYYMMDD"),
    (r"TO_CHAR\([^,]+,'YYYYMMDDHH24MISS'\)",      "VARCHAR2(14)", True, "TO_CHAR YYYYMMDDHH24MISS"),
    (r"TO_TIMESTAMP\(",                            "TIMESTAMP", True,  "TO_TIMESTAMP"),
    # K2 (2026-09-28): CAST / TO_CHAR ที่ใช้ใน converted SQL ของ payment_3bb_vdo
    (r"^CAST\(.*\bAS\s+TIMESTAMP\)\s*(AS\s+\w+)?$", "TIMESTAMP", True, "CAST AS TIMESTAMP"),
    (r"^CAST\(.*\bAS\s+NUMBER\)\s*(AS\s+\w+)?$",    "NUMBER", True,    "CAST AS NUMBER (Spark DOUBLE)"),
    (r"TO_CHAR\([^,]+,'YYYY-MM-DD'\)",            "VARCHAR2(10)", True, "TO_CHAR YYYY-MM-DD"),
    (r"\bTRUNC\(",                                 "DATE", True,       "TRUNC()"),
    (r"\bSYSDATE\b",                               "DATE", True,       "SYSDATE"),
    (r"LPAD\(TO_CHAR\(ROW_NUMBER",                 "VARCHAR2(26)", True, "cdr_id = 14+3+9 ตัวอักษร"),
    (r"^\s*1\s*$|^\s*0\s*$",                       "NUMBER(1)", True,  "boolean literal 1/0"),
    (r"COUNT\(|ROW_NUMBER\(|DENSE_RANK\(|NTH_VALUE\(|MIN\(|MAX\(", "NUMBER", True, "aggregate/analytic"),
]

# คอลัมน์ที่รู้ความหมายแน่ชัดจาก business logic
KNOWN = {
    "STATUS": ("VARCHAR2(5)", "ค่าที่เป็นไปได้: MAP/UNMAP/DUP/MAN/TYP"),
    "WORKFLOW_PROCESS_DATE": ("VARCHAR2(14)", "yyyyMMddHHmmss"),
    "PARTITION_DATE": ("NUMBER(8)", "yyyyMMdd"),
    "CDR_ID": ("VARCHAR2(26)", "14+3+9"),
    "CDR_FILEDATE": ("VARCHAR2(10)", "yyyy-MM-dd (Spark date -> string) - K2"),
    "CHECKPOINT_PARTITION": ("NUMBER(12)", "partition_minute = yyyyMMddHHmm"),
    "SUCCESS": ("VARCHAR2(5)", "boolean 'TRUE'/'FALSE' string (D2-revised)"),
    "RUNNING": ("VARCHAR2(5)", "boolean 'TRUE'/'FALSE' string (D2-revised)"),
    "TRANSACTION_UNITS": ("VARCHAR2(10)", "ค่าคงที่ '1' ใน SQL"),
    "ERR_MSG": ("VARCHAR2(4000)", "ข้อความ error"),
    "FILTER_ERROR": ("VARCHAR2(4000)", "ข้อความ error"),
    "MAPPING_ERROR": ("VARCHAR2(4000)", "ข้อความ error"),
    "TYPE_ERROR": ("VARCHAR2(4000)", "ข้อความ error"),
    "FILTER_ERROR_MSG": ("VARCHAR2(4000)", "ข้อความ error"),
    "MAPPING_ERROR_MSG": ("VARCHAR2(4000)", "ข้อความ error"),
    "TYPE_ERROR_MSG": ("VARCHAR2(4000)", "ข้อความ error"),
}


def split_top_level(expr: str) -> list:
    parts, depth, last, in_str = [], 0, 0, False
    for i, ch in enumerate(expr):
        if ch == "'":
            in_str = not in_str
        elif not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append(expr[last:i]); last = i + 1
    parts.append(expr[last:])
    return [p.strip() for p in parts if p.strip()]


def outer_select_items(sql: str) -> list:
    m = re.match(r"\s*SELECT\s+(?:DISTINCT\s+)?", sql, flags=re.I)
    if not m:
        return []
    depth, in_str, end, i = 0, False, None, m.end()
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            in_str = not in_str
        elif not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif depth == 0 and re.match(r"\bFROM\b", sql[i:], flags=re.I):
                end = i; break
        i += 1
    return split_top_level(sql[m.end():end if end is not None else len(sql)])


def col_name_of(item: str) -> str:
    a = re.search(r"\bAS\s+([A-Za-z_][\w$#]*)\s*$", item, flags=re.I)
    if a:
        return a.group(1).upper()
    t = re.search(r"([A-Za-z_][\w$#]*)\s*$", item)
    return t.group(1).upper() if t else ""


# ---------- lookup index (dedup / idempotency guard) ----------
# ตาราง append/merge โตขึ้นทุก run แต่ SQL ของ task อื่นอ่านย้อนกลับทุก run:
#   - 040000:  LEFT JOIN (SELECT chk_duplicate FROM valid UNION SELECT chk_duplicate FROM temp) dup  -> dedup ทั้ง history
#   - 0501/0502/0503: COUNT(*) ... WHERE workflow_process_date = (SELECT ...)                     -> guard กันรันซ้ำ
#   - 999999:  WHERE workflow_process_date > ... (ถ้าอยู่ใน scope — ข้ามได้ด้วย config.scope.excluded_tasks)
# ถ้าไม่มี index = full scan ทั้ง history ทุกชั่วโมง (ช้าลงเรื่อย ๆ) -> generate index จากรูปแบบเหล่านี้
_ID = r"(?:[A-Za-z_]\w*\.)?([A-Za-z_]\w*)"
JOIN_LOOKUP_RE = re.compile(
    r"JOIN\s*\(\s*(SELECT\s+\w+\s+FROM\s+(?:[A-Za-z_]\w*\.)?[A-Za-z_]\w*"
    r"(?:\s+UNION(?:\s+ALL)?\s+SELECT\s+\w+\s+FROM\s+(?:[A-Za-z_]\w*\.)?[A-Za-z_]\w*)*)\s*\)", re.I)
SEL_FROM_RE = re.compile(r"SELECT\s+(\w+)\s+FROM\s+" + _ID, re.I)
WHERE_PRED_RE = re.compile(r"\b(\w+)\s*(?:=|>=|>|<=|<)\s*(?:\(\s*SELECT|TO_CHAR\s*\(|\d)", re.I)
# ไม่นับการเทียบกับ string literal (เช่น status = 'MAP') - cardinality ต่ำ index ไม่ช่วย
FROM_WHERE_RE = re.compile(r"FROM\s+" + _ID + r"\s+WHERE\s+(.*?)(?=\)\s*(?:\)|WHERE|AND|$)|$)", re.I | re.S)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


def in_scope_sql(sql_dir: Path, config: dict) -> list:
    """converted SQL ที่อยู่ใน scope — ข้าม task ใน config.scope.excluded_tasks (เช่น 999999 export→MSSQL)"""
    excluded = set((config.get("scope") or {}).get("excluded_tasks") or [])
    files = []
    for f in sorted(Path(sql_dir).glob("*.sql")):
        if any(f"_{t}_" in f.stem for t in excluded):
            continue
        files.append(f)
    return files


def find_lookup_columns(conv_dir: Path, config: dict = None) -> dict:
    """{TABLE_UPPER: {COL_UPPER: {"why": set(), "tasks": set()}}}"""
    found = {}
    def add(tbl, col, why, tag):
        d = found.setdefault(tbl.upper(), {}).setdefault(col.upper(), {"why": set(), "tasks": set()})
        d["why"].add(why); d["tasks"].add(tag)
    for f in in_scope_sql(conv_dir, config or {}):
        sql = _strip_comments(f.read_text(encoding="utf-8"))
        m = re.search(r"_(\d{6})_", f.stem); tag = m.group(1) if m else f.stem
        for jm in JOIN_LOOKUP_RE.finditer(sql):
            for col, tbl in SEL_FROM_RE.findall(jm.group(1)):
                add(tbl, col, "join-lookup", tag)
        for tbl, pred in FROM_WHERE_RE.findall(sql):
            for col in WHERE_PRED_RE.findall(pred):
                if col.upper() in {"AND", "OR", "NOT", "SELECT"}:
                    continue
                add(tbl, col, "where-filter", tag)
    return found


def index_name(table_short: str, col: str, used: set) -> str:
    core = re.sub(r"^TB_(TRANSACTION|STAGING)_", "", table_short)
    colpart = col if len(col) <= 13 else "".join(w[0] for w in col.split("_"))
    name = f"IX_{core}_{colpart}"[:30]
    n, base = 1, name
    while name in used:
        n += 1; name = f"{base[:27]}_{n}"
    used.add(name)
    return name


# ---------- profile intake (Q5/Q6) ----------
def load_profile(config: dict) -> dict:
    """อ่าน input/run_results/profile_result.csv (tbl,col,max_len,null_cnt,row_cnt) ที่ export จากผลของ 03_profile
    คืน {(TBL, COL): {"max_len": int|None, "null_cnt": int, "row_cnt": int}}"""
    pc = config.get("profile") or {}
    path = Path(pc.get("result_csv", "input/run_results/profile_result.csv"))
    if not path.exists():
        return {}
    out = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            def num(x):
                return int(float(x)) if x not in ("", "null", "NULL", "None") else None
            out[(r["tbl"].upper(), r["col"].upper())] = {
                "max_len": num(r.get("max_len", "")), "null_cnt": num(r.get("null_cnt", "")),
                "row_cnt": num(r.get("row_cnt", ""))}
    return out


def nice_length(max_len: int, margin_pct: int) -> int:
    """เผื่อ margin แล้วปัดขึ้น: <=100 ปัดทีละ 10, <=1000 ทีละ 50, มากกว่านั้นทีละ 500 (cap 4000, ขั้นต่ำ 10)"""
    n = max(10, math.ceil(max_len * (1 + margin_pct / 100)))
    step = 10 if n <= 100 else 50 if n <= 1000 else 500
    return min(4000, int(math.ceil(n / step) * step))


def profiled_max(profile: dict, table: str, col: str, landing_map: dict, landing: str):
    """ความยาวสูงสุดจาก (1) ตารางนี้ (2) คอลัมน์ชื่อเดียวกันทุกตาราง (3) คอลัมน์ landing ที่ map มา
    ตาราง staging ที่ TRUNCATE ทุก run เห็นแค่รอบล่าสุด จึงต้องรวมจากหลายแหล่ง"""
    vals, srcs = [], []
    for (t, c), v in profile.items():
        if v["max_len"] is None:
            continue
        if c == col:
            vals.append(v["max_len"]); srcs.append(t.lower())
    for lcol, targets in landing_map.items():
        if col in [x.upper() for x in targets]:
            v = profile.get((landing.upper(), lcol.upper()))
            if v and v["max_len"] is not None:
                vals.append(v["max_len"]); srcs.append(f"{landing.lower()}.{lcol.lower()}")
    if not vals:
        return None, []
    return max(vals), sorted(set(srcs))


def load_existing_columns():
    """K16: {(TABLE, COL): oracle_type} จาก input/run_results/*/*.csv ที่มีหัว all_tab_columns"""
    out = {}
    need = {"TABLE_NAME", "COLUMN_NAME", "DATA_TYPE", "DATA_LENGTH"}
    for f in sorted(Path("input/run_results").glob("*/*.csv")):
        try:
            with f.open(encoding="utf-8-sig", newline="") as fh:
                rd = csv.DictReader(fh)
                if not need <= set(rd.fieldnames or []):
                    continue
                for r in rd:
                    t, c, dt = r["TABLE_NAME"].upper(), r["COLUMN_NAME"].upper(), r["DATA_TYPE"].upper()
                    if not c or c == "MISSING_OBJECT":
                        continue
                    ln, pr, sc = r.get("DATA_LENGTH") or "", r.get("DATA_PRECISION") or "", r.get("DATA_SCALE") or ""
                    if dt in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "RAW"):
                        typ = f"{dt}({ln})"
                    elif dt == "NUMBER":
                        typ = "NUMBER" if not pr else (f"NUMBER({pr})" if sc in ("", "0") else f"NUMBER({pr},{sc})")
                    else:
                        typ = dt
                    out[(t, c)] = typ
        except (OSError, csv.Error, KeyError):
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    manifest = json.loads(Path(config["paths"]["dml_manifest"]).read_text(encoding="utf-8"))
    # entry readonly (เช่น 000000 precheck) ไม่ได้เขียน target -> ไม่นับเป็น target table
    manifest = [e for e in manifest if not e.get("readonly")]
    export = json.loads(Path(config["paths"]["input_export_workflow"]).read_text(encoding="utf-8"))
    conv_dir = Path(config["paths"]["output_converted_sql"])
    out = Path("output/ddl"); out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().isoformat(timespec="seconds")

    # [1] schema block จาก export (data type จริงของ Blendata)
    spark_types, partitions = {}, {}
    # K1 (2026-09-30): export แบบง่าย (input/export_workflow.sample.json = {"workflow_name","tasks"}) ไม่มี schema block
    #   เดิม KeyError ทำให้ทดสอบ pipeline ด้วยไฟล์ตัวอย่างไม่ผ่าน Phase 6 -> ใช้ schema ว่าง (ทุกคอลัมน์อนุมานจาก expression / fallback)
    models = export.get("airflowExportModels") if isinstance(export, dict) else None
    if models:
        ver = next((v for v in models[0].get("versions", []) if v.get("latest")), (models[0].get("versions") or [{}])[0])
        tasks = json.loads(ver.get("taskDetailString") or "[]")
    else:
        tasks = []
        print("[WARN] export ไม่มี airflowExportModels (ไฟล์ตัวอย่าง?) — ไม่มีชนิดคอลัมน์จาก Blendata, ใช้การอนุมานจาก expression")
    for t in tasks:
        b = t.get("body") or {}
        for c in b.get("schema") or []:
            spark_types[c["originName"].upper()] = c["originDataType"]
        ac = b.get("aggregationConfig") or {}
        parts = (ac.get("sinkOption") or {}).get("partitions") or []
        if ac.get("tableName") and parts:
            partitions[ac["tableName"].upper()] = [p.upper() for p in parts]

    # รวม target -> คอลัมน์ + expression
    # BUGFIX: ตารางเดียวกันอาจถูกเขียนโดยหลาย task ด้วยคอลัมน์คนละชุด (เช่น
    # TB_STAGING_..._WORKFLOW_STATUS ถูกเขียนทั้งจาก 030000 (RUNNING, WORKFLOW_PROCESS_DATE)
    # และ 090000 (SUCCESS)) - เดิม logic เอาแค่ task ที่มีคอลัมน์มากสุดแล้วทิ้งที่เหลือไปเลย
    # ทำให้ DDL ขาดคอลัมน์ SUCCESS ไปทั้งคอลัมน์ - ต้อง union คอลัมน์จากทุก task ที่ชี้ตารางเดียวกัน
    tables = {}
    for e in manifest:
        tgt, cols = e["target_table"], e["columns"]
        if not cols:
            continue
        sql_path = conv_dir / (e["task_id"] + ".sql")
        exprs = outer_select_items(sql_path.read_text(encoding="utf-8")) if sql_path.exists() else []
        expr_by_col = {}
        for it in exprs:
            n = col_name_of(it)
            if n:
                expr_by_col[n] = it
        if tgt not in tables:
            tables[tgt] = {"cols": [], "expr": {}, "merge_keys": []}
        entry = tables[tgt]
        for c in cols:
            if c not in entry["cols"]:
                entry["cols"].append(c)
        for k, v in expr_by_col.items():
            entry["expr"].setdefault(k, v)
        if e.get("merge_keys"):
            entry["merge_keys"] = e.get("merge_keys")

    # ตารางที่ถูก TRUNCATE ทุก run เล็กเสมอ -> ไม่ต้องมี lookup index
    truncated = {e["target_table"].rsplit(".", 1)[-1].upper()
                 for e in manifest if any("TRUNCATE" in s_.upper() for s_ in e.get("steps", []))}
    lookups = find_lookup_columns(conv_dir, config)
    used_ix, index_report = set(), []

    ddl, review = [], []
    ddl.append(f"-- 01_create_tables.sql  (DRAFT generated {stamp})")
    ddl.append("-- ⚠️ DRAFT: คอลัมน์ที่ทำเครื่องหมาย TODO ต้องกำหนดชนิด/ความยาวจริงเอง")
    ddl.append("--    ดู README.md และรัน 03_profile_source_lengths.sql ฝั่ง Blendata ก่อนสรุป\n")

    stats = {"existing": 0, "schema": 0, "known": 0, "expr": 0, "fallback": 0, "profile": 0}
    existing = load_existing_columns()
    existing_tables = {t for t, _ in existing}
    missing_in_dev = []
    pcfg = config.get("profile") or {}
    profile = load_profile(config)
    margin = int(pcfg.get("length_margin_pct", 50))
    landing_map = pcfg.get("landing_column_map") or {}
    landing_tbl = pcfg.get("landing_table", "")
    notnull_candidates = []
    # K2: pre-pass — ชนิดที่อนุมานได้จาก expression ของทุกตาราง (ใช้เติมคอลัมน์ชื่อเดียวกันที่ fallback)
    cross_types = {}
    for tgt_, info_ in sorted(tables.items()):
        for c_, ex_ in info_["expr"].items():
            for pat, t2, conf, why in EXPR_RULES:
                if conf and not t2.startswith("VARCHAR2") and re.search(pat, ex_, flags=re.I):
                    cross_types.setdefault(c_, (t2, tgt_.rsplit(".", 1)[-1])); break

    for tgt, info in sorted(tables.items()):
        short = tgt.rsplit(".", 1)[-1]
        lines = ([f"-- K16: {short} มีอยู่แล้วใน Oracle (all_tab_columns) — DDL นี้ใช้อ้างอิง/สร้างใน env ใหม่ (Prod) ห้ามรันทับใน Dev"]
                 if short.upper() in existing_tables else [f"-- K16: {short} ไม่พบในผล all_tab_columns — ต้องสร้างใหม่หรือยืนยันว่ามีอยู่"])
        lines.append(f"CREATE TABLE {tgt} (")
        body = []
        for c in info["cols"]:
            typ, confident, src, note = None, False, None, ""
            if (short.upper(), c.upper()) in existing:
                typ, confident, src = existing[(short.upper(), c.upper())], True, "existing"
                note = "ชนิดจริงใน Oracle (all_tab_columns)"
            elif short.upper() in existing_tables:
                missing_in_dev.append(f"{short}.{c}")
            if typ is not None:
                pass
            elif c in KNOWN:
                typ, note = KNOWN[c]; confident = True; src = "known"
            elif c in spark_types:
                typ, confident = SPARK_TO_ORACLE.get(spark_types[c], ("VARCHAR2(4000)", False))
                src = "schema"; note = f"Blendata type = {spark_types[c]}"
            else:
                ex = info["expr"].get(c, "")
                for pat, t2, conf, why in EXPR_RULES:
                    if re.search(pat, ex, flags=re.I):
                        typ, confident, src, note = t2, conf, "expr", why; break
                if typ is None and c in cross_types:
                    # K2: คอลัมน์ชื่อเดียวกันที่อนุมานได้จากตารางอื่น (เช่น RAW_TEMP -> VALID/REJECT)
                    typ, confident, src, note = cross_types[c][0], True, "expr", f"อนุมานจากตาราง {cross_types[c][1]}"
                if typ is None:
                    typ, confident, src, note = "VARCHAR2(4000)", False, "fallback", "เดาไม่ได้จาก SQL"
            if profile and typ.startswith("VARCHAR2") and not confident:
                mx, srcs = profiled_max(profile, short.upper(), c, landing_map, landing_tbl)
                if mx is not None:
                    typ = f"VARCHAR2({nice_length(mx, margin)})"
                    confident, src = True, "profile"
                    note = f"profile max={mx} (+{margin}%) จาก {', '.join(srcs)}"
            if src == "schema" and not confident:
                note += " (ความยาวยังไม่ยืนยัน)"
            pv = profile.get((short.upper(), c))
            if pv and pv["row_cnt"] and pv["null_cnt"] == 0:
                notnull_candidates.append((short, c, pv["row_cnt"]))
            stats[src] = stats.get(src, 0) + 1
            body.append((f"    {c:28s} {typ:16s}", "" if confident else "   -- TODO ยืนยันชนิด/ความยาว"))
            review.append((short, c, typ, src, "ยืนยันแล้ว" if confident else "ต้องตรวจ", note))
        # comma ต้องอยู่ "ก่อน" comment ไม่งั้นจะโดน -- comment ออกไปด้วย
        rendered = []
        for i, (col, cmt) in enumerate(body):
            rendered.append(col + ("," if i < len(body) - 1 else "") + cmt)
        lines.append("\n".join(rendered))
        lines.append(");")
        if info["merge_keys"]:
            k = ", ".join(x.upper() for x in info["merge_keys"])
            lines.append(f"-- merge key ของ MERGE statement -> ควรมี unique index")
            lines.append(f"CREATE UNIQUE INDEX UX_{short[:25]} ON {tgt} ({k});")
        lk = lookups.get(short.upper(), {})
        mk = {x.upper() for x in info["merge_keys"]}
        if short.upper() not in truncated:
            for col, meta in sorted(lk.items()):
                if col not in info["cols"] or col in mk:
                    continue
                ix = index_name(short.upper(), col, used_ix)
                why = " + ".join(sorted(meta["why"]))
                tasks = ", ".join(sorted(meta["tasks"]))
                lines.append(f"-- lookup index: {why} ใน task {tasks} (ตารางโตทุก run - ไม่มี index = full scan history)")
                lines.append(f"CREATE INDEX {ix} ON {tgt} ({col});")
                index_report.append((short, col, ix, why, tasks))
        p = partitions.get(short)
        if p:
            lines.append(f"-- Blendata partition by: {', '.join(p)}")
            lines.append(f"--   ถ้าจะทำ partition ฝั่ง Oracle ด้วย แนะนำ RANGE/INTERVAL บน PARTITION_DATE")
            lines.append(f"--   และจะทำให้ 080000 retention ใช้ DROP PARTITION แทน DELETE ได้")
        ddl.append("\n".join(lines) + "\n")

    (out / "01_create_tables.sql").write_text("\n".join(ddl), encoding="utf-8")

    # 03: query profile ฝั่ง Blendata — ผลลัพธ์ long format (tbl, col, max_len, null_cnt, row_cnt)
    #     export ผลทั้งหมดเป็น CSV -> input/run_results/profile_result.csv แล้วรัน gen_ddl.py ใหม่ = ได้ความยาวจริง
    prof = [f"-- 03_profile_source_lengths.sql  (Blendata / Spark SQL, generated {stamp})",
            "-- ผลลัพธ์ทุก query มี 5 คอลัมน์เหมือนกัน: tbl, col, max_len, null_cnt, row_cnt",
            "-- -> export รวมเป็นไฟล์เดียว input/run_results/profile_result.csv (มี header) แล้วรัน:",
            "--      python scripts/pipeline/gen_ddl.py && python scripts/pipeline/gen_backfill.py",
            "--    gen_ddl จะตั้ง VARCHAR2(ความยาวจริง + margin) และเสนอ NOT NULL candidate (Q5 - SA ตัดสินเอง)",
            "-- ⚠️ ตาราง staging ที่ overwrite ทุก run (raw_temp ฯลฯ) เห็นแค่รอบล่าสุด — gen_ddl จึงเอา max",
            "--    ข้ามทุกตารางที่มีคอลัมน์ชื่อเดียวกัน + คอลัมน์ต้นทางใน landing (config.profile.landing_column_map)\n"]
    def stack_query(tbl, cols, str_cols):
        # 2 ชั้น: ชั้นในรวม aggregate ครั้งเดียว (scan ตาราง 1 รอบ), ชั้นนอก stack() เป็น long format
        # (Spark ไม่ให้ใช้ generator ปนกับ aggregate ใน SELECT เดียวกัน)
        agg, stk = ["COUNT(*) AS row_cnt"], []
        for i_, c in enumerate(cols):
            ml = f"MAX(LENGTH(CAST({c.lower()} AS STRING)))" if c in str_cols else "CAST(NULL AS INT)"
            agg.append(f"{ml} AS ml_{i_}")
            agg.append(f"COUNT(*) - COUNT({c.lower()}) AS nc_{i_}")
            stk.append(f"'{c.lower()}', ml_{i_}, nc_{i_}")
        a = ",\n                 ".join(agg)
        st = ",\n                     ".join(stk)
        return (f"-- {tbl}\nSELECT '{tbl}' AS tbl, col, max_len, null_cnt, row_cnt\nFROM (\n"
                f"  SELECT row_cnt, stack({len(cols)},\n                     {st}\n"
                f"         ) AS (col, max_len, null_cnt)\n"
                f"  FROM (SELECT {a}\n        FROM {tbl}) a\n) t;\n")
    for tgt, info in sorted(tables.items()):
        short = tgt.rsplit(".", 1)[-1].lower()
        str_cols = [c for c in info["cols"] if c not in KNOWN or KNOWN[c][0].startswith("VARCHAR2")]
        str_cols = [c for c in str_cols if not (c in spark_types and not spark_types[c].startswith("string"))]
        prof.append(stack_query(short, info["cols"], set(str_cols)))
    if landing_tbl and landing_map:
        lcols = [k.upper() for k in landing_map]
        prof.append("-- landing (source จริงของคอลัมน์ raw) — ใช้เพิ่มความยาวให้คอลัมน์ target ตาม landing_column_map")
        prof.append(stack_query(landing_tbl.lower(), lcols, set(lcols)))
    (out / "03_profile_source_lengths.sql").write_text("\n".join(prof), encoding="utf-8")

    target_shorts = {t.rsplit(".", 1)[-1].upper() for t in tables}
    ext = set()
    for f in in_scope_sql(conv_dir, config or {}):
        for ref in re.findall(r"\b(?:FROM|JOIN)\s+(?:[A-Za-z_]\w*\.)?([A-Za-z_]\w*)",
                              _strip_comments(f.read_text(encoding="utf-8")), flags=re.I):
            if ref.upper() not in target_shorts and ref.upper() != "DUAL":
                ext.add(ref.upper())
    external = sorted(ext)

    rd = [f"# Target DDL — DRAFT ({stamp})", "",
          "⚠️ **ไม่ใช่ DDL สำหรับ production** — ที่มาของชนิดข้อมูลแต่ละคอลัมน์:", "",
          f"| ที่มา | จำนวนคอลัมน์ | ความน่าเชื่อถือ |", "|---|---|---|",
          f"| `known` — business logic ที่รู้แน่ (status, cdr_id, partition_date, …) | {stats.get('known',0)} | สูง |",
          f"| `existing` — ตารางจริงใน Oracle (all_tab_columns, K16) | {stats.get('existing',0)} | ตรงกับ Dev |",
          f"| `schema` — schema block ใน export_workflow.json | {stats.get('schema',0)} | ชนิดแน่ / ความยาวยังไม่แน่ |",
          f"| `expr` — อนุมานจาก expression ใน SQL | {stats.get('expr',0)} | สูง |",
          f"| `profile` — ความยาวจริงจาก `input/run_results/profile_result.csv` (+{margin}%) | {stats.get('profile',0)} | สูง (ขึ้นกับช่วงข้อมูลที่ profile) |",
          f"| `fallback` — เดาไม่ได้ ใส่ VARCHAR2(4000) | {stats.get('fallback',0)} | **ต้องแก้** |", "",
          ("✅ ใช้ผล profile แล้ว: " + str(len(profile)) + " แถวจาก `" + str(pcfg.get('result_csv', 'input/run_results/profile_result.csv')) + "`")
          if profile else "⏳ ยังไม่มี `input/run_results/profile_result.csv` — รัน `03_profile_source_lengths.sql` ฝั่ง Blendata แล้ว export ผลเป็น CSV", "",
          "## ขั้นตอน", "",
          "1. รัน `03_profile_source_lengths.sql` ฝั่ง Blendata → ได้ความยาวจริง",
          "2. แทน `VARCHAR2(4000)` ที่มี `-- TODO` ด้วยความยาวจริง (+ เผื่อ margin)",
          "3. ให้ DBA review เรื่อง tablespace / partition / index / NOT NULL constraint",
          "4. รัน `01_create_tables.sql`", "",
          "## สิ่งที่ DDL นี้ **ไม่ได้** กำหนดให้ (ต้องตัดสินใจเอง)", "",
          "- `NOT NULL` / `PRIMARY KEY` / `FOREIGN KEY` — kit ไม่รู้ business constraint",
          "- tablespace, storage, compression",
          "- partition จริง (มีแต่ comment แนะนำจาก partition ฝั่ง Blendata)",
          "- index อื่นนอกจาก unique index ของ merge key และ lookup index ด้านล่าง "
          "(เช่น local index เมื่อทำ partition จริง)",
          f"- {len(external)} external object ที่ SQL อ้างถึงแต่ไม่ได้สร้างที่นี่: "
          + ", ".join(f"`{x}`" for x in external), "",
          "## Lookup index (generate จาก SQL ของ task อื่นที่อ่านตาราง append/merge ย้อนกลับทุก run)", "",
          "| ตาราง | คอลัมน์ | index | ใช้เป็น | task |", "|---|---|---|---|---|"]
    rd += [f"| {a} | {b} | `{c}` | {d} | {e} |" for a, b, c, d, e in index_report]
    rd += ["", "⚠️ 040000 dedup เทียบ `CHK_DUPLICATE` กับ **ทั้ง history** ของ valid ∪ temp (ไม่มีขอบเขตเวลา) — "
           "index ช่วยได้ระดับหนึ่ง แต่ runtime ยังโตตาม history ต้องวัดใน parallel run (CUTOVER_RUNBOOK K1)", ""]
    if profile:
        rd += ["## NOT NULL candidate (Q5 — ข้อเสนอเท่านั้น ไม่ได้ใส่ใน DDL)", "",
               "คอลัมน์ที่ profile แล้วไม่มี NULL เลย — SA ตัดสินว่าเป็น business rule จริงหรือแค่บังเอิญในช่วงข้อมูลนี้", "",
               "| ตาราง | คอลัมน์ | row_cnt ที่ profile |", "|---|---|---|"]
        rd += [f"| {a} | {b} | {n:,} |" for a, b, n in notnull_candidates] or ["| - | - | - |"]
        rd += [""]
    rd += ["## รายคอลัมน์", "",
          "| ตาราง | คอลัมน์ | ชนิด | ที่มา | สถานะ | หมายเหตุ |", "|---|---|---|---|---|---|"]
    for r in review:
        rd.append("| " + " | ".join(str(x) for x in r) + " |")
    (out / "README.md").write_text("\n".join(rd) + "\n", encoding="utf-8")

    print(f"[OK] output/ddl/01_create_tables.sql ({len(tables)} ตาราง)")
    print(f"[OK] output/ddl/03_profile_source_lengths.sql")
    if profile:
        print(f"[PROFILE] ใช้ผล {len(profile)} แถว -> ตั้งความยาว {stats.get('profile', 0)} คอลัมน์, "
              f"NOT NULL candidate {len(notnull_candidates)} คอลัมน์ (ดู README)")
    else:
        print("[PROFILE] ยังไม่มี input/run_results/profile_result.csv - ความยาวยังเป็น DRAFT")
    for a, b, c, d, e in index_report:
        print(f"[INDEX] {c} ON {a} ({b})  <- {d} ใน task {e}")
    print(f"[OK] output/ddl/README.md")
    print(f"[SUMMARY] ที่มาของชนิดข้อมูล: {stats}")
    if existing:
        have = sorted(t.rsplit(".", 1)[-1] for t in tables if t.rsplit(".", 1)[-1].upper() in existing_tables)
        new = sorted(t.rsplit(".", 1)[-1] for t in tables if t.rsplit(".", 1)[-1].upper() not in existing_tables)
        print(f"[EXISTING] มีอยู่แล้วใน Oracle {len(have)} ตาราง · ไม่พบ {len(new)}: {', '.join(new) or '-'}")
    if missing_in_dev:
        print(f"[FAIL] คอลัมน์ที่ DML เขียนแต่ไม่มีในตารางจริง {len(missing_in_dev)}: {', '.join(missing_in_dev[:10])}")
    if stats.get("fallback"):
        print(f"[WARN] {stats['fallback']} คอลัมน์เดาชนิดไม่ได้ -> VARCHAR2(4000) ต้องแก้ก่อนใช้จริง")


if __name__ == "__main__":
    main()
