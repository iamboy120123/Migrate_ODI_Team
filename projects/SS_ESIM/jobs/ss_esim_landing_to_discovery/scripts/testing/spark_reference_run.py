#!/usr/bin/env python3
"""spark_reference_run.py - run the ORIGINAL Blendata Spark SQL locally to produce the reference
("expected") results for an ODI migration test.   USE WHEN: you need the expected result from the ORIGINAL Spark SQL on your seed data (step 2 of test-method; one Spark config).

WHY: the goal of a migration test is "does ODI give the same result as the original Blendata job".
The expected result must therefore come from the ORIGINAL Spark SQL in the workflow JSON, never from
the converted Oracle SQL.  This script executes each SQL task of the DAG with PySpark (local mode) on
the seed data you supply, applies the sink semantics (overwrite / overwrite-by-partition / append) and
dumps the state of every table before and after every task.

WHAT IT DOES NOT DO (be honest in the report):
  * it does not talk to any database - seeds come from CSV files, results go to CSV files
  * it only runs tasks whose body has aggregationConfig.sql (service-job-aggregate); every other task
    (recover, retention/cleanup, export ...) is reported as NOT SIMULATED
  * Spark version / spark configs are what you put in the config - they are NOT read from Blendata
  * now() is the real clock of the machine running this script (one value per query)
  * Delta/keyColumns merge semantics are NOT emulated: Append is a plain append

USAGE
  python3 spark_reference_run.py --workflow export_workflow.json --config test-config.json --out ref_out
Requires: pyspark (pip install pyspark) and a Java runtime.  Run python with -I when the inputs are untrusted.

CONFIG (JSON) - see references/example/mock-test/test-config.example.json
  {
    "spark": {"ansi": false, "timeParserPolicy": "CORRECTED", "timeZone": null},   # null = machine tz
    "udfs": {"get_user": "blendata"},                  # zero-arg string UDFs the SQL calls
    "null_token": "\\N",                               # CSV token meaning NULL (empty field = empty string)
    "tables": {                                         # every table the SQL reads or writes
       "<table>": {"ddl": "col type, col type", "seed": "seed/x.csv" | null}   # null = exists but empty
    },
    "skip_tasks": ["000000", "080000", "999999"],      # task-name prefixes not to run
    "rounds": [                                         # each round = optional appends, then run the DAG once
       {"name": "round1"},
       {"name": "round2", "append": {"<table>": ["seed/round2.csv"]}}
    ]
  }
"""
import argparse, csv, json, os, sys, shutil, datetime


def die(msg):
    sys.stderr.write("ERROR: %s\n" % msg)
    sys.exit(2)


