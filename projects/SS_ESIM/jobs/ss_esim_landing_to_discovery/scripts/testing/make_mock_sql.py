#!/usr/bin/env python3
"""make_mock_sql.py - turn the SAME seed CSV files used by spark_reference_run.py into Oracle INSERT scripts.
USE WHEN: before running the Oracle side - same seed CSV as spark_reference_run.py (step 3 of test-method).

Principle: ONE source of seed data.  The reference run (Spark) and the Oracle mock must be fed from the same CSV,
otherwise "same input" is not guaranteed.  This script never connects to a database - it only writes .sql text.
A human runs the output (project rule: the agent never runs DDL/DML).

USAGE
  python3 make_mock_sql.py --config test-config.json --schema MYSCHEMA --out mock_sql [--rows-per-insert 50]
Output: one file per seed (table + round), reset script, and a checks script with expected row counts.

RULES APPLIED
  * explicit column list (D-R1) taken from the config ddl (optionally narrowed by "oracle_columns" in the table spec: use it when the
    Oracle table has fewer columns than the Spark seed - e.g. a landing table without a full DDL), schema-qualified (D-R2), no trailing ';' inside a statement body
    except the statement terminator (one statement per ';')
  * INSERT ... SELECT ... FROM dual UNION ALL ...  (no CTE, no aliases that can hit a reserved word)
  * the CSV null token -> NULL ; an EMPTY field is an empty string in Spark but Oracle stores '' as NULL -> written as NULL
    (known difference - see knowledge/reference/test-method.md)
  * Spark boolean -> 1/0 ; timestamp -> TIMESTAMP 'YYYY-MM-DD HH24:MI:SS' ; date -> DATE 'YYYY-MM-DD'
  * warns when a column name is an Oracle reserved word (RAW, DATE, NUMBER, ...), because quoting would be needed
"""
import argparse, csv, json, os, re, sys

RESERVED = set("""ACCESS ADD ALL ALTER AND ANY AS ASC AUDIT BETWEEN BY CHAR CHECK CLUSTER COLUMN COMMENT COMPRESS CONNECT CREATE
CURRENT DATE DECIMAL DEFAULT DELETE DESC DISTINCT DROP ELSE EXCLUSIVE EXISTS FILE FLOAT FOR FROM GRANT GROUP HAVING IDENTIFIED
IMMEDIATE IN INCREMENT INDEX INITIAL INSERT INTEGER INTERSECT INTO IS LEVEL LIKE LOCK LONG MAXEXTENTS MINUS MLSLABEL MODE MODIFY
NOAUDIT NOCOMPRESS NOT NOWAIT NULL NUMBER OF OFFLINE ON ONLINE OPTION OR ORDER PCTFREE PRIOR PUBLIC RAW RENAME RESOURCE REVOKE ROW
ROWID ROWNUM ROWS SELECT SESSION SET SHARE SIZE SMALLINT START SUCCESSFUL SYNONYM SYSDATE TABLE THEN TO TRIGGER UID UNION UNIQUE
UPDATE USER VALIDATE VALUES VARCHAR VARCHAR2 VIEW WHENEVER WHERE WITH""".split())


def split_ddl(ddl):
    cols, depth, cur = [], 0, ""
    for ch in ddl:
        if ch == "(": depth += 1
        if ch == ")": depth -= 1
        if ch == "," and depth == 0:
            cols.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip(): cols.append(cur.strip())
    out = []
    for c in cols:
        n, t = c.split(None, 1)
        out.append((n, t.strip().lower()))
    return out


def lit(val, typ, null_token):
    if val is None or val == null_token or val == "":
        return "NULL"
    base = re.split(r"[( ]", typ)[0]
    if base in ("int", "integer", "bigint", "long", "smallint", "tinyint", "double", "float", "decimal", "numeric"):
        return val
    if base == "boolean":
        return "1" if val.strip().lower() in ("true", "1") else "0"
    if base == "timestamp":
        v = val.strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?$", v):
            raise ValueError("timestamp seed must be 'YYYY-MM-DD HH:MM:SS' - got %r" % val)
        return "TIMESTAMP '%s'" % v
    if base == "date":
        return "DATE '%s'" % val.strip()
    return "'" + val.replace("'", "''") + "'"


