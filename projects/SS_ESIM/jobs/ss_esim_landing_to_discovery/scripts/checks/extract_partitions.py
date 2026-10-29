#!/usr/bin/env python3
"""extract_partitions.py (v1.0.0) -- auto-build the --partitions CSV for check_sql.py (D-R7).

Reads a Blendata workflow export JSON (export_workflow*.json) and, for every
task whose sinkOption.mode == "Overwrite", mechanically derives whether
sinkOption.partitions was an empty array (safe to TRUNCATE the whole table)
or a non-empty array (TRUNCATE would destroy other partitions' data --
knowledge/reference/delivery-checklist.md case 26, checklist item 41, rule D-R7).

This does NOT replace the Q14 conversation -- it automates the one step that
IS purely mechanical (reading a field that is already sitting in the DAG
JSON the user gave at Q1). It deliberately does NOT guess the one case that
genuinely needs a human: a task with sinkOption.mode == "Overwrite" but no
partitions field at all. knowledge/reference/blendata-json-schema.md says explicitly not to assume that
means "whole table" -- so this script leaves those out of the CSV and lists
them separately under NEEDS_CONFIRMATION, exactly like the main file's Q14
item 7 already requires asking the user directly.

Field paths are exactly as documented in knowledge/reference/blendata-json-schema.md
(G1 for the double-JSON-parse quirk, G2 for the per-task fields). Nothing
here is guessed -- every field read is one knowledge/reference/blendata-json-schema.md already names.

Output: a CSV with header TABLE_NAME,PARTITIONS_EMPTY,TASK_NAME,SOURCE,PARTITION_COLUMNS,DECISION
(kit 2.8.0: PARTITION_COLUMNS = ชื่อคอลัมน์จาก sinkOption.partitions · DECISION = คำตอบ I14 ที่คนกรอก:
 delete_by_partition | truncate_all -- gen_dml.py อ่านไปสร้าง SQL; รันซ้ำไม่ทับ DECISION ที่กรอกแล้ว)
(เดิม: TABLE_NAME,PARTITIONS_EMPTY,TASK_NAME,SOURCE
(SOURCE is always "auto-from-dag" for rows this script writes -- a human who
adds a NEEDS_CONFIRMATION row manually after asking the user should write
"user-confirmed" there instead, so a reviewer can tell which rows were ever
touched by a person). check_sql.py's load_partitions() only looks at
TABLE_NAME and PARTITIONS_EMPTY; the extra columns are for human review and
are harmless to the loader (unknown columns are ignored).

Usage:
    python scripts/checks/extract_partitions.py <export_workflow.json> [-o partitions_check.csv]

Exit codes:
    0 = CSV written (may still have NEEDS_CONFIRMATION tasks printed to stderr)
    1 = could not parse the file at all (reported, nothing written)
    2 = parsed fine but found zero Overwrite tasks with a usable table name
        (CSV would be empty and meaningless -- refuses to write one)
"""

import argparse
import csv
import json
import os
import sys
import tempfile


def load_tasks(path):
    """Return the list of task dicts, per knowledge/reference/blendata-json-schema.md G1 (double JSON parse)."""
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        data = json.load(fh)
    models = data.get("airflowExportModels")
    if not isinstance(models, list) or not models:
        raise ValueError(
            "ไม่พบ key 'airflowExportModels' เป็น list ที่ไม่ว่าง -- "
            "นี่อาจไม่ใช่ export_workflow*.json ตัวที่ถูกต้อง (ดู knowledge/reference/blendata-json-schema.md G1)")
    wf = models[0]
    versions = wf.get("versions")
    if not isinstance(versions, list) or not versions:
        raise ValueError(
            "ไม่พบ key 'versions' เป็น list ที่ไม่ว่างใน airflowExportModels[0] "
            "(ดู knowledge/reference/blendata-json-schema.md G1)")
    raw = versions[0].get("taskDetailString")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(
            "ไม่พบ 'taskDetailString' เป็น string ที่ไม่ว่างใน versions[0] -- "
            "field นี้ต้องเป็น string ที่ซ้อน JSON อีกชั้น (ดู knowledge/reference/blendata-json-schema.md G1)")
    try:
        tasks = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            "parse 'taskDetailString' รอบที่สองไม่สำเร็จ (%s) -- "
            "เนื้อหาข้างในอาจไม่ใช่ JSON ที่ถูกต้อง" % e)
    if not isinstance(tasks, list):
        raise ValueError(
            "'taskDetailString' หลัง parse รอบสองไม่ใช่ list ของทาสก์ (ดู knowledge/reference/blendata-json-schema.md G1)")
    return tasks


