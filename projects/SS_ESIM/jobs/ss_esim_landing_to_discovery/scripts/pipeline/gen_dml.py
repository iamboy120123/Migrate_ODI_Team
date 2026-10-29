"""
gen_dml.py
-----------
Runbook Phase 5a (DML Generation)

หน้าที่:
    อ่าน SQL ที่ผ่านการแก้ไข/รีวิวแล้วจาก output/sql/converted/
    ห่อเป็น Oracle DML (INSERT หรือ MERGE) ตาม load_strategy ใน config.json
    แนบ LOG ERRORS clause ถ้า error_handling = "errlog"
    ใส่ target_table_prefix ตามที่กำหนด
    เขียนผลลัพธ์เป็นไฟล์ DML ต่อ task ลงใน output/dml/ (นี่คือเนื้อหาของ ODI Procedure)

ข้อควรทราบ (ระบุไว้ตรงๆ เพราะ CLAUDE.md ไม่ได้นิยาม logic ของ "smart" ไว้ชัดเจน):
    - overwrite : TRUNCATE TABLE + INSERT ... SELECT (จาก converted SQL)
    - upsert    : MERGE INTO ... USING (converted SQL) ON (merge_keys)
                  ต้องมี merge_keys ระบุไว้ใน raw manifest (มาจาก export_workflow.json)
    - smart     : ถ้า task มี merge_keys -> ใช้ MERGE เหมือน upsert
                  ถ้าไม่มี merge_keys -> fallback เป็น overwrite พร้อม print คำเตือน
                  ** SA ควรยืนยัน logic นี้กับทีมก่อนใช้งานจริง เพราะเป็นการตีความ
                     ของทีมพัฒนา ไม่ใช่ definition ที่ระบุใน CLAUDE.md ต้นฉบับ **

Usage:
    python scripts/pipeline/gen_dml.py [--config config/config.json]
"""

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime



def split_top_level(expr: str) -> list[str]:
    """แยก comma ระดับบนสุด (ไม่นับที่อยู่ใน () หรือใน string literal)"""
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
                parts.append(expr[last:i])
                last = i + 1
    parts.append(expr[last:])
    return [p.strip() for p in parts if p.strip()]


def derive_columns(converted_sql: str) -> list[str]:
    """ดึงรายชื่อคอลัมน์ผลลัพธ์จาก SELECT ชั้นนอกสุดของ converted SQL
    คืน [] ถ้าแกะไม่ได้อย่างมั่นใจ (เช่นมี SELECT * ) เพื่อไม่ให้ generate DML ผิด
    ** SA ต้องตรวจสอบรายชื่อที่ได้เทียบกับ DDL ของตาราง target จริงเสมอ **
    """
    sql = converted_sql.strip()
    m = re.match(r"\s*SELECT\s+(?:DISTINCT\s+)?", sql, flags=re.IGNORECASE)
    if not m:
        return []
    depth, in_str, end = 0, False, None
    i = m.end()
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            in_str = not in_str
        elif not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif depth == 0 and re.match(r"\bFROM\b", sql[i:], flags=re.IGNORECASE):
                end = i
                break
        i += 1
    if end is None:
        # SELECT ที่ไม่มี FROM (เช่น select 1 as success) - ใช้ทั้งบรรทัดเป็น select list
        end = len(sql)
    cols = []
    for item in split_top_level(sql[m.end():end]):
        if "*" in item:
            return []
        alias = re.search(r"\bAS\s+([A-Za-z_][\w$#]*)\s*$", item, flags=re.IGNORECASE)
        if alias:
            cols.append(alias.group(1))
            continue
        tail = re.search(r"([A-Za-z_][\w$#]*)\s*$", item)
        if not tail:
            return []
        cols.append(tail.group(1))
    return [c.upper() for c in cols] if cols else []


