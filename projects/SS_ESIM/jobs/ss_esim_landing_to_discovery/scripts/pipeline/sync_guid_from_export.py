"""
sync_guid_from_export.py
-------------------------
ดึง GlobalId ของ object ที่อยู่ใน ODI repository จริง (จาก Smart Export ที่ export ออกจาก Studio)
มาเขียนทับ output/odi_export/_guid_map.json เพื่อให้ Smart Import ครั้งถัดไปเป็นการ **update**
object เดิมใน repository ไม่ใช่สร้างซ้ำ

ใช้เมื่อ:
    - มีคนแก้/copy project ใน ODI Studio (copy = GlobalId ใหม่ทั้งหมด)
    - repository ถูก import จาก XML คนละรุ่นกับ _guid_map.json

จับคู่ด้วยชื่อ (ไม่ใช่ internal ID เพราะแต่ละ repository ต่างกัน):
    project / folder / package        -> key "project" / "folder" / "package"
    SnpTrt.TrtName                    -> "trt:<task_id>"            (TrtName = task_id ตัด task_<hash>_)
    SnpLineTrt (TrtName, SqlName)     -> "line:<task_id>:<OrdTrt>"   + TxtHeader ของ DefITxt -> "txt:<task_id>:<step>"
    SnpStep StepType=T                -> "step:<task_id>"
    SnpStep StepType=V                -> "step:var:<VarName>"
    SnpVar                            -> "var:<VarName>" + TxtHeader ของ ITxtVarIn -> "vartxt:<VarName>"

Usage:
    python scripts/pipeline/sync_guid_from_export.py --export <smart_export.xml> [--update-config] [--dry-run]
"""
import argparse
import json
import re
import sys
from pathlib import Path


def objects(path: Path):
    x = path.read_text(encoding="iso-8859-1")
    for m in re.finditer(r'<Object class="[\w.]+\.(\w+)">(.*?)</Object>', x, re.S):
        f = {}
        for g in re.finditer(r'<Field name="(\w+)" type="[\w.\[\]]+">(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</Field>',
                             m.group(2), re.S):
            f[g.group(1)] = g.group(2) if g.group(2) is not None else g.group(3)
        yield m.group(1), f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("--export", required=True, help="Smart Export XML ที่ export จาก ODI Studio")
    ap.add_argument("--update-config", action="store_true", help="เขียน project_code/project_name ลง config")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    manifest = json.loads(Path(config["paths"]["dml_manifest"]).read_text(encoding="utf-8"))
    guid_path = Path(config["paths"]["output_odi_export"]).parent / "_guid_map.json"
    old = json.loads(guid_path.read_text(encoding="utf-8")) if guid_path.exists() else {}

    task_by_proc = {}
    for e in manifest:
        tid = e["task_id"]
        proc = tid.split("_", 2)[2] if tid.startswith("task_") and tid.count("_") >= 2 else tid
        task_by_proc[proc] = tid

    obs = list(objects(Path(args.export)))
    txt = {f.get("ITxt"): f for c, f in obs if c == "SnpTxtHeader"}
    trt = {f["ITrt"]: f["TrtName"] for c, f in obs if c == "SnpTrt"}
    var = {f["IVar"]: f["VarName"] for c, f in obs if c == "SnpVar"}

    new, unmatched = {}, []
    proj = None
    for c, f in obs:
        if c == "SnpProject":
            new["project"] = f["GlobalId"]; proj = f
        elif c == "SnpFolder":
            new["folder"] = f["GlobalId"]
        elif c == "SnpPackage":
            new["package"] = f["GlobalId"]
        elif c == "SnpTrt":
            tid = task_by_proc.get(f["TrtName"])
            if tid: new[f"trt:{tid}"] = f["GlobalId"]
            else: unmatched.append(f"SnpTrt {f['TrtName']}")
        elif c == "SnpLineTrt":
            tid = task_by_proc.get(trt.get(f["ITrt"], ""))
            if tid:
                new[f"line:{tid}:{f['OrdTrt']}"] = f["GlobalId"]
                t = txt.get(f.get("DefITxt"))
                if t: new[f"txt:{tid}:{f['OrdTrt']}"] = t["GlobalId"]
        elif c == "SnpStep":
            if f.get("StepType") == "T":
                tid = task_by_proc.get(f["StepName"])
                if tid: new[f"step:{tid}"] = f["GlobalId"]
                else: unmatched.append(f"SnpStep {f['StepName']}")
            elif f.get("StepType") == "V":
                new[f"step:var:{var.get(f.get('IVar'), f['StepName'])}"] = f["GlobalId"]
            else:
                unmatched.append(f"SnpStep {f['StepName']} (type {f.get('StepType')} - generator ยังไม่รองรับ)")
        elif c == "SnpVar":
            new[f"var:{f['VarName']}"] = f["GlobalId"]
            t = txt.get(f.get("ITxtVarIn"))
            if t: new[f"vartxt:{f['VarName']}"] = t["GlobalId"]

    changed = sum(1 for k, v in new.items() if old.get(k) != v)
    added = [k for k in new if k not in old]
    only_old = [k for k in old if k not in new]
    merged = {**old, **new}
    print(f"[SYNC] project = {proj.get('ProjectCode')} / {proj.get('ProjectName')}" if proj else "[SYNC] ไม่พบ SnpProject")
    print(f"[SYNC] {len(new)} key จาก export: เปลี่ยน {changed}, ใหม่ {len(added)}; "
          f"key ที่มีเฉพาะใน map เดิม (object ยังไม่อยู่ใน repository) {len(only_old)}")
    for k in only_old:
        print(f"    [KEEP-OLD] {k}")
    for u in unmatched:
        print(f"    [UNMATCHED] {u}")
    if args.dry_run:
        return
    if guid_path.exists():
        guid_path.with_suffix(".json.bak").write_text(json.dumps(old, indent=2), encoding="utf-8")
    guid_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print(f"[OK] {guid_path} (backup: {guid_path.with_suffix('.json.bak').name})")
    if args.update_config and proj:
        config["odi"]["project_code"] = proj["ProjectCode"]
        config["odi"]["project_name"] = proj["ProjectName"]
        Path(args.config).write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[OK] config.odi.project_code/project_name = {proj['ProjectCode']} / {proj['ProjectName']}")


if __name__ == "__main__":
    main()