def sink_option(task):
    """cfg, sink dict (or None) -- per knowledge/reference/blendata-json-schema.md overwrite_scope()."""
    body = task.get("body") or {}
    cfg = body.get("aggregationConfig") or {}
    sink = cfg.get("sinkOption")
    if not isinstance(sink, dict):
        sink = body.get("sinkOption")
    return cfg, sink if isinstance(sink, dict) else None


def target_table(task, cfg):
    """per knowledge/reference/blendata-json-schema.md: body.aggregationConfig.tableName, falling back to body.tableName."""
    body = task.get("body") or {}
    name = cfg.get("tableName") or body.get("tableName")
    return name.strip() if isinstance(name, str) and name.strip() else None


def analyze(tasks):
    """Returns (confirmed_rows, needs_confirmation, overwrite_task_count).

    confirmed_rows: list of dict(table, partitions_empty, task_name)
      -- one table may appear more than once if written by several tasks;
      conflicts (same table, different Y/N) are resolved in main() by moving
      the whole table to needs_confirmation, never by silently picking one.
    needs_confirmation: list of dict(task_name, table, reason)
    """
    confirmed = []
    needs_confirmation = []
    overwrite_count = 0

    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_name = task.get("taskName") or "<ไม่มีชื่อทาสก์>"
        cfg, sink = sink_option(task)
        if sink is None:
            continue  # ไม่มี sinkOption เลย -- ไม่เกี่ยวกับ D-R7
        mode = sink.get("mode")
        if not isinstance(mode, str) or mode.strip().lower() != "overwrite":
            continue  # D-R7 เกี่ยวกับ Overwrite เท่านั้น (ดู knowledge/reference/blendata-json-schema.md)
        overwrite_count += 1

        table = target_table(task, cfg)
        if not table:
            needs_confirmation.append({
                "task_name": task_name,
                "table": "<ไม่ทราบ>",
                "reason": "ไม่พบชื่อตารางปลายทาง (tableName) ของทาสก์นี้",
            })
            continue

        if "partitions" not in sink:
            needs_confirmation.append({
                "task_name": task_name,
                "table": table,
                "reason": ("ไม่มี field 'partitions' เลยใน sinkOption -- knowledge/reference/blendata-json-schema.md "
                           "ห้ามสรุปว่าแปลว่าทั้งตาราง ต้องถามผู้ใช้ตรงๆ ที่ Q14"),
            })
            continue

        partitions = sink.get("partitions")
        if not isinstance(partitions, list):
            needs_confirmation.append({
                "task_name": task_name,
                "table": table,
                "reason": ("field 'partitions' มีอยู่แต่ไม่ใช่ array ที่คาดไว้ (พบชนิด %s) "
                           "-- ต้องเปิดไฟล์ดูด้วยตา" % type(partitions).__name__),
            })
            continue

        confirmed.append({
            "table": table,
            "partitions_empty": len(partitions) == 0,
            "task_name": task_name,
        })

    return confirmed, needs_confirmation, overwrite_count


def resolve_conflicts(confirmed, needs_confirmation):
    """Group confirmed rows by bare table name; a table with both Y and N
    verdicts from different tasks is a real conflict -- move it out of the
    CSV entirely rather than guessing which task wins."""
    by_table = {}
    for row in confirmed:
        key = row["table"].split(".")[-1].lower()
        by_table.setdefault(key, []).append(row)

    final_rows = []
    for key, rows in by_table.items():
        verdicts = {r["partitions_empty"] for r in rows}
        if len(verdicts) > 1:
            tasks = ", ".join(r["task_name"] for r in rows)
            needs_confirmation.append({
                "task_name": tasks,
                "table": rows[0]["table"],
                "reason": ("ตารางเดียวกันถูกเขียนทับจากหลายทาสก์ด้วยผล partitions "
                           "ไม่ตรงกัน (ว่าง/ไม่ว่างคนละทาสก์) -- check_sql.py ตัดสินได้แค่ "
                           "หนึ่งค่าต่อหนึ่งตาราง ต้องให้คนไล่ดูทีละทาสก์ว่าใบไหนถูก"),
            })
        else:
            # หลายทาสก์เห็นตรงกันก็พอใช้ได้ -- เก็บแถวเดียวจากทาสก์แรก
            final_rows.append(rows[0])
    return final_rows