def build_append_dml(target_table: str, converted_sql: str, cols: list[str], error_clause: str) -> list[tuple]:
    col_clause = f" ({', '.join(cols)})" if cols else ""
    stmts = [
        "-- Load Strategy: append (Blendata sinkOption.mode = Append)",
        "-- ไม่มี TRUNCATE โดยเจตนา - task นี้เป็น append ใน source",
        f"INSERT INTO {target_table}{col_clause}",
        converted_sql.rstrip().rstrip(";"),
    ]
    body = "\n".join(stmts)
    body = (body.rstrip() + "\n" + error_clause) if error_clause else (body.rstrip() + ";")
    return [("INSERT", body)]


def build_error_log_clause(target_table: str, job_name: str) -> str:
    # target_table อาจมี schema นำหน้า (เช่น MYSCHEMA.TB_X) -> ERR table ต้องเป็น MYSCHEMA.ERR_TB_X
    if "." in target_table:
        schema, tbl = target_table.rsplit(".", 1)
        err_table = f"{schema}.ERR_{tbl}".upper()
    else:
        err_table = f"ERR_{target_table}".upper()
    return (
        f"LOG ERRORS INTO {err_table} "
        f"('MIGRATE_{job_name.upper()}') REJECT LIMIT UNLIMITED;"
    )


def build_overwrite_dml(target_table: str, converted_sql: str, error_clause: str, cols: list[str] | None = None) -> list[tuple]:
    col_clause = f" ({', '.join(cols)})" if cols else ""
    # ODI Procedure 1 step รับได้ 1 statement -> ต้องแยก TRUNCATE กับ INSERT เป็นคนละ step
    # TRUNCATE เป็น DDL. default = plain (reference มี TRUNCATE แบบตรง ๆ ที่ SqlIndGrp=0). execute_immediate ใช้เมื่อ reference มีตัวอย่าง BEGIN..END เท่านั้น
    if TRUNCATE_STYLE == "execute_immediate":
        truncate_step = ("-- Load Strategy: overwrite (step 1/2)\n"
                         "BEGIN\n"
                         f"  EXECUTE IMMEDIATE 'TRUNCATE TABLE {target_table}';\n"
                         "END;")
    else:
        truncate_step = "-- Load Strategy: overwrite (step 1/2)\n" + f"TRUNCATE TABLE {target_table};"
    insert_body = "\n".join([
        "-- Load Strategy: overwrite (step 2/2)",
        f"INSERT INTO {target_table}{col_clause}",
        converted_sql.rstrip().rstrip(";"),
    ])
    insert_body = (insert_body.rstrip() + "\n" + error_clause) if error_clause else (insert_body.rstrip() + ";")
    return [("TRUNCATE", truncate_step), ("INSERT", insert_body)]


# ---------------------------------------------------------------------------
# Overwrite + sinkOption.partitions ไม่ว่าง (D-R7): คนตัดสินใจ (I14) -> กรอก DECISION ใน config/partitions_check.csv
#   delete_by_partition = DELETE เฉพาะ partition ที่ SELECT จะโหลดใหม่ แล้ว INSERT (แนะนำ)
#   truncate_all        = TRUNCATE ทั้งตาราง (คนยืนยันว่าตั้งใจ — ด่าน D-R7 ของตัวสร้าง XML ยังจะปฏิเสธเว้นแต่ PARTITIONS_EMPTY=Y จริง)
#   ว่าง                = gen_dml หยุด ไม่เดา
# ---------------------------------------------------------------------------
VALID_DECISIONS = ("delete_by_partition", "truncate_all")


def load_partition_info(path: Path) -> dict:
    """{ชื่อตารางไม่มี schema (lower): {"empty": bool, "cols": [..], "decision": str}} จาก partitions_check.csv"""
    import csv
    info = {}
    if not path.exists():
        return info
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            name = (row.get("table_name") or "").split(".")[-1].lower()
            if not name:
                continue
            info[name] = {
                "empty": row.get("partitions_empty", "").upper() in ("Y", "YES", "TRUE", "1"),
                "cols": [c.strip().upper() for c in re.split(r"[;,|]", row.get("partition_columns", "")) if c.strip()],
                "decision": row.get("decision", "").strip().lower(),
            }
    return info


