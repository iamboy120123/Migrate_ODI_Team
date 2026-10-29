#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_odi_export.py  (kit 2.8.0)
--------------------------------
สร้าง ODI Smart Export ด้วย builder ของ md15 (scripts/odi_builder/) แทน generate_odi_export.py เดิม

เหตุผล: ตัวเดิมใช้ template + ค่าฝังตาย (ไม่มี topology, SnpOrigTxt 102/103 ฝังตาย, SqlIndGrp "2" ทุกบรรทัด)
        ทำให้ import ไม่ได้ (ODI-10113 / SnpsInexistantObjectException / NPE) หรือค่าใน step เพี้ยน
        builder ของ md15 อ่านทุกค่าจาก Smart Export ของ repository ปลายทาง (input/odi_reference/)
        และปฏิเสธการเขียนไฟล์เมื่อ error เชิงโครงสร้าง

ไฟล์นี้ทำแค่ "แปลง" : output/dml/_manifest.json + DML -> build-spec.json (รูปแบบ md15) -> เรียก build_from_spec.py
ไม่มีการสร้าง XML เอง และไม่มีค่า ODI ฝังตาย

ผลลัพธ์ (อยู่ข้าง paths.output_odi_export):
    PROJ_EXPORT.xml         XML ที่ประกอบแล้ว (ไฟล์กลางของ builder)
    <package_name>.zip      ไฟล์ที่ใช้ Smart Import ใน ODI Studio
    build-spec.json         บันทึกการตัดสินใจ (สร้างซ้ำได้ด้วย build_from_spec.py)
    converted-sql/*.sql     SQL ต่อ 1 command line (ตัด ';' ท้าย / ตัด comment นอก ISO-8859-1 แล้ว)

Usage:
    python scripts/pipeline/build_odi_export.py [--config config/config.json] [--dry-run] [--force]

หมายเหตุ GlobalId (import ทับ / สร้างใหม่):
    - ชื่อตรงกับ build ก่อนหน้า (project code + project name + folder + package) -> reuse GlobalId เดิมทุก object ที่ชื่อเดิม
      => Smart Import เลือก Overwrite/Merge แล้วเป็นการ UPDATE (ไม่สร้าง project ซ้ำ)
    - ชื่อไม่ตรง -> GlobalId ใหม่ทั้งหมด = project ใหม่ · --new-guid บังคับสร้างใหม่
    - procedure/step ที่เพิ่มใหม่ได้ GlobalId ใหม่เฉพาะตัว · ที่หายไปจาก build ไม่ถูกลบใน repository (ลบใน Studio เอง)
    _guid_keys.json = ตัวจำ GlobalId (ห้ามแก้เอง) · _guid_map.json = ไว้ตรวจหลัง import (S1/G4)
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

STEP_MARKER = "-- @@ODI_STEP: "
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))


def is_plsql_block(sql: str) -> bool:
    body = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--")).strip()
    return bool(re.match(r"(DECLARE|BEGIN)\b", body, flags=re.I))


def odi_step_sql(sql: str, where: str) -> str:
    """ODI ส่ง SQL เดี่ยวผ่าน JDBC: ';' ท้าย = ORA-00911. ไฟล์ export เป็น ISO-8859-1:
    บรรทัด comment ที่มีอักขระนอก latin-1 ถูกตัด (ต้นฉบับยังอยู่ในไฟล์ DML), นอก comment = หยุด"""
    kept = []
    for line in sql.splitlines():
        if any(ord(ch) > 255 for ch in line):
            if line.strip().startswith("--"):
                continue
            sys.exit(f"[ERROR] {where}: มีอักขระนอก ISO-8859-1 นอก comment (จะกลายเป็น '?'): {line.strip()[:80]}")
        kept.append(line)
    sql = "\n".join(kept).strip()
    if is_plsql_block(sql):
        return sql
    return re.sub(r";\s*$", "", sql.rstrip())


def parse_dml_steps(text: str) -> list:
    lines = text.splitlines(keepends=True)
    marks = [(i, l[len(STEP_MARKER):].strip()) for i, l in enumerate(lines) if l.startswith(STEP_MARKER)]
    if not marks:
        return [("STEP_1_MAIN", text.strip())]
    out = []
    for j, (idx, name) in enumerate(marks):
        stop = marks[j + 1][0] if j + 1 < len(marks) else len(lines)
        out.append((name, "".join(lines[idx + 1:stop]).strip()))
    return out


def credential_fields(xml_path):
    """คืนรายการช่อง credential ที่ไม่ใช่ null ใน SnpConnect / SnpConnectProp (ห้ามมีค่า)"""
    x = Path(xml_path).read_text(encoding="iso-8859-1")
    bad = []
    for m in re.finditer(r'<Object class="[^"]*\.(SnpConnect|SnpConnectProp)">(.*?)</Object>', x, re.S):
        for g in re.finditer(r'<Field name="(\w*(?:Pass|Pwd)\w*)" type="[^"]+">(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</Field>', m.group(2), re.S):
            v = (g.group(2) if g.group(2) is not None else g.group(3) or "").strip()
            if v and v != "null":
                bad.append(f"{m.group(1)}.{g.group(1)}")
    return bad


def guid_identities(xml_path):
    """{identity: GlobalId} ของทุก object ที่ builder สุ่ม GlobalId ใหม่ + meta (ชื่อที่ใช้ตัดสินว่าเป็น project เดิมหรือไม่)
    identity อิง "ชื่อ" ไม่ใช่เลข internal: project/folder/package/procedure/step/variable/state group"""
    x = Path(xml_path).read_text(encoding="iso-8859-1")
    objs = []
    for m in re.finditer(r'<Object class="[^"]*\.(\w+)">(.*?)</Object>', x, re.S):
        f = {}
        for g in re.finditer(r'<Field name="(\w+)" type="[^"]+">(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</Field>', m.group(2), re.S):
            f[g.group(1)] = g.group(2) if g.group(2) is not None else g.group(3)
        objs.append((m.group(1), f))
    txt = {f.get("ITxt"): f for c, f in objs if c == "SnpTxtHeader"}
    trt = {f.get("ITrt"): f.get("TrtName") for c, f in objs if c == "SnpTrt"}
    grp = {f.get("IGrpState"): f.get("GrpStateName") for c, f in objs if c == "SnpGrpState"}
    ids, meta = {}, {}

    def put(key, f):
        if f and f.get("GlobalId") not in (None, "", "null"):
            ids[key] = f["GlobalId"]

    for c, f in objs:
        if c == "SnpProject":
            put(f"project:{f['ProjectCode']}", f); meta.update(project_code=f["ProjectCode"], project_name=f["ProjectName"])
        elif c == "SnpFolder":
            put(f"folder:{f['FolderName']}", f); meta["folder"] = f["FolderName"]
        elif c == "SnpPackage":
            put(f"package:{f['PackName']}", f); meta["package"] = f["PackName"]
        elif c == "SnpTrt":
            put(f"trt:{f['TrtName']}", f); put(f"trttxt:{f['TrtName']}", txt.get(f.get("ITxtTrtTxt")))
        elif c == "SnpLineTrt":
            tn = trt.get(f.get("ITrt"), "?")
            put(f"line:{tn}:{f['OrdTrt']}", f); put(f"txt:{tn}:{f['OrdTrt']}", txt.get(f.get("DefITxt")))
        elif c == "SnpVar":
            put(f"var:{f['VarName']}", f); put(f"vartxt:{f['VarName']}", txt.get(f.get("ITxtVarIn")))
        elif c == "SnpStep":
            put(f"step:{f['StepName']}", f)
        elif c == "SnpGrpState":
            put(f"grpstate:{f['GrpStateName']}", f)
        elif c == "SnpState2":
            put(f"state2:{grp.get(f.get('IGrpState'), '?')}:{f['StateName']}", f)
    return ids, meta


def reuse_guids(out_xml, zip_path, xml_name, new_guid):
    """ชื่อตรงกับ build ก่อนหน้า (project code + project name + folder + package) -> ใช้ GlobalId เดิม
    => Smart Import เป็นการ UPDATE/Overwrite. ชื่อไม่ตรง (หรือ --new-guid) -> GlobalId ใหม่ = project ใหม่
    object ที่เพิ่งเพิ่ม (ชื่อใหม่) ได้ GlobalId ใหม่เฉพาะตัว; object ที่หายไปจาก build ไม่ถูกลบใน repository"""
    import zipfile
    keys_path = out_xml.parent / "_guid_keys.json"
    ids, meta = guid_identities(out_xml)
    old = {}
    if keys_path.exists() and not new_guid:
        try:
            old = json.loads(keys_path.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
    same = bool(old) and old.get("meta") == meta
    mapping = {}
    if same:
        for k, g in ids.items():
            og = old.get("ids", {}).get(k)
            if og and og != g:
                mapping[g] = og
    if mapping:
        x = out_xml.read_bytes().decode("iso-8859-1")   # ไบต์ต่อไบต์ (คง line ending เดิมของ builder)
        x = re.sub("|".join(re.escape(g) for g in mapping), lambda m: mapping[m.group(0)], x)
        out_xml.write_bytes(x.encode("iso-8859-1"))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(out_xml, xml_name)
        ids, meta = guid_identities(out_xml)
    if keys_path.exists():
        keys_path.replace(keys_path.with_suffix(".json.bak"))
    keys_path.write_text(json.dumps({"meta": meta, "ids": ids}, indent=2, ensure_ascii=False), encoding="utf-8")
    reused = sum(1 for k in ids if old.get("ids", {}).get(k) == ids[k])
    if same:
        print(f"[GUID] ชื่อตรงกับ build ก่อนหน้า ({meta.get('project_code')}) -> reuse GlobalId {reused}/{len(ids)} object "
              f"(import แบบ Overwrite ได้; ใหม่ {len(ids) - reused})")
    elif old and not new_guid:
        print(f"[GUID] ชื่อไม่ตรงกับ build ก่อนหน้า (เดิม {old.get('meta')} / ใหม่ {meta}) -> GlobalId ใหม่ทั้งหมด = project ใหม่")
    else:
        print(f"[GUID] GlobalId ใหม่ทั้งหมด ({len(ids)} object) — import ครั้งแรก")


def seq_key(e):
    tid = e["task_id"]
    name = tid.split("_", 2)[2] if tid.startswith("task_") and tid.count("_") >= 2 else tid
    head = name.split("_", 1)[0]
    return (0, int(head)) if head.isdigit() else (1, 0), name


def proc_name_of(entry):
    tid = entry["task_id"]
    if tid.startswith("task_") and "_" in tid[5:]:
        return tid.split("_", 2)[2]
    return entry.get("procedure_name", f"PRC_{tid}")


def safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)


def merged_ddl(ddl_dir: Path, out: Path):
    files = sorted(p for p in ddl_dir.glob("*") if p.suffix.lower() in (".csv", ".tsv")) if ddl_dir.is_dir() else []
    if not files:
        return None
    if len(files) == 1:
        return files[0]
    rows, header = [], None
    for f in files:
        with open(f, encoding="utf-8-sig", newline="") as fh:
            rd = csv.DictReader(fh, delimiter="\t" if f.suffix.lower() == ".tsv" else ",")
            header = header or rd.fieldnames
            rows += list(rd)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("--dry-run", action="store_true", help="ตรวจอย่างเดียว ไม่เขียน XML/zip")
    ap.add_argument("--force", action="store_true", help="ข้ามได้เฉพาะ bind-prefix check (ส่งต่อให้ builder)")
    ap.add_argument("--new-guid", action="store_true",
                    help="ไม่ reuse GlobalId เดิม (ใช้เมื่อจะสร้าง project ใหม่ตั้งใจให้ซ้อนกับของเดิม) — ปกติไม่ต้องใส่")
    args = ap.parse_args()

    # ด่านของครบ: import เข้า Studio ทำครั้งเดียวตอนจบ -> ของที่ต้องใช้ต้องครบก่อนเขียนไฟล์ (ไม่มี --force)
    # --dry-run ข้ามด่านนี้ (check_inputs.py เรียก builder แบบ --dry-run เอง จึงต้องไม่วนซ้ำ)
    if not args.dry_run:
        pass  # K5: ใช้ subprocess ระดับ module (import ซ้ำในฟังก์ชันทำให้ UnboundLocalError)
        chk = Path(__file__).resolve().parents[1] / "checks" / "check_inputs.py"
        if chk.exists():
            r = subprocess.run([sys.executable, str(chk), "--no-dry-run"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode != 0:
                print(r.stdout, file=sys.stderr)
                print("[ERROR] ของที่ AI ต้องใช้ยังไม่ครบ (check_inputs) - ไม่สร้าง package "
                      "(Smart Import ทำครั้งเดียวตอนจบ จึงต้องครบก่อน build) ครบแล้วรันใหม่", file=sys.stderr)
                sys.exit(1)

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    odi = config.get("odi", {})
    out_xml = Path(config["paths"]["output_odi_export"])
    out_dir = out_xml.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # ด่านสุดท้ายก่อนสร้าง package: SQL ที่ convert_sql ยัง flag ว่าเป็น Spark-ism (date_format, concat, split ...)
    # import ผ่านแต่รันแล้วพัง -> ปฏิเสธเขียนไฟล์จนกว่าทุกแถวใน REVIEW_FLAGS จะเป็น RESOLVED (ไม่มี --force)
    flags_md = Path(config.get("paths", {}).get("review_flags", "status/REVIEW_FLAGS.md"))
    if flags_md.exists():
        open_flags = []
        for line in flags_md.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 4 and cells[-1].upper() == "PENDING":
                open_flags.append((cells[0], cells[1]))
        if open_flags:
            by_reason = {}
            for _t, reason in open_flags:
                by_reason[reason] = by_reason.get(reason, 0) + 1
            print(f"[ERROR] ยังมี {len(open_flags)} จุดใน {flags_md} ที่เป็น PENDING - SQL ยังมี Spark-ism ที่ Oracle ไม่รู้จัก "
                  "(import ผ่านแต่รันแล้วพัง) จึงไม่สร้าง package:", file=sys.stderr)
            for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
                print(f"  {n:3d} x {reason}", file=sys.stderr)
            print("วิธีแก้: แก้ SQL ใน output/sql/converted/ ตามกฎ md15 (appendix D) แล้วเปลี่ยน status ของแถวนั้นเป็น RESOLVED "
                  "ใน " + str(flags_md) + " (หรือรัน agent_reviewer.py ถ้า ai_mode=auto) แล้วรัน gen_dml.py + build_odi_export.py ใหม่",
                  file=sys.stderr)
            sys.exit(1)

    import read_smart_export as rse
    ref_path = rse.find_reference(Path("."))
    if not ref_path:
        sys.exit("[ERROR] ไม่พบ Smart Export ใน input/odi_reference/ (.xml หรือ .zip) — "
                 "ต้องเป็น export จาก repository ปลายทางที่จะ import จริง. ห้ามใช้ไฟล์จาก repository อื่น")

    if ref_path.suffix.lower() == ".zip":
        # builder ของ md15 อ่านเฉพาะ .xml -> แตกสำเนาไว้ข้างผลลัพธ์ (ไฟล์ reference ต้นฉบับไม่ถูกแตะ)
        import zipfile
        with zipfile.ZipFile(ref_path) as z:
            xmls = [n for n in z.namelist() if n.lower().endswith(".xml")]
            if len(xmls) != 1:
                sys.exit(f"[ERROR] {ref_path.name} มี .xml {len(xmls)} ไฟล์ (ต้องมี 1) — ใช้ Smart Export ที่ export จาก Studio ตรง ๆ")
            ref_path = out_dir / "_reference.xml"
            ref_path.write_bytes(z.read(xmls[0]))

    man_path = Path(config["paths"]["dml_manifest"])
    if not man_path.exists():
        sys.exit(f"[ERROR] ไม่พบ {man_path} — รัน gen_dml.py ก่อน")
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    if not manifest:
        sys.exit("[ERROR] dml manifest ว่างเปล่า")
    manifest = sorted(manifest, key=seq_key)

    sql_out = out_dir / "converted-sql"
    sql_out.mkdir(parents=True, exist_ok=True)
    for old in sql_out.glob("*.sql"):
        try:
            old.unlink()   # ไฟล์ที่ generator นี้สร้างเอง (ไม่ใช่ไฟล์ของผู้ใช้)
        except PermissionError:
            # K5 (2026-10-15): โฟลเดอร์ที่ห้ามลบ (Cowork mount) -> ล้างเนื้อหาแทน; ไฟล์ที่ชื่อยังใช้อยู่จะถูกเขียนทับ
            old.write_text("", encoding="utf-8")

    # ---- variables (แทน task ที่ระบุใน replaces_tasks) ----
    variables, replaced = [], set()
    for v in odi.get("variables") or []:
        fn = f"VAR_{safe(v['name'])}.sql"
        (sql_out / fn).write_text(odi_step_sql(v["refresh_query"], f"variable {v['name']}") + "\n", encoding="utf-8")
        item = {"name": v["name"], "sql_file": fn}
        if v.get("sql_ind_grp") is not None:
            item["sql_ind_grp"] = v["sql_ind_grp"]
        variables.append(item)
        replaced.update(str(t) for t in v.get("replaces_tasks", []))

    # ---- procedures: 1 task = 1 procedure, 1 step ใน DML = 1 command line ----
    procedures, excluded = [], []
    for e in manifest:
        tid = e["task_id"]
        if any(f"_{t}_" in tid for t in replaced):
            excluded.append({"task": tid, "reason": "แทนด้วย ODI variable (odi.variables.replaces_tasks)"})
            continue
        dml = Path(e["dml_file"])
        if not dml.exists():
            excluded.append({"task": tid, "reason": "ไม่พบไฟล์ DML"})
            continue
        pname = proc_name_of(e)
        lines = []
        for n, (step_name, sql) in enumerate(parse_dml_steps(dml.read_text(encoding="utf-8")), 1):
            fn = f"{safe(pname)}__{n:02d}_{safe(step_name)}.sql"
            (sql_out / fn).write_text(odi_step_sql(sql, f"{pname}/{step_name}") + "\n", encoding="utf-8")
            lines.append({"sql_file": fn})
        procedures.append({"name": pname, "lines": lines})
    if not procedures:
        sys.exit("[ERROR] ไม่มี procedure ให้ประกอบ")
    for x in config.get("scope", {}).get("excluded_tasks", []):
        excluded.append({"task": x, "reason": config["scope"].get("excluded_reason", {}).get(x, "scope.excluded_tasks")})

    # ---- steps: variable ก่อน แล้ว procedure ตามลำดับ workflow (chain เดียว) ----
    steps = [{"name": v["name"], "type": "V", "ref": v["name"]} for v in variables] + \
            [{"name": p["name"], "type": "T", "ref": p["name"]} for p in procedures]

    prefix = (config.get("target_table_prefix") or "").rstrip(".")
    spec = {
        "_readme": "สร้างโดย build_odi_export.py จาก output/dml/_manifest.json — แก้ที่ต้นทางแล้วรันใหม่ ไม่แก้ไฟล์นี้ตรง ๆ",
        "reference_smartexport": os.path.relpath(ref_path.resolve(), out_dir.resolve()).replace("\\", "/"),
        "sql_dir": "converted-sql",
        "project": {"name": odi.get("project_name", "migration"),
                    "code": odi.get("project_code", "MIGRATION"),
                    "folder": odi.get("folder_name", odi.get("project_name", "migration")),
                    "package": odi.get("package_name", "PKG_MIGRATION")},
        "variables": variables, "procedures": procedures, "steps": steps,
        "excluded_tasks": excluded,
        "output": {"xml": out_xml.name, "zip": f"{odi.get('package_name', 'PKG_MIGRATION')}.zip"},
    }
    if prefix:
        spec["default_schema"] = prefix
    ddl = merged_ddl(Path("input/oracle_ddl"), out_dir / "_ddl_merged.csv")
    if ddl:
        spec["ddl_file"] = os.path.relpath(ddl.resolve(), out_dir.resolve()).replace("\\", "/")
    part = Path("config/partitions_check.csv")
    if part.exists():
        spec["partitions_file"] = os.path.relpath(part.resolve(), out_dir.resolve()).replace("\\", "/")
        with open(part, encoding="utf-8-sig", newline="") as fh:
            spec["overwrite_scope"] = [
                {"table": r["TABLE_NAME"],
                 "decision": ("truncate table" if r.get("PARTITIONS_EMPTY", "").upper() == "Y"
                              else "I14 DECISION = " + (r.get("DECISION", "").strip() or "(blank)")
                              + " (partitions NOT empty)"),
                 "note": r.get("TASK_NAME", "")} for r in csv.DictReader(fh)]
    spec_path = out_dir / "build-spec.json"
    spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[INFO] reference: {ref_path.name} · spec: {spec_path} · {len(variables)} variable / {len(procedures)} procedure")

    builder = ROOT / "scripts" / "odi_builder" / "build_from_spec.py"
    cmd = [sys.executable, str(builder), str(spec_path)]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.force:
        cmd.append("--force")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "scripts" / "checks") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(cmd, env=env)
    if r.returncode == 0 and not args.dry_run:
        # กฎห้ามฝัง credential: ช่องรหัสผ่านใน Topology ต้องเป็น null (reference อาจมีรหัสเข้ารหัสติดมา -> ห้ามส่งต่อ)
        leaked = credential_fields(out_xml)
        if leaked:
            for f in (out_xml, out_dir / spec["output"]["zip"]):
                if f.exists():
                    f.unlink()   # ไฟล์ที่ generator นี้เพิ่งสร้างเอง
            print("[ERROR] reference มีค่าในช่องรหัสผ่านของ Topology: " + ", ".join(leaked) +
                  "\n        ลบไฟล์ผลลัพธ์แล้ว — export Smart Export ใหม่โดยไม่ใส่ password ใน Data Server (หรือให้ SA เคลียร์ช่อง) แล้ววางที่ input/odi_reference/")
            return 2
        reuse_guids(out_xml, out_dir / spec["output"]["zip"], "SmartExport.xml", args.new_guid)
        # บันทึก GlobalId ของ build นี้ลง _guid_map.json (ใช้ตรวจหลัง import: verify_all V2 / read_run_results S1)
        gp = out_dir / "_guid_map.json"
        if gp.exists():
            gp.replace(gp.with_suffix(".json.bak"))
        sg = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "sync_guid_from_export.py"),
                             "--config", args.config, "--export", str(out_xml)], env=env, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
        print("[INFO] " + (sg.stdout.strip().splitlines() or ["sync_guid: no output"])[0] if sg.returncode == 0
              else "[WARN] เขียน _guid_map.json ไม่สำเร็จ: " + (sg.stdout + sg.stderr)[-200:])
        print(f"\n[OK] {out_xml}  (ไฟล์กลาง)\n[OK] {out_dir / spec['output']['zip']}  (ใช้ Smart Import)")
        print("[ACTION REQUIRED] Smart Import เข้า ODI Dev ครั้งเดียว แล้วเริ่มทดสอบ · Topology/Scenario ต้องตั้ง/generate ใน Studio เอง")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