def partition_columns_by_table(tasks):
    """{ตาราง (lower, ไม่มี schema): [ชื่อคอลัมน์ partition]} -- อ่านจาก sinkOption.partitions ตรง ๆ
    element เป็น string = ชื่อคอลัมน์เลย · เป็น object = ใช้ name (ไม่มีใช้ ref) · รูปอื่น = ไม่เดา (ปล่อยว่าง)"""
    out = {}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        cfg, sink = sink_option(task)
        if not sink or not isinstance(sink.get("mode"), str) or sink["mode"].strip().lower() != "overwrite":
            continue
        table = target_table(task, cfg)
        parts = sink.get("partitions")
        if not table or not isinstance(parts, list):
            continue
        names = []
        for p in parts:
            if isinstance(p, str) and p.strip():
                names.append(p.strip())
            elif isinstance(p, dict) and (p.get("name") or p.get("ref")):
                names.append(str(p.get("name") or p.get("ref")).strip())
            else:
                names = []
                break
        out.setdefault(table.split(".")[-1].lower(), names)
    return out


def read_existing_decisions(path):
    """DECISION ที่คนกรอกไว้แล้ว (รันซ้ำต้องไม่ทับคำตอบของคน)"""
    keep = {}
    if not path or not os.path.exists(path):
        return keep
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            row = {(k or "").strip().upper(): (v or "").strip() for k, v in row.items()}
            if row.get("DECISION"):
                keep[row.get("TABLE_NAME", "").split(".")[-1].lower()] = row["DECISION"]
    return keep


def write_csv(path, rows, columns=None, decisions=None):
    columns = columns or {}
    decisions = decisions or {}
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["TABLE_NAME", "PARTITIONS_EMPTY", "TASK_NAME", "SOURCE", "PARTITION_COLUMNS", "DECISION"])
        for row in sorted(rows, key=lambda r: r["table"].lower()):
            key = row["table"].split(".")[-1].lower()
            decision = decisions.get(key, "")
            w.writerow([
                row["table"],
                "Y" if row["partitions_empty"] else "N",
                row["task_name"],
                "user-confirmed" if decision else "auto-from-dag",
                ";".join(columns.get(key, [])),
                decision,
            ])


def _mk_task(task_name, table=None, mode=None, partitions="__absent__",
             table_field="aggregationConfig", sink_field="aggregationConfig"):
    """Build a synthetic task dict for selftest, following knowledge/reference/blendata-json-schema.md G2 shape.

    table_field / sink_field: "aggregationConfig" puts tableName/sinkOption
    under body.aggregationConfig (the common case); "body" puts them directly
    under body (the fallback path knowledge/reference/blendata-json-schema.md also documents).
    """
    body = {}
    cfg_target = {}
    if table_field == "aggregationConfig":
        body["aggregationConfig"] = cfg_target
    else:
        cfg_target = body

    if table is not None:
        cfg_target["tableName"] = table

    sink = {}
    if mode is not None:
        sink["mode"] = mode
    if partitions != "__absent__":
        sink["partitions"] = partitions
    if mode is not None:
        if sink_field == "aggregationConfig":
            body.setdefault("aggregationConfig", cfg_target)
            body["aggregationConfig"]["sinkOption"] = sink
        else:
            body["sinkOption"] = sink

    return {"taskName": task_name, "body": body}