def build_partition_delete_dml(target_table, converted_sql, part_cols, cols, error_clause):
    """DELETE เฉพาะ partition ที่ SELECT ชุดเดียวกันกำลังจะโหลด แล้ว INSERT (SELECT ต้องคงเหมือนกันทั้งสอง step)"""
    pc = ", ".join(part_cols)
    lhs = pc if len(part_cols) == 1 else f"({pc})"
    body = converted_sql.strip().rstrip(";").rstrip()
    delete_step = "\n".join([
        "-- Load Strategy: overwrite by partition (step 1/2) -- I14: DELETE เฉพาะ partition ที่กำลังจะโหลดใหม่ ไม่ TRUNCATE ทั้งตาราง",
        "-- SELECT ข้างล่างต้องเหมือน step 2 ทุกประการ (แก้ที่เดียวต้องแก้ทั้งคู่)",
        f"DELETE FROM {target_table}",
        f"WHERE {lhs} IN (",
        f"    SELECT DISTINCT {pc}",
        "    FROM (",
        body,
        "    )",
        ")",
    ])
    insert_step = build_overwrite_dml(target_table, converted_sql, error_clause, cols)[1][1]
    return [("DELETE", delete_step), ("INSERT", insert_step)]


def build_merge_dml(target_table: str, converted_sql: str, merge_keys: list[str], error_clause: str, cols: list[str] | None = None) -> list[tuple]:
    on_clause = " AND ".join([f"tgt.{k.upper()} = src.{k.upper()}" for k in merge_keys])
    keys_up = {k.upper() for k in merge_keys}
    if cols:
        upd = [c for c in cols if c not in keys_up]
        update_set = ",\n".join([f"    tgt.{c} = src.{c}" for c in upd]) or "    -- ไม่มีคอลัมน์นอก merge key"
        insert_cols = "    (" + ", ".join(cols) + ")"
        insert_vals = "    VALUES (" + ", ".join([f"src.{c}" for c in cols]) + ")"
        stmts = [
            f"-- Load Strategy: upsert/smart (MERGE) on keys: {', '.join(merge_keys)}",
            "-- column list แกะจาก SELECT ชั้นนอกของ converted SQL - SA ต้องตรวจเทียบ DDL ของ target จริง",
            f"MERGE INTO {target_table} tgt",
            "USING (",
            converted_sql.rstrip().rstrip(";"),
            ") src",
            f"ON ({on_clause})",
            "WHEN MATCHED THEN UPDATE SET",
            update_set,
            "WHEN NOT MATCHED THEN INSERT",
            insert_cols,
            insert_vals,
        ]
        body = "\n".join(stmts)
        body = (body.rstrip() + "\n" + error_clause) if error_clause else (body.rstrip() + ";")
        return [("MERGE", body)]
    stmts = [
        f"-- Load Strategy: upsert/smart (MERGE) on keys: {', '.join(merge_keys)}",
        f"MERGE INTO {target_table} tgt",
        f"USING (",
        converted_sql.rstrip().rstrip(";"),
        f") src",
        f"ON ({on_clause})",
        f"WHEN MATCHED THEN UPDATE SET",
        f"    -- TODO: SA ต้องระบุ column list สำหรับ UPDATE SET ให้ครบตามตาราง target จริง",
        f"    tgt.updated_at = SYSDATE",
        f"WHEN NOT MATCHED THEN INSERT",
        f"    -- TODO: SA ต้องระบุ column list สำหรับ INSERT ให้ครบตามตาราง target จริง",
        f"    VALUES (src.*)",
    ]
    body = "\n".join(stmts)
    if error_clause:
        body = body.rstrip() + "\n" + error_clause
    else:
        body = body.rstrip() + ";"
    return [("MERGE", body)]


STEP_MARKER = "-- @@ODI_STEP: "
TRUNCATE_STYLE = "plain"   # ตั้งจาก config.truncate_style ใน main() — plain = TRUNCATE TABLE ตรง ๆ (ตรงกับ reference: SqlIndGrp=0); execute_immediate (BEGIN..END) ไม่มีตัวอย่างใน reference -> builder จะหยุดถาม


PLSQL_START_RE = re.compile(r"^\s*(DECLARE|BEGIN)\b", re.I)
WRITE_DML_RE = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE)\b", re.I)


