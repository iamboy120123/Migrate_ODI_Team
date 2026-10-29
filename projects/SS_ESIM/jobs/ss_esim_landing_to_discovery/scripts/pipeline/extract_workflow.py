"""
extract_workflow.py
--------------------
Runbook Phase 1-3 (Step 2: Extraction)

หน้าที่:
    อ่าน input/export_workflow.json (Blendata export) + config/config.json
    แล้วแตกออกเป็นไฟล์ .sql แยกต่อ task ลงใน output/sql/raw/
    พร้อมสร้าง manifest (_manifest.json) เก็บ metadata ของแต่ละ task

ข้อสมมติเรื่อง schema ของ export_workflow.json:
    Blendata/Airflow export ที่พบทั่วไปมักมีโครงสร้างแบบใดแบบหนึ่งต่อไปนี้:

    รูปแบบ A (task list ธรรมดา):
    {
      "workflow_name": "ss_esim_landing_to_discovery",
      "tasks": [
        {
          "task_id": "T001",
          "task_name": "load_customer_dim",
          "target_table": "customer_dim",
          "merge_keys": ["customer_id"],
          "sql": "SELECT * , upper(name) FROM raw.customer WHERE deleted_flag = ''"
        }
      ]
    }

    รูปแบบ B (Airflow DAG export style):
    {
      "dag_id": "ss_esim_landing_to_discovery",
      "nodes": {
        "task_001": {
          "task_type": "SparkSQLOperator",
          "target_table": "customer_dim",
          "sql_query": "SELECT ..."
        }
      }
    }

    สคริปต์นี้รองรับทั้งสองรูปแบบเบื้องต้น ถ้า export จริงของโปรเจกต์มีโครงสร้าง
    ต่างจากนี้ ให้ปรับฟังก์ชัน `parse_tasks()` ให้ตรงกับ schema จริงก่อนใช้งาน
    -- ห้ามเดาโครงสร้างเองแล้วรันทับข้อมูลจริงโดยไม่ตรวจสอบก่อน

Usage:
    python scripts/pipeline/extract_workflow.py [--config config/config.json]
"""

import argparse
import json
import re
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"[ERROR] ไม่พบไฟล์: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def safe_filename(task_id: str, task_name: str) -> str:
    base = f"{task_id}_{task_name}" if task_name else task_id
    base = re.sub(r"[^A-Za-z0-9_\-]", "_", base)
    return f"{base}.sql"