def load_tasks(path):
    with open(path, encoding="utf-8-sig") as f:
        d = json.load(f)
    tasks = []
    for m in d.get("airflowExportModels", []):
        for v in m.get("versions", []):
            if v.get("latest") is False and len(m["versions"]) > 1:
                continue
            tasks = json.loads(v["taskDetailString"])
            break
        if tasks:
            break
    if not tasks:
        die("no taskDetailString found in %s (see knowledge/reference/blendata-json-schema.md for the structure)" % path)
    return tasks


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default=None, help="folder that seed paths in the config are relative to (default: config folder)")
    a = ap.parse_args()

    cfg = json.load(open(a.config, encoding="utf-8"))
    base = a.base or os.path.dirname(os.path.abspath(a.config))
    null_token = cfg.get("null_token", "\\N")

    from pyspark.sql import SparkSession, functions as F, types as T
    sp = cfg.get("spark", {})
    b = (SparkSession.builder.master("local[2]").appName("blendata-reference")
         .config("spark.sql.ansi.enabled", str(sp.get("ansi", False)).lower())
         .config("spark.sql.legacy.timeParserPolicy", sp.get("timeParserPolicy", "CORRECTED"))
         .config("spark.sql.shuffle.partitions", "2").config("spark.ui.enabled", "false"))
    if sp.get("timeZone"):
        b = b.config("spark.sql.session.timeZone", sp["timeZone"])
    spark = b.getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    for name, val in cfg.get("udfs", {}).items():
        spark.udf.register(name, (lambda v: (lambda: v))(val), T.StringType())

    def materialize(df):
        return spark.createDataFrame(df.collect(), df.schema)

    tables, ddls, placeholders = {}, {}, set()

    def read_csv(ddl, paths):
        """read seed CSV with Python's csv module (NOT spark.read.csv): an empty field stays an EMPTY STRING and only
        the null token becomes NULL - Spark's own CSV reader turns unquoted empty fields into NULL, which would change the test."""
        target = T._parse_datatype_string(ddl)
        as_str = T.StructType([T.StructField(f.name, T.StringType(), True) for f in target.fields])
        out = None
        for p in paths:
            full = p if os.path.isabs(p) else os.path.join(base, p)
            if not os.path.exists(full):
                die("seed file not found: %s" % full)
            with open(full, encoding="utf-8", newline="") as fh:
                rd = csv.reader(fh); header = next(rd)
                if [h.strip().lower() for h in header] != [f.name.lower() for f in target.fields]:
                    die("seed %s header %s does not match ddl columns %s" % (full, header, [f.name for f in target.fields]))
                rows = []
                for r in rd:
                    if len(r) != len(header):
                        die("seed %s: row has %d fields, expected %d: %s" % (full, len(r), len(header), r))
                    rows.append(tuple(None if v == null_token else v for v in r))
            df = spark.createDataFrame(rows, as_str)
            df = df.select([F.col(f.name).cast(f.dataType).alias(f.name) for f in target.fields])
            out = df if out is None else out.unionByName(df)
        return out

    def reg(name, df):
        df = materialize(df)
        tables[name] = df
        df.createOrReplaceTempView(name)

    for name, spec in cfg["tables"].items():
        ddls[name] = spec["ddl"]
        if spec.get("seed"):
            seeds = spec["seed"] if isinstance(spec["seed"], list) else [spec["seed"]]
            reg(name, read_csv(spec["ddl"], seeds))
        else:
            reg(name, spark.createDataFrame([], spec["ddl"]))
            placeholders.add(name)

    tasks = load_tasks(a.workflow)
    tasks.sort(key=lambda t: (t.get("level", 0), t["taskName"]))
    skip = tuple(cfg.get("skip_tasks", []))

    out = os.path.abspath(a.out)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    log = {"spark_version": spark.version, "config": cfg.get("spark", {}), "started": datetime.datetime.now().isoformat(timespec="seconds"), "rounds": []}

    def counts():
        return {n: tables[n].count() for n in sorted(tables)}

    def dump(df, path):
        pdf = df.toPandas()
        pdf.to_csv(path, index=False, encoding="utf-8")

    for ri, rnd in enumerate(cfg["rounds"], 1):
        rname = rnd.get("name", "round%d" % ri)
        rdir = os.path.join(out, "%02d_%s" % (ri, rname)); os.makedirs(rdir)
        for tname, files in rnd.get("append", {}).items():
            if tname not in tables:
                die("round %s appends to unknown table %s" % (rname, tname))
            new = read_csv(ddls[tname], files)
            reg(tname, tables[tname].unionByName(new))
        rlog = {"name": rname, "tasks": [], "start_counts": counts()}
        dump_tables = {n: tables[n] for n in tables}
        os.makedirs(os.path.join(rdir, "00_before"))
        for n, df in dump_tables.items():
            dump(df, os.path.join(rdir, "00_before", n + ".csv"))
        step = 0
        for t in tasks:
            tn = t["taskName"]; body = t.get("body", {}); agg = body.get("aggregationConfig")
            if tn.startswith(skip) or not agg or not agg.get("sql"):
                rlog["tasks"].append({"task": tn, "simulated": False, "reason": "skipped by config or not an SQL task (%s)" % t.get("serviceTemplate")})
                continue
            step += 1
            so = agg.get("sinkOption") or {}
            target, mode, parts = agg["tableName"], so.get("mode"), [p for p in (so.get("partitions") or [])]
            before = counts()
            try:
                df = materialize(spark.sql(agg["sql"]))
            except Exception as e:
                die("task %s failed in Spark: %s" % (tn, str(e)[:800]))
            old = tables.get(target)
            if old is None:
                die("task %s writes %s which is not declared in config.tables" % (tn, target))
            if target in placeholders or (mode == "Overwrite" and not parts):
                new = df; placeholders.discard(target)
            elif mode == "Overwrite":
                keys = df.select(*parts).distinct()
                keep = old.join(keys, on=parts, how="left_anti")
                new = keep.unionByName(df, allowMissingColumns=True)
            elif mode == "Append":
                new = old.unionByName(df, allowMissingColumns=True)
            else:
                die("task %s: unsupported sink mode %r" % (tn, mode))
            reg(target, new)
            after = counts()
            tdir = os.path.join(rdir, "%02d_%s" % (step, tn[:6])); os.makedirs(tdir)
            dump(tables[target], os.path.join(tdir, target + ".csv"))
            rlog["tasks"].append({"task": tn, "simulated": True, "target": target, "mode": mode, "partitions": parts,
                                  "rows_written_by_sql": df.count(), "rows_before": before.get(target), "rows_after": after[target],
                                  "all_counts_after": after})
        rlog["end_counts"] = counts()
        for n, df in tables.items():
            dump(df, os.path.join(rdir, "99_final_" + n + ".csv"))
        log["rounds"].append(rlog)

    json.dump(log, open(os.path.join(out, "run-log.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False, default=str)
    # human summary
    lines = ["# Reference run (original Spark SQL)", "", "Spark %s | config %s" % (spark.version, json.dumps(cfg.get("spark", {}))), ""]
    for r in log["rounds"]:
        lines += ["## %s" % r["name"], "", "| step | task | target | mode | rows before | rows after |", "|---|---|---|---|---|---|"]
        i = 0
        for t in r["tasks"]:
            if t["simulated"]:
                i += 1
                lines.append("| %d | %s | %s | %s %s | %s | %s |" % (i, t["task"], t["target"], t["mode"], t["partitions"] or "", t["rows_before"], t["rows_after"]))
            else:
                lines.append("| - | %s | NOT SIMULATED | - | - | - |" % t["task"])
        lines += ["", "End-of-round counts: " + ", ".join("%s=%s" % kv for kv in r["end_counts"].items()), ""]
    open(os.path.join(out, "SUMMARY.md"), "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))
    print("\nWrote:", out)


if __name__ == "__main__":
    main()