def strip_leading_comments(sql: str) -> str:
    """ตัด comment/บรรทัดว่างส่วนหัวออก (เพื่อตรวจว่าเนื้อ SQL ขึ้นต้นด้วยอะไร)"""
    sql = re.sub(r"^\s*/\*.*?\*/", "", sql, flags=re.S)
    lines = sql.splitlines()
    while lines and (not lines[0].strip() or lines[0].strip().startswith("--")):
        lines.pop(0)
    return "\n".join(lines)


def as_plsql_block(sql: str):
    """ถ้า converted SQL เป็น PL/SQL block (DECLARE/BEGIN - เช่น pre/post check) คืน body ที่พร้อมใส่ ODI step
    ไม่งั้นคืน None
    - ส่งผ่านตามเดิม ไม่ห่อด้วย INSERT/MERGE/TRUNCATE
    - ตัด '/' ท้าย block ออก: '/' เป็นคำสั่งของ SQL*Plus ไม่ใช่ PL/SQL - ถ้าอยู่ใน ODI step จะ error"""
    body = strip_leading_comments(sql)
    if not PLSQL_START_RE.match(body):
        return None
    body = re.sub(r"\n\s*/\s*$", "", body.rstrip())
    return body.rstrip()


def overwrite_with_decision(task_id, table_raw, target_table, converted_sql, error_clause, cols, part_info, pending, strategy_used):
    """เลือก TRUNCATE หรือ DELETE ตาม partition ตามคำตอบ I14 ใน partitions_check.csv (ไม่เดา)"""
    info = part_info.get(table_raw.split(".")[-1].lower())
    if info is None:
        print(f"[WARN] {task_id}: ไม่มีตาราง {table_raw} ใน partitions_check.csv - ใช้ TRUNCATE ตามเดิมแต่ยังไม่ได้ยืนยัน I14 "
              f"(ด่าน P1/P4 และตัวสร้าง XML จะตรวจซ้ำ)")
        return build_overwrite_dml(target_table, converted_sql, error_clause, cols), strategy_used
    if info["empty"]:
        return build_overwrite_dml(target_table, converted_sql, error_clause, cols), strategy_used
    d = info["decision"]
    if d == "delete_by_partition":
        problems = []
        if not info["cols"]:
            problems.append("PARTITION_COLUMNS ว่างใน partitions_check.csv")
        elif not cols:
            problems.append("แกะ column list ของ SELECT ไม่ได้ (ต้องรู้ว่า partition column อยู่ในผลลัพธ์)")
        else:
            miss = [c for c in info["cols"] if c not in {x.upper() for x in cols}]
            if miss:
                problems.append("partition column " + ", ".join(miss) + " ไม่อยู่ใน column list ของ INSERT")
        if problems:
            pending.append((task_id, table_raw, "delete_by_partition ใช้ไม่ได้: " + "; ".join(problems)))
            return [], strategy_used
        return (build_partition_delete_dml(target_table, converted_sql, info["cols"], cols, error_clause),
                f"overwrite-by-partition (I14 delete_by_partition: {', '.join(info['cols'])})")
    if d == "truncate_all":
        print(f"[WARN] {task_id}: I14 เลือก truncate_all ทั้งที่ sinkOption.partitions ไม่ว่าง - ข้อมูล partition อื่นจะหายถาวร; "
              f"ตัวสร้าง XML (D-R7) จะปฏิเสธเว้นแต่ยืนยันกับทีม Blendata แล้วว่าตารางนี้เขียนทับทั้งใบจริง (แก้ PARTITIONS_EMPTY=Y พร้อมเหตุผล)")
        return build_overwrite_dml(target_table, converted_sql, error_clause, cols), strategy_used + " + I14 truncate_all"
    if d:
        pending.append((task_id, table_raw, f"DECISION '{d}' ไม่รู้จัก (ใช้ได้: {' | '.join(VALID_DECISIONS)})"))
    else:
        pending.append((task_id, table_raw, "ยังไม่ได้ตอบ I14 (DELETE หรือ TRUNCATE) - sinkOption.partitions ไม่ว่าง"))
    return [], strategy_used


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.json")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))

    converted_dir = Path(config["paths"]["output_converted_sql"])
    dml_dir = Path(config["paths"]["output_dml"])
    dml_manifest_path = Path(config["paths"]["dml_manifest"])
    raw_manifest_path = Path(config["paths"]["raw_manifest"])
    dml_dir.mkdir(parents=True, exist_ok=True)

    global TRUNCATE_STYLE
    TRUNCATE_STYLE = config.get("truncate_style", "plain")
    load_strategy = config.get("load_strategy", "smart")
    error_handling = config.get("error_handling", "errlog")
    prefix = config.get("target_table_prefix", "")
    project_name = config.get("project_name", "MIGRATION")

    part_info = load_partition_info(Path(config["paths"].get("partitions_check", "config/partitions_check.csv")))
    ok_lines = []
    pending, pending_writes = [], []   # pending = task ที่ยังไม่มีคำตอบ I14 -> หยุดก่อนเขียนไฟล์ใด ๆ

    raw_manifest = json.loads(raw_manifest_path.read_text(encoding="utf-8")) if raw_manifest_path.exists() else []
    # ไฟล์ใน converted/ ตั้งชื่อเป็น "<task_id>_<task_name>.sql" ไม่ใช่ "<task_id>.sql"
    # จึงต้อง map ด้วย stem ของ raw_sql_file ไม่ใช่ task_id ตรงๆ (มิฉะนั้น target_table/merge_keys จะหลุดทั้งหมด)
    meta_by_task = {}
    for m in raw_manifest:
        meta_by_task[m["task_id"]] = m
        if m.get("raw_sql_file"):
            meta_by_task[Path(m["raw_sql_file"]).stem] = m

    sql_files = sorted(converted_dir.glob("*.sql"))
    if not sql_files:
        sys.exit(f"[ERROR] ไม่พบไฟล์ .sql ใน {converted_dir} - รัน convert_sql.py (และ agent_reviewer.py ถ้าจำเป็น) ก่อน")

    dml_manifest = []
    for f in sql_files:
        task_id = f.stem
        meta = meta_by_task.get(task_id, {})
        target_table_raw = meta.get("target_table") or task_id
        target_table = f"{prefix}{target_table_raw}".upper()
        merge_keys = meta.get("merge_keys", [])
        sink_mode = (meta.get("sink_mode") or "").lower()
        kind = meta.get("kind", "aggregate")

        if not meta:
            sys.exit(f"[ERROR] {task_id} ไม่พบใน raw manifest - target_table/merge_keys จะผิด "
                     f"กรุณารัน extract_workflow.py ใหม่ก่อน")
        if kind == "export_jdbc":
            print(f"[SKIP] {task_id} เป็น export ออกนอก Oracle (kind=export_jdbc) "
                  f"ต้องทำเป็น ODI mapping ไม่ใช่ procedure - ข้ามการ gen DML")
            continue

        converted_sql = f.read_text(encoding="utf-8")

        # --- PL/SQL block (DECLARE/BEGIN) เช่น pre/post check: ส่งผ่านเป็น 1 step ไม่ห่อ DML ---
        plsql = as_plsql_block(converted_sql)
        if plsql is not None:
            readonly = not WRITE_DML_RE.search(plsql)
            strategy_used = "plsql pass-through (DECLARE/BEGIN block)" + (" read-only" if readonly else "")
            header = (
                f"-- ============================================================\n"
                f"-- ODI Procedure Body: {task_id}\n"
                f"-- Target Table      : {target_table if not readonly else '(none - read-only PL/SQL block)'}\n"
                f"-- Generated         : {datetime.now().isoformat(timespec='seconds')}\n"
                f"-- Strategy          : {strategy_used}\n"
                f"-- Error Handling    : {error_handling}\n"
                f"-- ============================================================\n\n"
            )
            out_path = dml_dir / f"{task_id}.sql"
            pending_writes.append((out_path, header + f"{STEP_MARKER}STEP_1_PLSQL\n{plsql}\n"))
            entry = {"task_id": task_id, "target_table": target_table, "strategy_used": strategy_used,
                     "dml_file": str(out_path.as_posix()), "procedure_name": f"PRC_{task_id}",
                     "sink_mode": sink_mode, "merge_keys": [], "columns": [], "steps": ["STEP_1_PLSQL"]}
            if readonly:
                entry["readonly"] = True   # ไม่นับเป็น target ใน DDL/preflight/backfill/validation
            dml_manifest.append(entry)
            ok_lines.append(f"[OK] {task_id} -> {out_path} ({strategy_used}, 1 step)")
            continue

        cols = derive_columns(converted_sql)
        if not cols:
            print(f"[WARN] {task_id} แกะ column list ไม่ได้ - DML จะไม่มี column list ต้องเติมเอง")

        error_clause = ""
        if error_handling == "errlog":
            error_clause = build_error_log_clause(target_table, f"{project_name}_{task_id}")

        strategy = load_strategy
        if strategy == "smart":
            if sink_mode == "append":
                # K-E1 (setup_migrate 2.7.2): Append + keyColumns -> INSERT (Append wins over merge_keys) - ถ้า SA ต้องการ MERGE ให้ตั้ง load_strategy=upsert
                strategy_used = "append (smart->sinkOption.mode=Append" + (f", keyColumns={','.join(merge_keys)} ignored" if merge_keys else "") + ")"
                dml = build_append_dml(target_table, converted_sql, cols, error_clause)
            elif merge_keys:
                strategy_used = f"merge (smart->merge_keys={','.join(merge_keys)}, sink_mode={sink_mode})"
                dml = build_merge_dml(target_table, converted_sql, merge_keys, error_clause, cols)
            elif sink_mode == "append":
                # สำคัญ: task ที่ source เป็น Append ห้าม TRUNCATE เด็ดขาด (data loss)
                strategy_used = "append (smart->sinkOption.mode=Append)"
                dml = build_append_dml(target_table, converted_sql, cols, error_clause)
            else:
                strategy_used = f"overwrite (smart->sinkOption.mode={sink_mode or 'unknown'})"
                if not sink_mode:
                    print(f"[WARN] {task_id} ไม่มีทั้ง merge_keys และ sink_mode - fallback overwrite "
                          f"(TRUNCATE) กรุณายืนยันกับ SA")
                dml, strategy_used = overwrite_with_decision(task_id, target_table_raw, target_table, converted_sql,
                                                              error_clause, cols, part_info, pending, strategy_used)
        elif strategy == "upsert":
            if not merge_keys:
                sys.exit(f"[ERROR] {task_id} เลือก upsert แต่ไม่มี merge_keys ใน manifest - "
                          f"กรุณาระบุ merge_keys ใน export_workflow.json แล้ว extract ใหม่")
            strategy_used = "merge (upsert)"
            dml = build_merge_dml(target_table, converted_sql, merge_keys, error_clause, cols)
        else:  # overwrite
            strategy_used = "overwrite"
            dml, strategy_used = overwrite_with_decision(task_id, target_table_raw, target_table, converted_sql,
                                                          error_clause, cols, part_info, pending, strategy_used)

        header = (
            f"-- ============================================================\n"
            f"-- ODI Procedure Body: {task_id}\n"
            f"-- Target Table      : {target_table}\n"
            f"-- Generated         : {datetime.now().isoformat(timespec='seconds')}\n"
            f"-- Strategy          : {strategy_used}\n"
            f"-- Error Handling    : {error_handling}\n"
            f"-- ============================================================\n\n"
        )

        steps = dml if isinstance(dml, list) else [("MAIN", dml)]
        step_names = []
        blocks = []
        for i, (kind_name, body) in enumerate(steps, 1):
            step_name = f"STEP_{i}_{kind_name}"
            step_names.append(step_name)
            blocks.append(f"{STEP_MARKER}{step_name}\n{body}")
        out_path = dml_dir / f"{task_id}.sql"
        pending_writes.append((out_path, header + "\n\n".join(blocks) + "\n"))

        dml_manifest.append({
            "task_id": task_id,
            "target_table": target_table,
            "strategy_used": strategy_used,
            "dml_file": str(out_path.as_posix()),
            "procedure_name": f"PRC_{task_id}",
            "sink_mode": sink_mode,
            "merge_keys": merge_keys,
            "columns": cols,
            "steps": step_names,
        })
        ok_lines.append(f"[OK] {task_id} -> {out_path} ({strategy_used}, {len(step_names)} step)")

    if pending:
        print("\n[ERROR] หยุดก่อนเขียนไฟล์ใด ๆ - มี task ที่ต้องให้คนตัดสินใจ (I14) ก่อน ไม่เดาให้:", file=sys.stderr)
        for tid, tbl, why in pending:
            print(f"  - {tid} / ตาราง {tbl}: {why}", file=sys.stderr)
        print("วิธีแก้: เปิด config/partitions_check.csv กรอกคอลัมน์ DECISION ของตารางเหล่านี้ตามที่ SA ตอบ I14 "
              "(delete_by_partition = DELETE เฉพาะ partition แล้ว INSERT [แนะนำ] | truncate_all = ล้างทั้งตาราง) "
              "แล้วรัน gen_dml.py ใหม่", file=sys.stderr)
        sys.exit(1)
    # K3 (SS_PAYMENT_3BB_VDO 2026-10-15): schema_mode=odiref -> ชื่อตารางปลายทางใน DML (TRUNCATE/DELETE/INSERT/MERGE)
    # ต้องเป็น odiRef ด้วย ไม่ใช่ target_table_prefix แบบ literal (เดิม hardcode DSSDEV. แม้ SQL ส่วน SELECT เป็น odiref)
    _mode = (config.get("schema_mode") or "literal").strip().lower()
    _lit = (prefix or "").strip().upper()
    if _mode == "odiref" and _lit:
        _lit = _lit if _lit.endswith(".") else _lit + "."
        _ls = ((config.get("odi") or {}).get("logical_schema") or "").strip()
        _tag = '<%=odiRef.getSchemaName("' + _ls + '","D")%>.'
        pending_writes = [(_p, "\n".join(_ln if _ln.lstrip().startswith("--") else _ln.replace(_lit, _tag)
                                          for _ln in _txt.split("\n"))) for _p, _txt in pending_writes]
    for _p, _txt in pending_writes:
        _p.write_text(_txt, encoding="utf-8")
    for _l in ok_lines:
        print(_l)

    # เก็บ entry ที่ SA เพิ่มเองไว้ (เช่น non-SQL task 080000 cleanup) - มิฉะนั้นรันซ้ำแล้ว procedure หายจาก XML
    # เงื่อนไข: task_id ไม่ได้ถูก generate รอบนี้ + raw manifest ระบุเป็น kind=non_sql + ไฟล์ DML ยังอยู่
    generated = {e["task_id"] for e in dml_manifest}
    non_sql_ids = {m["task_id"] for m in raw_manifest if m.get("kind") == "non_sql"}
    if dml_manifest_path.exists():
        try:
            previous = json.loads(dml_manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = []
        for e in previous:
            tid = e.get("task_id", "")
            base_id = "_".join(tid.split("_")[:2])
            # K5 (2026-09-28): entry ที่ SA/agent เพิ่มเองโดยไม่มี task ต้นทาง (เช่น precheck guard) ใส่ "manual": true
            if tid in generated or (base_id not in non_sql_ids and not e.get("manual")):
                continue
            if not Path(e.get("dml_file", "")).is_file():
                print(f"[WARN] manual entry {tid} หายไป: ไม่พบ {e.get('dml_file')} - ไม่ได้เก็บไว้ใน manifest")
                continue
            dml_manifest.append(e)
            print(f"[KEEP] {tid} (manual non-SQL entry, {e.get('strategy_used')})")

    dml_manifest_path.write_text(json.dumps(dml_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n[SUMMARY] สร้าง DML แล้ว {len(dml_manifest)} ไฟล์")
    print(f"[SUMMARY] dml manifest: {dml_manifest_path}")
    print("\nขั้นตอนถัดไป: python scripts/pipeline/build_odi_export.py")


if __name__ == "__main__":
    main()