def write_sql(path, text):
    """Write a .sql file as ISO-8859-1. A character outside that set is refused (project rule), not silently replaced."""
    try:
        data = text.encode("iso-8859-1")
    except UnicodeEncodeError as e:
        bad = text[e.start:e.start + 20].replace("\n", " ")
        sys.stderr.write("ERROR: %s contains a character outside ISO-8859-1 near: %r - fix the seed CSV\n" % (os.path.basename(path), bad))
        sys.exit(2)
    with open(path, "wb") as f:
        f.write(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--schema", required=True, help="Oracle schema, e.g. MYSCHEMA")
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default=None)
    ap.add_argument("--rows-per-insert", type=int, default=50)
    ap.add_argument("--table-map", default=None, help="optional JSON file {spark_table: oracle_table} when names differ")
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    base = a.base or os.path.dirname(os.path.abspath(a.config))
    nt = cfg.get("null_token", "\\N")
    tmap = json.load(open(a.table_map)) if a.table_map else {}
    os.makedirs(a.out, exist_ok=True)
    schema = a.schema.lower()
    written, warn = [], []

    def emit(table, seed_path, fname, expected):
        ddl = split_ddl(cfg["tables"][table]["ddl"])
        otab = tmap.get(table, table)
        full = seed_path if os.path.isabs(seed_path) else os.path.join(base, seed_path)
        with open(full, encoding="utf-8", newline="") as f:
            rd = csv.reader(f); header = next(rd); rows = list(rd)
        if [h.lower() for h in header] != [c[0].lower() for c in ddl]:
            sys.exit("ERROR: header of %s does not match ddl of %s:\n  csv=%s\n  ddl=%s" % (seed_path, table, header, [c[0] for c in ddl]))
        for n, _ in ddl:
            if n.upper() in RESERVED:
                warn.append("%s.%s is an Oracle reserved word - check the real column name / quoting" % (table, n))
        keep = [i for i, (n, _) in enumerate(ddl) if not cfg["tables"][table].get("oracle_columns") or n.lower() in [c.lower() for c in cfg["tables"][table]["oracle_columns"]]]
        typ = [ddl[i][1] for i in keep]
        collist = ",".join(ddl[i][0] for i in keep)
        stmts = []
        for i in range(0, len(rows), a.rows_per_insert):
            chunk = rows[i:i + a.rows_per_insert]
            sel = []
            for r in chunk:
                if len(r) != len(ddl):
                    sys.exit("ERROR: %s row has %d fields, expected %d: %s" % (seed_path, len(r), len(ddl), r))
                sel.append("SELECT " + ",".join(lit(r[i], ddl[i][1], nt) for i in keep) + " FROM dual")
            stmts.append("INSERT INTO %s.%s\n  (%s)\n%s;" % (schema, otab, collist, "\nUNION ALL ".join(sel)))
        text = "-- %s : %d rows from %s\n-- generated by make_mock_sql.py - run by a human, then COMMIT\n%s\nCOMMIT;\n" % (otab, len(rows), os.path.basename(seed_path), "\n\n".join(stmts))
        write_sql(os.path.join(a.out, fname), text)
        written.append((fname, otab, len(rows)))
        expected.setdefault(otab, 0)
        expected[otab] += len(rows)

    expected = {}
    n = 0
    for table, spec in cfg["tables"].items():
        if spec.get("seed"):
            seeds = spec["seed"] if isinstance(spec["seed"], list) else [spec["seed"]]
            for s in seeds:
                n += 1; emit(table, s, "%02d_seed_%s.sql" % (n, table), expected)
    after_r1 = dict(expected)
    for r in cfg["rounds"]:
        for table, files in r.get("append", {}).items():
            for s in files:
                n += 1; emit(table, s, "%02d_%s_%s.sql" % (n, r["name"], table), {})

    reset = ["-- reset: empties every table of the test (TRUNCATE = DDL, human runs it)"]
    for t in cfg["tables"]:
        reset.append("TRUNCATE TABLE %s.%s;" % (schema, tmap.get(t, t)))
    write_sql(os.path.join(a.out, "00_reset.sql"), "\n".join(reset) + "\n")
    chk = ["-- row counts BEFORE any procedure runs (must match; otherwise the mock is not loaded as designed)"]
    parts = ["SELECT '%s' AS table_name, COUNT(*) AS row_count, %d AS expected FROM %s.%s" % (tmap.get(t, t), after_r1.get(tmap.get(t, t), 0), schema, tmap.get(t, t)) for t in cfg["tables"]]
    chk.append("\nUNION ALL ".join(parts) + ";")
    write_sql(os.path.join(a.out, "99_check_counts.sql"), "\n".join(chk) + "\n")
    print("Wrote %d seed scripts + reset + check to %s" % (len(written), a.out))
    for f, t, c in written: print("  %-40s %-60s %5d rows" % (f, t, c))
    for w in sorted(set(warn)): print("WARN:", w)


if __name__ == "__main__":
    main()