def parse_tasks(raw: dict) -> list[dict]:
    """
    คืนค่าเป็น list ของ dict มาตรฐาน:
        { task_id, task_name, target_table, merge_keys, sql, source_shape }
    """
    tasks = []

    # รูปแบบ A: {"tasks": [...]}
    if isinstance(raw.get("tasks"), list):
        for i, t in enumerate(raw["tasks"]):
            task_id = t.get("task_id") or f"T{i+1:03d}"
            tasks.append({
                "task_id": task_id,
                "task_name": t.get("task_name", task_id),
                "target_table": t.get("target_table", ""),
                "merge_keys": t.get("merge_keys", []),
                "sql": t.get("sql", "").strip(),
                "source_shape": "A:tasks[]",
            })
        return tasks

    # รูปแบบ B: {"nodes": {...}} (Airflow DAG export style)
    if isinstance(raw.get("nodes"), dict):
        for i, (node_id, node) in enumerate(raw["nodes"].items()):
            sql = node.get("sql_query") or node.get("sql", "")
            if not sql:
                continue  # ข้าม node ที่ไม่มี SQL (เช่น sensor/branch task)
            tasks.append({
                "task_id": node_id,
                "task_name": node.get("task_name", node_id),
                "target_table": node.get("target_table", ""),
                "merge_keys": node.get("merge_keys", []),
                "sql": sql.strip(),
                "source_shape": "B:nodes{}",
            })
        return tasks

    # รูปแบบ C: Blendata export จริง
    #   {"airflowExportModels":[{"workflowName":..., "versions":[{"taskDetailString":"<json string>", "latest":true}]}]}
    # โดย taskDetailString เป็น JSON string ของ list[task]; SQL อยู่ที่
    #   body.aggregationConfig.sql        (service-job-aggregate)
    #   body.sql                          (service-job-export)
    # task ที่ไม่มี SQL (retention / recover) จะถูกคืนค่าพร้อม kind="non_sql"
    # เพื่อให้บันทึกลง manifest + flag ให้ SA ตัดสินใจ (ไม่สร้างไฟล์ .sql)
    if isinstance(raw.get("airflowExportModels"), list) and raw["airflowExportModels"]:
        for model in raw["airflowExportModels"]:
            versions = model.get("versions") or []
            if not versions:
                continue
            version = next((v for v in versions if v.get("latest")), versions[0])
            detail = version.get("taskDetailString") or "[]"
            try:
                raw_tasks = json.loads(detail) if isinstance(detail, str) else detail
            except json.JSONDecodeError as e:
                sys.exit(f"[ERROR] taskDetailString ไม่ใช่ JSON ที่ parse ได้: {e}")

            for i, t in enumerate(raw_tasks):
                body = t.get("body") or {}
                agg = body.get("aggregationConfig") or {}
                sink = agg.get("sinkOption") or {}
                template = t.get("serviceTemplate", "")

                if agg.get("sql"):
                    kind, sql = "aggregate", agg["sql"]
                    target_table = agg.get("tableName", "")
                    merge_keys = sink.get("keyColumns") or []
                    sink_mode = sink.get("mode", "")
                elif body.get("sql"):
                    kind, sql = "export_jdbc", body["sql"]
                    target_table = ""
                    merge_keys = []
                    sink_mode = body.get("sinkMode", "")
                else:
                    kind, sql = "non_sql", ""
                    target_table = body.get("tableName", "")
                    merge_keys = []
                    sink_mode = ""

                tasks.append({
                    "task_id": t.get("taskId") or f"T{i+1:03d}",
                    "task_name": t.get("taskName", ""),
                    "target_table": target_table,
                    "merge_keys": merge_keys,
                    "sql": (sql or "").strip(),
                    "source_shape": "C:airflowExportModels/taskDetailString",
                    "kind": kind,
                    "service_template": template,
                    "sink_mode": sink_mode,
                    "parent_task": t.get("parentTask") or [],
                    "workflow_name": model.get("workflowName", ""),
                    "schedule_time": version.get("scheduleTime", ""),
                    "db_platform": body.get("dbPlatform", ""),
                })
        return tasks

    sys.exit(
        "[ERROR] ไม่รู้จักโครงสร้างของ export_workflow.json นี้ "
        "กรุณาปรับฟังก์ชัน parse_tasks() ใน extract_workflow.py "
        "ให้ตรงกับ schema จริงของ Blendata export ก่อนรันใหม่"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.json")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_json(config_path)

    export_path = Path(config["paths"]["input_export_workflow"])
    raw_out_dir = Path(config["paths"]["output_raw_sql"])
    manifest_path = Path(config["paths"]["raw_manifest"])
    raw_out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] อ่าน export: {export_path}")
    raw = load_json(export_path)

    tasks = parse_tasks(raw)
    if not tasks:
        sys.exit("[ERROR] parse_tasks() คืนค่าว่างเปล่า - ไม่มี task ให้ extract")

    manifest = []
    non_sql_count = 0
    passthrough = (
        "kind", "service_template", "sink_mode", "parent_task",
        "workflow_name", "schedule_time", "db_platform",
    )
    for t in tasks:
        entry = {
            "task_id": t["task_id"],
            "task_name": t["task_name"],
            "target_table": t["target_table"],
            "merge_keys": t["merge_keys"],
            "raw_sql_file": None,
            "source_shape": t["source_shape"],
        }
        for k in passthrough:
            if k in t:
                entry[k] = t[k]

        if not t["sql"]:
            # ไม่มี SQL (เช่น table-retention / recover) - บันทึกไว้ให้ SA ตัดสินใจ
            entry["kind"] = t.get("kind", "non_sql")
            entry["review"] = "SA_DECIDE: task นี้ไม่มี SQL ต้องออกแบบวิธีทำเทียบเท่าใน ODI เอง"
            manifest.append(entry)
            non_sql_count += 1
            print(f"[NON-SQL] {t['task_name'] or t['task_id']} ({t.get('service_template','')}) - บันทึกลง manifest ให้ SA ตัดสิน")
            continue

        filename = safe_filename(t["task_id"], t["task_name"])
        out_path = raw_out_dir / filename
        out_path.write_text(t["sql"], encoding="utf-8")
        entry["raw_sql_file"] = str(out_path.as_posix())
        if entry.get("kind") == "export_jdbc":
            entry["review"] = (
                "SA_DECIDE: export ออกนอก Oracle (dbPlatform="
                f"{t.get('db_platform','')}) ต้องทำเป็น ODI mapping/interface ไม่ใช่ procedure ธรรมดา"
            )
        manifest.append(entry)
        print(f"[OK] {t['task_id']} -> {out_path}")

    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    expected_count = len(tasks)
    sql_count = len(manifest) - non_sql_count
    print(f"\n[SUMMARY] พบ {expected_count} task ใน export | extract SQL ได้ {sql_count} | non-SQL {non_sql_count} (บันทึกใน manifest)")
    if len(manifest) != expected_count:
        print("[WARN] จำนวนไม่ตรงกับ export - SA ควรตรวจสอบว่ามี task ที่ถูกข้ามไปโดยตั้งใจหรือไม่")
    print(f"[SUMMARY] manifest: {manifest_path}")
    print("\nขั้นตอนถัดไป: python scripts/pipeline/convert_sql.py")


if __name__ == "__main__":
    main()
