"""
gen_dba_prereq.py
------------------
Runbook Phase 6 (DBA Prerequisites)

หน้าที่:
    อ่าน output/dml/_manifest.json แล้ว generate script ที่ DBA ต้องรันบน Oracle target
    ก่อน Smart Import และก่อนรัน ODI Package ครั้งแรก:

        output/dba/01_create_error_log_tables.sql  - สร้าง error log table ให้ทุก target
        output/dba/02_preflight_checks.sql         - ตรวจความพร้อมก่อนรันจริง
        output/dba/README.md                       - ลำดับการรันและสิ่งที่ต้องยืนยัน

    ชื่อ error log table ถูก derive ด้วย logic เดียวกับ build_error_log_clause() ใน
    gen_dml.py เพื่อให้ตรงกับ LOG ERRORS clause ใน DML เสมอ

Usage:
    python scripts/pipeline/gen_dba_prereq.py [--config config/config.json]
"""

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime

ORACLE_MAX_IDENT = 128       # Oracle 12.2+ (COMPATIBLE >= 12.2)
ORACLE_LEGACY_IDENT = 30     # COMPATIBLE < 12.2


def err_table_for(target_table: str) -> str:
    """ต้องตรงกับ build_error_log_clause() ใน gen_dml.py"""
    if "." in target_table:
        schema, tbl = target_table.rsplit(".", 1)
        return f"{schema}.ERR_{tbl}".upper()
    return f"ERR_{target_table}".upper()


TRUNCATE_RE = re.compile(r"EXECUTE\s+IMMEDIATE\s+'TRUNCATE\s+TABLE", re.I)
SRC_REF_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_$#]*(?:\.[A-Za-z_][A-Za-z0-9_$#]*)?)", re.I)
CTE_RE = re.compile(r"(?:\bWITH|,)\s*([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", re.I)


def strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


def task_no(task_id: str) -> str:
    m = re.search(r"_(\d{6})_", task_id)
    return m.group(1) if m else task_id


def uses_truncate(entry: dict) -> bool:
    """นับจากเนื้อ DML จริง (ไม่นับ comment) - fallback เป็นชื่อ step ถ้าเปิดไฟล์ไม่ได้"""
    f = Path(entry.get("dml_file", ""))
    if f.is_file():
        return bool(TRUNCATE_RE.search(strip_sql_comments(f.read_text(encoding="utf-8"))))
    return any("TRUNCATE" in step.upper() for step in entry.get("steps", []))


def dml_kinds(entry: dict) -> set:
    """ชนิด DML ที่ procedure ใช้จริง -> ใช้คำนวณสิทธิ์ขั้นต่ำต่อ target"""
    kinds = set()
    for step in entry.get("steps", []):
        for k in ("TRUNCATE", "INSERT", "MERGE", "UPDATE", "DELETE"):
            if k in step.upper():
                kinds.add(k)
    return kinds


def required_privs(kinds: set) -> list:
    privs = set()
    if kinds & {"INSERT", "MERGE"}:
        privs.add("INSERT")
    if kinds & {"MERGE", "UPDATE"}:
        privs |= {"UPDATE", "SELECT"}
    if "DELETE" in kinds:
        privs |= {"DELETE", "SELECT"}
    return sorted(privs)


def in_scope_sql(sql_dir: Path, config: dict) -> list:
    """converted SQL ที่อยู่ใน scope — ข้าม task ใน config.scope.excluded_tasks (เช่น 999999 export→MSSQL)"""
    excluded = set((config.get("scope") or {}).get("excluded_tasks") or [])
    files = []
    for f in sorted(Path(sql_dir).glob("*.sql")):
        if any(f"_{t}_" in f.stem for t in excluded):
            continue
        files.append(f)
    return files


