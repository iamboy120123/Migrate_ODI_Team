"""
gen_preflight_pack.py  (kit K3, 2026-09-30)
-------------------------------------------
Phase 0 / G0 — สร้าง Run Pack ตรวจ environment ให้คนรัน (courier loop) ก่อนใช้ข้อมูลจริง
ครอบคลุม PREFLIGHT ข้อ 2, 3, 5 และข้อมูลที่ต้องใช้ตอบ Q (Spark config / data contract ของ landing / work repository)

Output: run_packs/rp00_preflight_<YYYYMMDD>/
    README.md                 ลำดับรัน + ผลที่คาด + PREFLIGHT/Q ที่แต่ละไฟล์ใช้ยืนยัน
    P1_oracle_env.sql         DB version, user, NLS, timezone        (Oracle Dev — SELECT เดียว)
    P2_oracle_privileges.sql  session privileges / roles ของ work user (Oracle Dev — SELECT เดียว)
    P3_source_columns.sql     all_tab_columns ของ landing/source      (Oracle Dev — SELECT เดียว)
    P4_work_repo_schema.sql   owner ของตาราง SNP_* (work repository)  (Oracle Dev — SELECT เดียว)
    P5_blendata_spark_conf.sql ค่า Spark config ที่มีผลต่อ semantics  (Blendata / Spark SQL)
    (ผลที่ export ได้ วางที่ input/run_results/<ชื่อ pack>/ ไม่ใช่ในโฟลเดอร์นี้)

source object มาจาก (ตามลำดับ): converted SQL -> raw SQL -> config.profile.landing_table
ไม่ต้องมี DDL / DML / XML (ใช้ได้ตั้งแต่ Phase 0) · ทุกไฟล์ Oracle เป็น SELECT เดียว ไม่มี SET/SPOOL/';'

Usage:
    python scripts/runpack/gen_preflight_pack.py [--config config/config.json]
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))
from gen_dba_prereq import collect_source_refs  # noqa: E402

SPARK_CONF = ["spark.sql.ansi.enabled", "spark.sql.legacy.timeParserPolicy", "spark.sql.parser.escapedStringLiterals",
              "spark.sql.session.timeZone", "spark.sql.storeAssignmentPolicy", "spark.sql.legacy.sizeOfNull"]


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def odcilist(names) -> str:
    return "sys.odcivarchar2list(" + ", ".join(q(n) for n in names) + ")"


def source_objects(config: dict) -> tuple:
    paths = config.get("paths") or {}
    for key, label in (("output_converted_sql", "converted SQL"), ("output_raw_sql", "raw SQL")):
        d = ROOT / (paths.get(key) or "")
        if paths.get(key) and d.is_dir() and any(d.glob("*.sql")):
            refs = collect_source_refs(d, config)
            if refs:
                return sorted(refs), label
    lt = ((config.get("profile") or {}).get("landing_table") or (config.get("precheck") or {}).get("landing_table") or "").strip()
    return ([lt.split(".")[-1].upper()] if lt else []), "config landing_table"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    args = ap.parse_args()
    config = json.loads((ROOT / args.config).read_text(encoding="utf-8"))
    odi = config.get("odi") or {}
    work_user = (odi.get("work_user") or "").upper()
    if not work_user:
        sys.exit("[ERROR] config.odi.work_user ว่าง")
    day = datetime.now().strftime("%Y%m%d")
    existing = sorted((ROOT / "run_packs").glob("rp00_preflight_*"))
    pack = existing[-1] if existing else ROOT / "run_packs" / f"rp00_preflight_{day}"
    res_dir = Path("input") / "run_results" / pack.name
    pack.mkdir(parents=True, exist_ok=True)
    res_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().isoformat(timespec="seconds")
    objs, src_label = source_objects(config)
    wr = (odi.get("work_repo_schema") or "").upper()

    hdr = lambda name, where: (f"-- {name} ({stamp}) - run on {where}\n"
                               "-- single SELECT: run with Ctrl+Enter, export result as CSV (with header) into input/run_results/<this pack name>/\n")
    files = {}
    files["P1_oracle_env.sql"] = hdr("P1 Oracle environment", f"Oracle Dev as {work_user}") + (
        "SELECT 'DB_VERSION' AS check_name, product AS item, version AS result FROM product_component_version WHERE UPPER(product) LIKE '%DATABASE%'\n"
        "UNION ALL SELECT 'CURRENT_USER', 'user', USER FROM dual\n"
        f"UNION ALL SELECT 'IS_WORK_USER', {q(work_user)}, CASE WHEN USER = {q(work_user)} THEN 'YES' ELSE 'NO' END FROM dual\n"
        "UNION ALL SELECT 'DB_TIMEZONE', 'dbtimezone', DBTIMEZONE FROM dual\n"
        "UNION ALL SELECT 'SESSION_TIMEZONE', 'sessiontimezone', SESSIONTIMEZONE FROM dual\n"
        "UNION ALL SELECT 'SYSDATE', 'sysdate', TO_CHAR(SYSDATE, 'YYYY-MM-DD HH24:MI:SS') FROM dual\n"
        "UNION ALL SELECT 'NLS_DB', parameter, value FROM nls_database_parameters WHERE parameter IN "
        "('NLS_CHARACTERSET', 'NLS_NCHAR_CHARACTERSET', 'NLS_DATE_FORMAT', 'NLS_TIMESTAMP_FORMAT', 'NLS_LENGTH_SEMANTICS', 'NLS_SORT', 'NLS_COMP')\n"
        "UNION ALL SELECT 'NLS_SESSION', parameter, value FROM nls_session_parameters WHERE parameter IN "
        "('NLS_DATE_FORMAT', 'NLS_TIMESTAMP_FORMAT', 'NLS_TERRITORY', 'NLS_LANGUAGE', 'NLS_LENGTH_SEMANTICS')\n"
        "ORDER BY 1, 2\n")
    files["P2_oracle_privileges.sql"] = hdr("P2 privileges", f"Oracle Dev as {work_user}") + (
        "SELECT 'SYS_PRIV' AS kind, privilege AS name FROM session_privs\n"
        "UNION ALL SELECT 'ROLE', role FROM session_roles\n"
        "UNION ALL SELECT 'QUOTA', tablespace_name || ':' || CASE WHEN max_bytes = -1 THEN 'UNLIMITED' ELSE TO_CHAR(max_bytes) END FROM user_ts_quotas\n"
        "ORDER BY 1, 2\n")
    if objs:
        files["P3_source_columns.sql"] = hdr(f"P3 source/landing columns ({len(objs)} object from {src_label})", "Oracle Dev") + (
            "SELECT c.owner, c.table_name, c.column_id, c.column_name, c.data_type, c.data_length, c.data_precision, c.data_scale, c.nullable\n"
            f"FROM all_tab_columns c WHERE c.table_name IN (SELECT column_value FROM TABLE({odcilist(objs)}))\n"
            "UNION ALL\n"
            "SELECT NULL, t.column_value, NULL, 'MISSING_OBJECT', NULL, NULL, NULL, NULL, NULL\n"
            f"FROM TABLE({odcilist(objs)}) t WHERE NOT EXISTS (SELECT 1 FROM all_tab_columns a WHERE a.table_name = t.column_value)\n"
            "ORDER BY 2, 1, 3\n")
    files["P4_work_repo_schema.sql"] = hdr("P4 work repository schema", "Oracle Dev (user that can see SNP_* tables)") + (
        "SELECT owner, table_name, 'expected: not SYSTEM (G6.M4)' AS note FROM all_tables\n"
        "WHERE table_name IN ('SNP_SESSION', 'SNP_SESS_TASK_LOG', 'SNP_PROJECT', 'SNP_VAR')\n"
        "ORDER BY 1, 2\n")
    files["P5_blendata_spark_conf.sql"] = (
        f"-- P5 Spark config ({stamp}) - run on Blendata SQL editor / spark-sql (NOT Oracle)\n"
        "-- SET <key> only displays the current value in Spark; screenshot or export each result into input/run_results/<this pack name>/\n"
        + "".join(f"SET {k};\n" for k in SPARK_CONF))

    rows = [
        ("P1", "Oracle Dev", "P1_oracle_env.sql", "PREFLIGHT 2 (login = work user) · NLS/timezone → `knowledge/environment-facts.md` · Q5 schedule/timezone", "DB 19.x · IS_WORK_USER = YES"),
        ("P2", "Oracle Dev", "P2_oracle_privileges.sql", "PREFLIGHT 5 (สิทธิ์) · G6.M4", "CREATE TABLE / CREATE PROCEDURE / quota"),
        ("P3", "Oracle Dev", "P3_source_columns.sql", "PREFLIGHT 3 · **Q4 data contract** · lessons L1 (ชนิดจริงของ landing ก่อนแปลง SQL)", "ไม่มีแถว MISSING_OBJECT"),
        ("P4", "Oracle Dev", "P4_work_repo_schema.sql", "**Q7 work repository** · `config.odi.work_repo_schema`" + (f" (ปัจจุบัน `{wr}`)" if wr else ""), "owner ไม่ใช่ SYSTEM"),
        ("P5", "Blendata", "P5_blendata_spark_conf.sql", "**Q3 Spark config** · lessons L7–L9", "ค่าของทุก key"),
    ]
    rows = [r for r in rows if r[2] in files]
    readme = [f"# Run Pack {pack.name} — Pre-flight (Phase 0 / G0)", "",
              f"Generated: {stamp} · `python scripts/runpack/gen_preflight_pack.py` · work user `{work_user}` · source object {len(objs)} ตัว (จาก {src_label})", "",
              "ทุกไฟล์ Oracle เป็น **SELECT เดียว** → Ctrl+Enter ได้ · export CSV (มี header) ลง `{res_dir.as_posix()}/` ชื่ออะไรก็ได้ · P5 รันใน Blendata (ไม่ใช่ Oracle)", "",
              "| # | ที่รัน | ไฟล์ | ใช้ยืนยัน | ผลที่คาด |", "|---|---|---|---|---|"]
    readme += [f"| {a} | {b} | `{c}` | {d} | {e} |" for a, b, c, d, e in rows]
    readme += ["", "## หลังรันเสร็จ", "",
               f"1. วางผลทั้งหมดใน `{res_dir.as_posix()}/`",
               "2. ใน Claude Code พิมพ์ `/preflight` อีกครั้ง — agent จะอ่านผล สรุปข้อที่ผ่าน/ไม่ผ่าน และบันทึกข้อเท็จจริงใน `knowledge/environment-facts.md`",
               "3. SA ติ๊ก ✅ ใน `status/PREFLIGHT_CHECKLIST.md` และตอบ Q3 / Q4 / Q7 ใน `status/OPEN_DECISIONS.md` เอง (agent ติ๊กแทนไม่ได้)"]
    if not objs:
        readme += ["", "⚠️ ยังไม่รู้ชื่อ landing/source — ไม่ได้สร้าง P3 · ใส่ `profile.landing_table` ใน config หรือรันหลัง extract"]
    for name, body in files.items():
        (pack / name).write_text(body, encoding="utf-8")
    (pack / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    print(f"[OK] {pack.relative_to(ROOT).as_posix()}/ — " + ", ".join(["README.md"] + list(files)))
    print(f"[INFO] source object {len(objs)} ตัว จาก {src_label}" + (f": {', '.join(objs[:8])}" if objs else ""))


if __name__ == "__main__":
    main()