def run_selftest():
    n = [0]

    def check(cond, msg):
        n[0] += 1
        assert cond, "selftest #%d failed: %s" % (n[0], msg)

    # 1) Overwrite + empty partitions -> confirmed Y
    tasks = [_mk_task("t1", "table_a", "Overwrite", [])]
    confirmed, needs, cnt = analyze(tasks)
    check(cnt == 1, "overwrite count ของ 1 ทาสก์ overwrite")
    check(confirmed == [{"table": "table_a", "partitions_empty": True, "task_name": "t1"}],
          "partitions=[] ต้องได้ Y: %r" % confirmed)
    check(needs == [], "ไม่ควรมี needs_confirmation: %r" % needs)

    # 2) Overwrite + non-empty partitions -> confirmed N
    tasks = [_mk_task("t2", "table_b", "Overwrite", ["region"])]
    confirmed, needs, cnt = analyze(tasks)
    check(confirmed == [{"table": "table_b", "partitions_empty": False, "task_name": "t2"}],
          "partitions=['region'] ต้องได้ N: %r" % confirmed)

    # 3) Append mode -> skipped entirely (ไม่เกี่ยวกับ D-R7)
    tasks = [_mk_task("t3", "table_c", "Append", [])]
    confirmed, needs, cnt = analyze(tasks)
    check(cnt == 0 and confirmed == [] and needs == [],
          "mode=Append ต้องถูกข้าม ไม่ใช่ confirmed หรือ needs_confirmation: %r/%r" % (confirmed, needs))

    # 4) Overwrite ไม่มี field partitions เลย -> needs_confirmation, ไม่ใช่ confirmed
    tasks = [_mk_task("t4", "table_d", "Overwrite", partitions="__absent__")]
    confirmed, needs, cnt = analyze(tasks)
    check(confirmed == [], "ไม่มี field partitions ต้องไม่โผล่ใน confirmed: %r" % confirmed)
    check(len(needs) == 1 and needs[0]["table"] == "table_d",
          "ไม่มี field partitions ต้องโผล่ใน needs_confirmation: %r" % needs)

    # 5) partitions มีอยู่แต่ไม่ใช่ list -> needs_confirmation
    tasks = [_mk_task("t5", "table_e", "Overwrite", partitions="not-a-list")]
    confirmed, needs, cnt = analyze(tasks)
    check(confirmed == [] and len(needs) == 1,
          "partitions ที่ไม่ใช่ list ต้องตก needs_confirmation: %r/%r" % (confirmed, needs))

    # 6) ไม่มีชื่อตาราง -> needs_confirmation
    tasks = [_mk_task("t6", table=None, mode="Overwrite", partitions=[])]
    confirmed, needs, cnt = analyze(tasks)
    check(confirmed == [] and len(needs) == 1 and needs[0]["table"] == "<ไม่ทราบ>",
          "ไม่มี tableName ต้องตก needs_confirmation: %r/%r" % (confirmed, needs))

    # 7) case-insensitive mode match
    tasks = [_mk_task("t7", "table_f", "OVERWRITE", [])]
    confirmed, needs, cnt = analyze(tasks)
    check(cnt == 1 and confirmed and confirmed[0]["table"] == "table_f",
          "mode ตัวพิมพ์ใหญ่ต้องจับได้เหมือนกัน: %r" % confirmed)

    # 8) fallback path: tableName/sinkOption อยู่ตรงๆ ใน body (ไม่ผ่าน aggregationConfig)
    tasks = [_mk_task("t8", "table_g", "Overwrite", [], table_field="body", sink_field="body")]
    confirmed, needs, cnt = analyze(tasks)
    check(confirmed and confirmed[0]["table"] == "table_g",
          "fallback path body.tableName/body.sinkOption ต้องอ่านได้: %r" % confirmed)

    # 9) สองทาสก์เขียนตารางเดียวกัน เห็นตรงกัน -> ไม่ชน ได้แถวเดียว
    tasks = [_mk_task("t9a", "table_h", "Overwrite", []),
             _mk_task("t9b", "table_h", "Overwrite", [])]
    confirmed, needs, cnt = analyze(tasks)
    final_rows = resolve_conflicts(confirmed, needs)
    check(len(final_rows) == 1 and final_rows[0]["table"] == "table_h",
          "สองทาสก์เห็นตรงกันต้องเหลือแถวเดียว: %r" % final_rows)
    check(needs == [], "ไม่ควรมี conflict ตรงนี้: %r" % needs)

    # 10) สองทาสก์เขียนตารางเดียวกัน ผลขัดกัน -> ตก needs_confirmation ทั้งคู่ ไม่เดาให้
    tasks = [_mk_task("t10a", "table_i", "Overwrite", []),
             _mk_task("t10b", "table_i", "Overwrite", ["p"])]
    confirmed, needs, cnt = analyze(tasks)
    final_rows = resolve_conflicts(confirmed, needs)
    check(not any(r["table"] == "table_i" for r in final_rows),
          "ตารางที่ผลขัดกันต้องไม่ถูกเขียนลง CSV เลย: %r" % final_rows)
    check(any("ขัดกัน" in n["reason"] or "ไม่ตรงกัน" in n["reason"] for n in needs),
          "ต้องมี note อธิบายว่าขัดกัน: %r" % needs)

    # 11) end-to-end load_tasks(): double-JSON-parse ตาม knowledge/reference/blendata-json-schema.md G1
    good = {
        "airflowExportModels": [{
            "workflowName": "wf_test",
            "versions": [{
                "taskDetailString": json.dumps([_mk_task("t11", "table_j", "Overwrite", [])])
            }]
        }]
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                      encoding="utf-8") as fh:
        json.dump(good, fh)
        good_path = fh.name
    try:
        tasks = load_tasks(good_path)
        check(len(tasks) == 1 and tasks[0]["taskName"] == "t11",
              "load_tasks ต้อง parse taskDetailString รอบสองได้: %r" % tasks)
    finally:
        os.unlink(good_path)

    # 12) load_tasks(): ไฟล์ที่ไม่มี airflowExportModels -> ValueError ชัดเจน ไม่ใช่ crash เงียบๆ
    bad = {"somethingElse": 1}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                      encoding="utf-8") as fh:
        json.dump(bad, fh)
        bad_path = fh.name
    try:
        threw = False
        try:
            load_tasks(bad_path)
        except ValueError:
            threw = True
        check(threw, "ไฟล์ที่ไม่มี airflowExportModels ต้องได้ ValueError ไม่ใช่เงียบ")
    finally:
        os.unlink(bad_path)

    # 13) load_tasks(): taskDetailString parse รอบสองไม่ได้ (JSON เสีย) -> ValueError ชัดเจน
    bad2 = {
        "airflowExportModels": [{
            "versions": [{"taskDetailString": "{not valid json"}]
        }]
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                      encoding="utf-8") as fh:
        json.dump(bad2, fh)
        bad2_path = fh.name
    try:
        threw = False
        try:
            load_tasks(bad2_path)
        except ValueError:
            threw = True
        check(threw, "taskDetailString ที่ parse รอบสองไม่ได้ ต้องได้ ValueError ไม่ใช่เงียบ")
    finally:
        os.unlink(bad2_path)

    print("extract_partitions selftest: %d assertions passed" % n[0])


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("workflow_json", nargs="?",
                     help="path ของ export_workflow*.json (DAG)")
    ap.add_argument("-o", "--output", default="partitions_check.csv",
                     help="ไฟล์ CSV ที่จะเขียน (default: partitions_check.csv)")
    ap.add_argument("--selftest", action="store_true",
                     help="รันชุดทดสอบในตัวแล้วจบ ไม่ต้องมีไฟล์ DAG จริง")
    args = ap.parse_args(argv)

    if args.selftest:
        run_selftest()
        return 0

    if not args.workflow_json:
        ap.error("ต้องระบุ path ของ export_workflow*.json (หรือใช้ --selftest)")

    try:
        tasks = load_tasks(args.workflow_json)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print("[ERROR] อ่านไฟล์ไม่สำเร็จ: %s" % e, file=sys.stderr)
        return 1

    confirmed, needs_confirmation, overwrite_count = analyze(tasks)
    confirmed = resolve_conflicts(confirmed, needs_confirmation)

    print("สแกนทาสก์ทั้งหมด %d ตัว พบ sinkOption.mode = Overwrite %d ตัว"
          % (len(tasks), overwrite_count))

    if not confirmed and not needs_confirmation:
        print("[ERROR] ไม่พบทาสก์ Overwrite ที่ใช้ได้เลย -- "
              "ไม่เขียนไฟล์ CSV เปล่าๆ ที่ไม่มีความหมาย", file=sys.stderr)
        return 2

    if confirmed:
        write_csv(args.output, confirmed, partition_columns_by_table(tasks), read_existing_decisions(args.output))
        y = sum(1 for r in confirmed if r["partitions_empty"])
        n = len(confirmed) - y
        print("เขียน %s แล้ว -- %d ตาราง (ว่าง/ปลอดภัย %d ใบ, ไม่ว่าง/ต้องระวัง %d ใบ)"
              % (args.output, len(confirmed), y, n))
    else:
        print("[WARN] ไม่มีตารางไหนสรุปได้อัตโนมัติเลย -- ไม่เขียน %s "
              "(ทุกใบต้องถามผู้ใช้ก่อน ดูรายการด้านล่าง)" % args.output, file=sys.stderr)

    if needs_confirmation:
        print("\n⚠️  %d ทาสก์ต้องถามผู้ใช้ตรงๆ ที่ Q14 ก่อน (ไม่ได้ใส่ใน %s "
              "เพราะเดาไม่ได้จริง):" % (len(needs_confirmation), args.output),
              file=sys.stderr)
        for item in needs_confirmation:
            print("  - ทาสก์ %r / ตาราง %r: %s"
                  % (item["task_name"], item["table"], item["reason"]),
                  file=sys.stderr)
        print("\nหลังถามแล้ว ให้เติมแถวของตารางเหล่านี้ลงใน %s เองด้วยมือ "
              "(คอลัมน์ SOURCE ใส่ \"user-confirmed\" แทน \"auto-from-dag\" "
              "เพื่อให้รู้ว่าผ่านคนแล้ว)" % args.output, file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