def collect_source_refs(sql_dir: Path, config: dict = None) -> dict:
    """{OBJECT_NAME_UPPER: {"qualified": bool, "files": set(task_no)}} จาก converted SQL ทุกไฟล์"""
    refs = {}
    if not sql_dir.is_dir():
        return refs
    for f in in_scope_sql(sql_dir, config or {}):
        sql = strip_sql_comments(f.read_text(encoding="utf-8"))
        ctes = {c.upper() for c in CTE_RE.findall(sql)}
        m = re.search(r"_(\d{6})_", f.stem)
        tag = m.group(1) if m else f.stem
        for raw in SRC_REF_RE.findall(sql):
            name = raw.split(".")[-1].upper()
            if name == "DUAL" or name in ctes:
                continue
            r = refs.setdefault(name, {"qualified": False, "unqualified": False, "files": set()})
            r["qualified" if "." in raw else "unqualified"] = True
            r["files"].add(tag)
    return refs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.json")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    manifest_path = Path(config["paths"]["dml_manifest"])
    if not manifest_path.exists():
        sys.exit(f"[ERROR] ไม่พบ {manifest_path} - รัน gen_dml.py ก่อน")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # entry readonly (เช่น 000000 precheck) ไม่ได้เขียน target -> ไม่นับเป็น target table
    manifest = [e for e in manifest if not e.get("readonly")]
    error_handling = config.get("error_handling", "errlog")
    project = config.get("project_name", "MIGRATION")
    out_dir = Path("output/dba")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().isoformat(timespec="seconds")

    # dedupe target table (หลาย task เขียนตารางเดียวกันได้ เช่น workflow_status)
    targets = []
    for e in manifest:
        t = e["target_table"]
        if t not in targets:
            targets.append(t)

    truncate_procs = [e for e in manifest if uses_truncate(e)]
    truncate_count = len(truncate_procs)
    truncate_task_nos = sorted(task_no(e["task_id"]) for e in truncate_procs)
    cleanup_task_nos = sorted(task_no(e["task_id"]) for e in truncate_procs if "cleanup" in e["task_id"])

    # สิทธิ์ขั้นต่ำต่อ target (union ของทุก procedure ที่เขียนตารางนั้น)
    tgt_kinds = {}
    for e in manifest:
        tgt_kinds.setdefault(e["target_table"], set()).update(dml_kinds(e))

    # source object ที่ SQL อ้างถึงแต่ kit ไม่ได้สร้าง (ไม่ใช่ target ของ task ใด)
    target_names = {t.split(".")[-1].upper() for t in targets}
    src_refs = collect_source_refs(Path(config["paths"].get("output_converted_sql", "output/sql/converted")), config)
    external = {k: v for k, v in sorted(src_refs.items()) if k not in target_names}
    unqualified = sorted(k for k, v in src_refs.items() if v["unqualified"])
    max_name_len = max((len(n) for t in targets for n in [t.split(".")[-1]]), default=0)

    warnings = []
    for t in targets:
        names = [t.split(".")[-1]]
        if error_handling == "errlog":
            names.append(err_table_for(t).split(".")[-1])
        for name in names:
            if len(name) > ORACLE_MAX_IDENT:
                warnings.append(f"{name} ({len(name)} ตัวอักษร) เกิน {ORACLE_MAX_IDENT} - ใช้ไม่ได้บน Oracle 19c")
            elif len(name) > ORACLE_LEGACY_IDENT:
                warnings.append(f"{name} ({len(name)} ตัวอักษร) เกิน {ORACLE_LEGACY_IDENT} - "
                                f"ใช้ได้เฉพาะเมื่อ COMPATIBLE >= 12.2")

    # ---------- 01: error log tables ----------
    if error_handling == "errlog":
        lines = [
            f"-- 01_create_error_log_tables.sql  (generated {stamp})",
            f"-- Project: {project}",
            "-- รันด้วย user ที่มีสิทธิ์ CREATE TABLE ใน schema เป้าหมาย",
            "-- skip_unsupported => TRUE เพื่อข้ามคอลัมน์ชนิดที่ error logging ไม่รองรับ (LOB/LONG/object)",
            "-- idempotent: ถ้า error log table มีอยู่แล้วจะข้าม ไม่ error",
            "",
            "BEGIN",
        ]
        for t in targets:
            err = err_table_for(t)
            owner, err_name = (err.split(".", 1) + [None])[:2] if "." in err else (None, err)
            lines += [
                "  BEGIN",
                f"    DBMS_ERRLOG.CREATE_ERROR_LOG(",
                f"      dml_table_name     => '{t.upper()}',",
                f"      err_log_table_name => '{err_name}',",
            ]
            if owner:
                lines.append(f"      err_log_table_owner=> '{owner}',")
            lines += [
                "      skip_unsupported   => TRUE);",
                f"    DBMS_OUTPUT.PUT_LINE('created {err}');",
                "  EXCEPTION",
                "    WHEN OTHERS THEN",
                "      IF SQLCODE = -955 THEN",          # ORA-00955 name already used
                f"        DBMS_OUTPUT.PUT_LINE('skip (exists): {err}');",
                "      ELSE RAISE; END IF;",
                "  END;",
            ]
        lines += ["END;", ""]   # ไม่ใส่ "/" (คำสั่ง SQL*Plus) - Alt+X/Execute Script ของ DBeaver ปิด block ที่ END; เอง
        (out_dir / "01_create_error_log_tables.sql").write_text("\n".join(lines), encoding="utf-8")
    else:
        (out_dir / "01_create_error_log_tables.sql").write_text(
            f"-- error_handling = '{error_handling}' (ไม่ใช่ errlog) จึงไม่ต้องสร้าง error log table\n",
            encoding="utf-8")

    # ---------- 02: preflight checks ----------
    tgt_list = ",\n         ".join(f"'{t.split('.')[-1].upper()}'" for t in targets)
    err_list = ",\n         ".join(f"'{err_table_for(t).split('.')[-1]}'" for t in targets)
    schemas = sorted({t.rsplit(".", 1)[0].upper() for t in targets if "." in t}) or ["USER"]
    schema_pred = ", ".join(f"'{s}'" for s in schemas)

    if error_handling == "errlog":
        errlog_check = f"""-- [3] error log table ต้องมีครบ (รัน 01_create_error_log_tables.sql ก่อน)
SELECT 'ERROR_LOG_TABLES' AS check_name, COUNT(*) AS found, {len(targets)} AS expected
FROM   all_tables
WHERE  owner IN ({schema_pred})
AND    table_name IN (
         {err_list});
"""
    else:
        errlog_check = (f"-- [3] error log table: ข้าม (error_handling = '{error_handling}')\n"
                        "--     DML ไม่มี LOG ERRORS clause แล้ว ตามมาตรฐาน Smart Export ของทีม\n")

    if max_name_len > ORACLE_LEGACY_IDENT:
        compat_comment = (f"-- [1] COMPATIBLE ต้อง >= 12.2 (ชื่อ target ยาวสุด {max_name_len} ตัวอักษร "
                          f"เกิน {ORACLE_LEGACY_IDENT})")
    else:
        compat_comment = (f"-- [1] COMPATIBLE: ชื่อ target ยาวสุด {max_name_len} ตัวอักษร ไม่เกิน "
                          f"{ORACLE_LEGACY_IDENT} - check นี้เป็น informational")

    priv_matrix = "\n".join(
        f"--   {t.split('.')[-1].upper():<60} {', '.join(required_privs(tgt_kinds.get(t, set()))) or '-'}"
        + ("  (+TRUNCATE)" if "TRUNCATE" in tgt_kinds.get(t, set()) else "")
        for t in targets)

    if external:
        ext_list = ",\n                       ".join(f"'{k}'" for k in external)
        ext_detail = "\n".join(
            f"--   {k:<50} ใช้ใน task {', '.join(sorted(v['files']))}"
            + ("" if v["qualified"] else "  [ไม่มี schema prefix]")
            for k, v in external.items())
        external_check = f"""-- [5] source object ที่ SQL อ้างถึงแต่ไม่ได้ generate โดย kit นี้ (external/view)
--     คำนวณจาก FROM/JOIN ใน converted SQL หักด้วย target ของทุก task:
{ext_detail}
SELECT 'EXTERNAL_OBJECTS' AS check_name, object_name, object_type, owner
FROM   all_objects
WHERE  object_name IN ({ext_list})
ORDER  BY object_name;
-- expected: ครบ {len(external)} object (ถ้าขาด = SQL จะ fail ตอนรัน ไม่ใช่ตอน import)
-- ODI work user ต้องมี SELECT บนทุก object ข้างบน (หรือผ่าน synonym)
"""
    else:
        external_check = "-- [5] external object: ไม่พบ source ที่อยู่นอก target ของ kit\n"

    work_user = (config.get("odi") or {}).get("work_user")  # Q16
    unq_list = ",\n                       ".join(f"'{k}'" for k in unqualified)
    if unqualified:
        resolve_owner = work_user.upper() if work_user else "&ODI_USER"
        resolve_check = f"""
-- [7] name resolution ของ {len(unqualified)} object ที่ SQL อ้างโดยไม่มี schema prefix (Q16)
--     ODI session รันเป็น {resolve_owner} -> ชื่อต้อง resolve ได้จาก object ของ {resolve_owner} เอง หรือ synonym (private/PUBLIC)
SELECT n.name AS object_name,
       CASE WHEN EXISTS (SELECT 1 FROM all_objects o WHERE o.owner = UPPER('{resolve_owner}') AND o.object_name = n.name
                         AND o.object_type IN ('TABLE','VIEW','MATERIALIZED VIEW'))
                 THEN 'OWN OBJECT'
            WHEN EXISTS (SELECT 1 FROM all_synonyms s WHERE s.owner IN (UPPER('{resolve_owner}'), 'PUBLIC') AND s.synonym_name = n.name)
                 THEN 'SYNONYM'
            ELSE '*** NOT RESOLVABLE -> ORA-00942 ***' END AS resolves_as
FROM  (SELECT column_value AS name FROM TABLE(sys.odcivarchar2list(
                       {unq_list}))) n
ORDER BY 2 DESC, 1;
-- expected: ไม่มีแถว NOT RESOLVABLE; external object ที่เป็น SYNONYM ต้องมี SELECT grant ให้ {resolve_owner} ด้วย
"""
    else:
        resolve_check = ""

    work_user_label = (work_user.upper() if work_user else "ODI work user")
    checks = f"""-- 02_preflight_checks.sql  (generated {stamp})
-- Project: {project}
-- รันทั้งไฟล์แล้วดูผล - ทุก check ต้องได้ผลตามคอลัมน์ EXPECTED ก่อนเริ่ม Phase 6 Smart Import

{compat_comment}
SELECT 'COMPATIBLE' AS check_name, value, '>= 12.2' AS expected
FROM   v$parameter WHERE name = 'compatible';

-- [2] target table ต้องมีครบ {len(targets)} ตาราง
SELECT 'TARGET_TABLES' AS check_name, COUNT(*) AS found, {len(targets)} AS expected
FROM   all_tables
WHERE  owner IN ({schema_pred})
AND    table_name IN (
         {tgt_list});

-- [2b] ตารางที่ยังขาด
SELECT t.tbl AS missing_target_table
FROM  (SELECT column_value AS tbl FROM TABLE(sys.odcivarchar2list(
         {tgt_list}))) t
WHERE NOT EXISTS (SELECT 1 FROM all_tables a
                  WHERE a.owner IN ({schema_pred}) AND a.table_name = t.tbl);

{errlog_check}
-- [4] สิทธิ์ของ ODI work user (แทน &ODI_USER ด้วย user จริงของ ODI Agent)
SELECT 'PRIVS' AS check_name, privilege, table_name
FROM   all_tab_privs
WHERE  grantee = UPPER('&ODI_USER')
AND    table_name IN (
         {tgt_list})
ORDER  BY table_name, privilege;
-- ผลว่าง = ไม่มี grant ตรงบนตาราง (ยังไม่ใช่ไม่มีสิทธิ์: อาจได้ผ่าน role/ANY privilege) -> ดูสิทธิ์จริงของ session ด้านล่าง
SELECT 'ANY_TABLE_PRIVS' AS check_name, privilege
FROM   session_privs
WHERE  privilege IN ('SELECT ANY TABLE', 'INSERT ANY TABLE', 'UPDATE ANY TABLE', 'DELETE ANY TABLE')
ORDER  BY privilege;
-- สิทธิ์ขั้นต่ำที่คำนวณจาก DML จริงของแต่ละ target (ถ้าเป็น owner ข้ามได้):
{priv_matrix}
-- TRUNCATE ต้องใช้ DROP ANY TABLE หรือเป็น owner เอง (ดู check [6])

{external_check}
-- [6] สิทธิ์ TRUNCATE ของ ODI work user
--     TRUNCATE เป็น DDL: ต้องเป็น owner ของตาราง หรือมี DROP ANY TABLE
--     DML ใช้ TRUNCATE TABLE ตรง ๆ (truncate_style=plain) หรือห่อ BEGIN EXECUTE IMMEDIATE (execute_immediate) — รันด้วยสิทธิ์ของ session
SELECT 'IS_OWNER' AS check_name,
       CASE WHEN UPPER('&ODI_USER') IN ({schema_pred}) THEN 'YES - ไม่ต้องขอ DROP ANY TABLE'
            ELSE 'NO - ต้องมี DROP ANY TABLE' END AS result
FROM   dual;

-- ใช้ session_privs (สิทธิ์ที่ session นี้ใช้ได้จริง รวมที่ได้ผ่าน role เช่น DBA) - ต้องรันด้วย user เดียวกับที่ ODI ต่อ DB
-- (all_sys_privs ไม่มีใน Oracle -> ORA-00942 / dba_sys_privs ไม่นับสิทธิ์ที่มาจาก role)
SELECT 'DROP_ANY_TABLE' AS check_name, COUNT(*) AS granted, '1 ถ้าไม่ได้เป็น owner (รันด้วย {work_user_label})' AS expected
FROM   session_privs
WHERE  privilege = 'DROP ANY TABLE';
{resolve_check}"""
    if work_user:
        checks = checks.replace("&ODI_USER", work_user.upper()).replace(
            "(แทน &ODI_USER ด้วย user จริงของ ODI Agent)", f"(work user = {work_user.upper()} ตาม Q16)")
        checks = checks.replace(f"(แทน {work_user.upper()} ด้วย user จริงของ ODI Agent)",
                                f"(work user = {work_user.upper()} ตาม config odi.work_user / Q16)")
    (out_dir / "02_preflight_checks.sql").write_text(checks, encoding="utf-8")

    # ---------- README ----------
    rd = [f"# Phase 6 — DBA Prerequisites ({project})", "",
          f"Generated: {stamp} | target tables: {len(targets)}", "",
          "## ลำดับการรัน", "",
          "1. สร้าง/ยืนยัน target table ทั้งหมดจาก `output/ddl/01_create_tables.sql` (DRAFT — "
           "ยืนยันความยาวคอลัมน์กับ `output/ddl/03_profile_source_lengths.sql` ก่อนรัน CREATE TABLE จริง)",
          "2. `01_create_error_log_tables.sql` — ใช้เฉพาะเมื่อ error_handling = errlog",
          "3. `02_preflight_checks.sql` — ต้องผ่านทุก check ก่อนรัน package",
          "4. **Smart Import** `output/odi_export/<package>.zip` เข้า ODI **Dev** (ทำครั้งเดียว หลังข้อ 1–3 เสร็จ; ไม่ใช่ Import Project)",
          "5. รัน package ใน Dev 1 รอบ แล้วไป Phase 7 (`output/validation/`)", "",
          "## Target tables", ""]
    if error_handling == "errlog":
        rd += ["| Target | Error log table |", "|---|---|"]
        for t in targets:
            rd.append(f"| `{t.upper()}` | `{err_table_for(t)}` |")
    else:
        rd += [f"error_handling = `{error_handling}` → ไม่มี error log table (DML ไม่มี `LOG ERRORS`)", "",
               "| Target |", "|---|"]
        for t in targets:
            rd.append(f"| `{t.upper()}` |")
    rd += ["", "## ⚠️ ต้องยืนยันก่อนรัน", "",
           f"- **TRUNCATE**: {truncate_count} procedure ใช้ `TRUNCATE TABLE` ซึ่งเป็น DDL "
           f"({', '.join(truncate_task_nos)}) — ODI work user ต้องเป็น owner",
           "  ของตาราง หรือมี `DROP ANY TABLE` ถ้าให้ไม่ได้ ต้องเปลี่ยนเป็น `DELETE` (ช้ากว่าและกิน UNDO)",
           "- **data type ของคอลัมน์ boolean** (`success`, `running`): converted SQL ส่งค่า string `'TRUE'`",
           "  DDL เป็น `VARCHAR2(5)` (D2-revised — ดู status/PHASE4_REVIEW_LOG.md)",
           "- **`cdr_id` ต้องเป็น VARCHAR2** (ใช้เป็น merge key ของ 050300)",
           "- **`effective_date` / `expired_date` ต้องเป็น DATE/TIMESTAMP** (converted SQL ใช้ `TRUNC()`)",
           "- **partition**: source เป็น Spark partitioned by `partition_date` — ถ้า target ทำ partition ด้วย",
           "  ให้พิจารณา `TRUNCATE PARTITION` แทน `TRUNCATE TABLE`",
           "- **Non-SQL tasks** (080000/000000; 999999 นอก scope ตาม config.scope): ดูสถานะและ design เต็มที่ "
           "`output/odi_export/NON_SQL_TASKS_DESIGN.md`"
           + "".join(f" — {n} (cleanup) รวมอยู่ใน {truncate_count} procedure ข้างต้นแล้ว" for n in cleanup_task_nos)]
    if external:
        rd += ["", f"## External source objects ({len(external)}) — kit ไม่ได้สร้างให้", "",
               "| Object | ใช้ใน task | schema prefix ใน SQL |", "|---|---|---|"]
        for k, v in external.items():
            rd.append(f"| `{k}` | {', '.join(sorted(v['files']))} | {'มี' if v['qualified'] else '**ไม่มี**'} |")
    if unqualified:
        rd += ["", "## ⚠️ Object ที่อ้างโดยไม่มี schema prefix", "",
               f"{len(unqualified)} object ใน converted SQL ไม่มี schema prefix — จะ resolve ตาม default schema "
               "ของ ODI work user / synonym / logical schema ของ ODI ต้องยืนยันว่าชี้ไปที่ schema ถูก "
               "(โดยเฉพาะ target ที่ INSERT ด้วย `<work_user>.` แต่ SELECT กลับโดยไม่มี prefix):", ""]
        rd += [f"- `{k}` (task {', '.join(sorted(src_refs[k]['files']))})" for k in unqualified]
    if warnings:
        rd += ["", "## ⚠️ ความยาวชื่อ object", ""] + [f"- {w}" for w in sorted(set(warnings))]
    (out_dir / "README.md").write_text("\n".join(rd) + "\n", encoding="utf-8")

    print(f"[OK] output/dba/01_create_error_log_tables.sql ({len(targets)} ตาราง)")
    n_checks = len(re.findall(r"^-- \[\d+\]", checks, flags=re.M))
    print(f"[OK] output/dba/02_preflight_checks.sql ({n_checks} checks, "
          f"{len(external)} external objects, {truncate_count} TRUNCATE procedures)")
    print(f"[OK] output/dba/README.md")
    for w in sorted(set(warnings)):
        print(f"[WARN] {w}")


if __name__ == "__main__":
    main()
