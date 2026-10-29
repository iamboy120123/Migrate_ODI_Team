# ============================================================================
# DEPRECATED (kit 2.8.0) -- ห้ามใช้สร้าง XML ที่จะ import จริง
# ตัวนี้ใช้ template + ค่าฝังตาย (ไม่มี topology / SnpOrigTxt 102,103 ฝังตาย / SqlIndGrp "2" ทุกบรรทัด /
# ITxtTrtTxt=null) ทำให้ import ไม่ได้ (ODI-10113, SnpsInexistantObjectException, NPE) หรือค่า step เพี้ยน
# ใช้ scripts/pipeline/build_odi_export.py (builder ของ md15: scripts/odi_builder/) แทน
# เก็บไว้เทียบผลและย้อนกลับเท่านั้น -- รันต้องใส่ --i-know-this-is-deprecated
# ============================================================================
"""
generate_odi_export.py
------------------------
Runbook Phase 5b (ODI Smart Export Generation)

สร้าง ODI Smart Export XML (<SunopsisExport>) จาก DML ใน output/dml/
ให้ import เข้า ODI 14.1.2 ผ่าน Smart Import ได้โดยตรง

โครงสร้างอ้างอิงจาก Smart Export จริงของทีม (SmartExport_7.xml, work repo 21)
โดยเก็บ field order / Java type / ค่า default เชิงโครงสร้างไว้ที่
references/odi-export-field-template.json

โครงสร้างที่ generate:
    <Admin IsSmartExportFile="true" .../>
    <Encryption containsCipherText="false" .../>
    <SmartExportList><Include>SnpProject#<id></Include></SmartExportList>
    SnpProject
    SnpFolder
    SnpOrigTxt  x2   (102 = SNP_LINE_TRT.DEF_I_TXT, 103 = SNP_LINE_TRT.COL_I_TXT)
    ต่อ 1 procedure:
        SnpTrt                      (TrtType=U)
        SnpTxtHeader + SnpLineTrt   ต่อ 1 step (OrdTrt = 10,20,...)
    SnpPackage
    SnpStep x N                     (ผูกกันด้วย OkNextStep, Nno = 0,1,2,...)
    SnpFKXRef                       (อ้าง SNP_ORIGTXT ที่ไม่ได้อยู่ในไฟล์)

การจัดการ ID:
    Smart Import ของ ODI จับคู่ object ด้วย GlobalId (UUID) ส่วน internal ID
    (ITrt / ILineTrt / ITxt / IStep / IPackage / IFolder / IProject) เป็นเลขภายใน
    ที่ต้องไม่ชนกันเองในไฟล์ - script นี้จึงสุ่ม UUID ใหม่ทุก object และไล่เลข
    internal ID ต่อจาก odi.id_base ใน config.json (ค่าเริ่มต้น 90000)

    ** รัน 2 ครั้งจะได้ GlobalId คนละชุด = ODI จะมองเป็น object คนละตัว **
    ถ้าต้อง re-generate หลัง import ไปแล้ว สคริปต์จะอ่าน GlobalId เดิมจาก
    output/odi_export/_guid_map.json ให้อัตโนมัติ (ใช้ --new-guid ถ้าต้องการสุ่มใหม่)

Usage:
    python scripts/pipeline/generate_odi_export.py [--config config/config.json] [--new-guid]
"""

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from datetime import datetime

STEP_MARKER = "-- @@ODI_STEP: "

# SnpOrigTxt ที่ SQL ของ step อ้างถึง (ค่าคงที่ของ ODI ไม่ใช่ของโปรเจกต์)
ORIGTXT_ROWS = [
    {"GlobalId": "null", "ITxtOrig": "102", "OrigineName": "Target Technology",
     "SnpsCol": "DEF_I_TXT", "SnpsTable": "SNP_LINE_TRT"},
    {"GlobalId": "null", "ITxtOrig": "103", "OrigineName": "Source Technology",
     "SnpsCol": "COL_I_TXT", "SnpsTable": "SNP_LINE_TRT"},
]
ITXT_ORIG_DEF = "102"
# refresh query ของ variable (SNP_VAR.I_TXT_VAR_IN) - ค่าจาก Smart Export จริง (Copy (2), 2026-09-24)
ORIGTXT_VAR_IN = {"GlobalId": "null", "ITxtOrig": "128", "OrigineName": "Variable Query",
                  "SnpsCol": "I_TXT_VAR_IN", "SnpsTable": "SNP_VAR"}


def is_plsql_block(sql: str) -> bool:
    """step ที่เป็น PL/SQL block (BEGIN/DECLARE) ต้องจบด้วย END; ไว้ - ส่วน SQL เดี่ยวห้ามมี ; ท้าย"""
    body = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--")).strip()
    return bool(re.match(r"(DECLARE|BEGIN)\b", body, flags=re.I))


def odi_step_sql(sql: str) -> str:
    """ODI ส่ง SQL เดี่ยวผ่าน JDBC -> ';' ท้าย statement = ORA-00911 invalid character
    (พบจาก Smart Export ที่แก้ใน Studio 2026-09-24: ทีมลบ ';' ท้าย INSERT/MERGE ทุก step)
    PL/SQL block คงไว้ตามเดิม (END; จำเป็น)"""
    # ไฟล์ export เป็น ISO-8859-1: comment ภาษาไทยจะกลายเป็น '????' ใน repository (เห็นใน Smart Export จริง 09-24)
    # -> ตัดบรรทัด comment ที่มีตัวอักษรนอก latin-1 ออกจาก step (ต้นฉบับยังอยู่ในไฟล์ DML)
    #    ตัวอักษรนอก latin-1 ที่ไม่ใช่ comment = ข้อมูลจะเพี้ยน -> หยุด
    kept = []
    for line in sql.splitlines():
        if any(ord(ch) > 255 for ch in line):
            if line.strip().startswith("--"):
                continue
            sys.exit(f"[ERROR] step SQL มีตัวอักษรนอก ISO-8859-1 นอก comment (จะกลายเป็น '?'): {line.strip()[:80]}")
        kept.append(line)
    sql = "\n".join(kept)
    if is_plsql_block(sql):
        return sql
    return re.sub(r";\s*$", "", sql.rstrip())

# field ที่ต้อง generate ใหม่เสมอ ห้าม inherit ค่าจากโปรเจกต์ต้นแบบ
RESET_FIELDS = {
    "GlobalId", "FirstDate", "LastDate", "FirstUser", "LastUser", "IntVersion",
    "ExtVersion", "VLastDate", "RepGuid", "RepVersion", "OrdFolder",
    "IScTrt", "IScOrigTrt", "IScBaseTrt", "ScOrigTrtTag",
    "IScPackage", "IScOrigPackage", "IScBasePackage", "ScOrigPackageTag",
    "IScMapping", "IScPop", "IScTable", "IState", "ITxtPack",
}


def esc(v: str) -> str:
    return v.replace("]]>", "]]]]><![CDATA[>")


class Emitter:
    def __init__(self, template_path: Path, now: str, user: str):
        tpl = json.loads(template_path.read_text(encoding="utf-8"))
        self.schema = tpl["schema"]
        self.now, self.user = now, user
        self.out = []

    def obj(self, cls: str, values: dict):
        """render 1 <Object> โดยใช้ field order/type จาก export จริง
        field ที่ไม่ได้ส่งมาใน values -> ใช้ค่าโครงสร้างจากต้นแบบ (ยกเว้น RESET_FIELDS)"""
        if cls not in self.schema:
            sys.exit(f"[ERROR] ไม่มี {cls} ใน field template - ตรวจ references/odi-export-field-template.json")
        spec = self.schema[cls]
        lines = [f'<Object class="{spec["class"]}">']
        for name, jtype, ref_default in spec["fields"]:
            if name in values:
                v = values[name]
            elif name in RESET_FIELDS:
                v = {"FirstDate": self.now, "LastDate": self.now,
                     "FirstUser": self.user, "LastUser": self.user,
                     "IntVersion": "1", "GlobalId": str(uuid.uuid4())}.get(name, "null")
            else:
                v = ref_default
            if v is None:
                v = "null"
            v = str(v)
            if v == "null":
                lines.append(f'\t<Field name="{name}" type="{jtype}">null</Field>')
            else:
                lines.append(f'\t<Field name="{name}" type="{jtype}"><![CDATA[{esc(v)}]]></Field>')
        lines.append("</Object>")
        self.out.append("\n".join(lines))


def parse_dml_steps(text: str) -> list:
    """แยกไฟล์ DML เป็น step ตาม marker; คืน [(step_name, sql)]"""
    marks = []
    for i, line in enumerate(text.splitlines(keepends=True)):
        if line.startswith(STEP_MARKER):
            marks.append((i, line[len(STEP_MARKER):].strip()))
    if not marks:
        return [("STEP_1_MAIN", text.strip())]
    lines = text.splitlines(keepends=True)
    steps = []
    for j, (idx, name) in enumerate(marks):
        stop = marks[j + 1][0] if j + 1 < len(marks) else len(lines)
        steps.append((name, "".join(lines[idx + 1:stop]).strip()))
    return steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("--reuse-guid", action="store_true",
                    help="(default แล้ว) อ่าน GlobalId เดิมจาก _guid_map.json - คงไว้เพื่อ backward compat")
    ap.add_argument("--new-guid", action="store_true",
                    help="สุ่ม GlobalId ใหม่ทั้งหมด ไม่อ่าน _guid_map.json (ใช้เฉพาะก่อน import ครั้งแรก "
                         "- ถ้า import ไปแล้ว Smart Import จะสร้าง object ซ้ำแทนการ update)")
    ap.add_argument("--i-know-this-is-deprecated", action="store_true")
    args = ap.parse_args()
    if not args.i_know_this_is_deprecated:
        sys.exit("[DEPRECATED] ใช้ python scripts/pipeline/build_odi_export.py แทน (ดูหัวไฟล์)")

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    odi = config.get("odi", {})
    dml_manifest_path = Path(config["paths"]["dml_manifest"])
    output_path = Path(config["paths"]["output_odi_export"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tpl_path = Path(odi.get("field_template", "references/odi-export-field-template.json"))

    # ค่าของ repository ต้องมาจาก Smart Export reference เท่านั้น — ไม่มีค่าตายตัวแทน (ปฏิเสธการเขียนไฟล์ถ้าไม่ครบ)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import read_smart_export as rse
    ref, ref_err = rse.load_reference(Path("."))
    if ref_err:
        sys.exit(f"[ERROR] Smart Export reference ใช้ไม่ได้: {ref_err}\n"
                 "        วางไฟล์ที่ input/odi_reference/ (export จาก repository ปลายทาง) แล้วรันใหม่ — ไม่สร้าง XML จากค่าเดา")
    refv = rse.odi_values(ref)
    miss = []
    for k in ("repository_version", "odi_version", "context_code", "logical_schema"):
        if not odi.get(k):
            if refv[k]:
                odi[k] = refv[k]
            else:
                miss.append(k)
    for k in ("origin_master_repository_id", "origin_work_repository_id"):
        if odi.get(k) in (None, ""):
            if refv[k] != "":
                odi[k] = int(refv[k])
            else:
                miss.append(k)
    if miss:
        sys.exit(f"[ERROR] ไม่มีค่า odi.{', odi.'.join(miss)} ใน config/config.json และอ่านจาก reference ไม่ได้อย่างไม่กำกวม "
                 "(เช่น reference มีหลายค่า) — ตั้งใน config ให้ตรงกับ Topology แล้วรันใหม่ · ไม่เดาแทน")
    if ref.get("max_internal_id", 0) >= int(odi.get("id_base", 90000)):
        print(f"[WARN] reference มี internal ID สูงสุด {ref['max_internal_id']} ≥ odi.id_base {odi.get('id_base', 90000)} — เพิ่ม odi.id_base ใน config เพื่อกัน ID ชน")
    print(f"[INFO] ค่า repository อ่านจาก reference: {ref['file']}")

    if not dml_manifest_path.exists():
        sys.exit(f"[ERROR] ไม่พบ {dml_manifest_path} - รัน gen_dml.py ก่อน")
    if not tpl_path.exists():
        sys.exit(f"[ERROR] ไม่พบ field template: {tpl_path}")

    manifest = json.loads(dml_manifest_path.read_text(encoding="utf-8"))
    if not manifest:
        sys.exit("[ERROR] dml manifest ว่างเปล่า")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.0")
    user = odi.get("odi_user", "SUPERVISOR")
    em = Emitter(tpl_path, now, user)

    guid_path = output_path.parent / "_guid_map.json"
    # default = reuse: import เข้า ODI ไปแล้ว GlobalId ต้องคงเดิมเพื่อให้ Smart Import เป็นการ update ไม่ใช่สร้างซ้ำ
    reuse = guid_path.exists() and not args.new_guid
    guids = json.loads(guid_path.read_text(encoding="utf-8")) if reuse else {}
    print(f"[INFO] GlobalId: {'reuse จาก ' + str(guid_path) + f' ({len(guids)} key)' if reuse else 'สุ่มใหม่ทั้งหมด'}")

    def guid(key: str) -> str:
        if key not in guids:
            guids[key] = str(uuid.uuid4())
        return guids[key]

    base = int(odi.get("id_base", 90000))
    i_project, i_folder, i_package = base, base + 1, base + 2
    next_id = base + 10

    def alloc():
        nonlocal next_id
        next_id += 1
        return next_id

    lschema = odi["logical_schema"]
    techno = odi.get("techno", "ORACLE")
    ctx = odi.get("context_code")

    # ---------------- header ----------------
    em.out.append('<?xml version="1.0" encoding="ISO-8859-1"?>')
    em.out.append("<SunopsisExport>")
    em.out.append(
        f'<Admin IsSmartExportFile="true" RepositoryVersion="{odi["repository_version"]}"'
        f' OdiVersion="{odi["odi_version"]}"'
        f' OriginMasterRepositoryID="{odi["origin_master_repository_id"]}"'
        f' IsLegacyIdCompatible="false"'
        f' OriginWorkRepositoryID="{odi["origin_work_repository_id"]}"'
        f' Created="{datetime.now().strftime("%Y-%m-%d %H:%M:%S +0000")}" />')
    em.out.append(
        f'<Encryption algorithm="AES" keyLength="128" exportKeyHash="null"'
        f' keyVect="{uuid.uuid4().hex[:22]}==" exportKeySalt="{uuid.uuid4()}"'
        f' containsCipherText="false"/>')
    em.out.append('<SmartExportList materializeShortcut="false">')
    em.out.append(f'   <Include><![CDATA[SnpProject#{i_project}]]></Include>')
    em.out.append("</SmartExportList>")

    # ---------------- project / folder ----------------
    em.obj("SnpProject", {
        "GlobalId": guid("project"), "IProject": i_project,
        "ProjectCode": odi.get("project_code", "MIGRATION"),
        "ProjectName": odi.get("project_name", "migration"),
        "IndChange": "I", "FirstDate": now, "LastDate": now,
        "FirstUser": user, "LastUser": user, "IntVersion": "1",
    })
    em.obj("SnpFolder", {
        "GlobalId": guid("folder"), "IFolder": i_folder, "IProject": i_project,
        "FolderName": odi.get("folder_name", "migration"), "ParIFolder": "null",
        "IndChange": "I", "FirstDate": now, "LastDate": now,
        "FirstUser": user, "LastUser": user, "IntVersion": "1",
    })
    variables = odi.get("variables") or []
    origtxt_rows = ORIGTXT_ROWS + ([ORIGTXT_VAR_IN] if variables else [])
    for row in origtxt_rows:
        em.obj("SnpOrigTxt", row)

    # ---------------- variables (Refresh Variable) ----------------
    # ใช้แทน procedure ที่ระบุใน replaces_task (เช่น 000000 precheck) - โครงสร้างตาม Smart Export จริง:
    # SnpVar (VarType=P project variable, IndStore=L เก็บค่าล่าสุด) + SnpTxtHeader (refresh query, ITxtOrig=128)
    var_objs = []
    replaced = set()
    for v in variables:
        i_var, i_vtxt = alloc(), alloc()
        name = v["name"]
        em.obj("SnpVar", {
            "GlobalId": guid(f"var:{name}"), "IVar": i_var, "IProject": i_project,
            "VarName": name, "VarDatatype": v.get("datatype", "N"),
            "VarType": v.get("var_type", "P"), "IndStore": v.get("store", "L"),
            "LschemaName": v.get("logical_schema") or lschema,
            "ITxtVarIn": i_vtxt, "ITxtVar": "null", "ITxtVarValTxt": "null",
            "IndChange": "I", "FirstDate": now, "LastDate": now,
            "FirstUser": user, "LastUser": user, "IntVersion": "1",
        })
        em.obj("SnpTxtHeader", {
            "GlobalId": guid(f"vartxt:{name}"), "ITxt": i_vtxt,
            "ITxtOrig": ORIGTXT_VAR_IN["ITxtOrig"], "Txt": v["refresh_query"].strip(),
            "Enc": "0", "SqlIndGrp": "2",
        })
        var_objs.append((name, i_var))
        for t in v.get("replaces_tasks", []):
            replaced.add(str(t))

    # ---------------- procedures + steps ----------------
    def seq_key(e):
        """เรียงตามลำดับงานจริงของ workflow ไม่ใช่ตามชื่อไฟล์
        ชื่อ task ของ Blendata ขึ้นต้นด้วยเลขลำดับ (010000, 020000, 050100, ...)"""
        tid = e["task_id"]
        name = tid.split("_", 2)[2] if tid.startswith("task_") and tid.count("_") >= 2 else tid
        head = name.split("_", 1)[0]
        return (0, int(head)) if head.isdigit() else (1, 0), name

    manifest = sorted(manifest, key=seq_key)

    procs = []
    skipped = []
    for entry in manifest:
        task_id = entry["task_id"]
        if any(f"_{t}_" in task_id for t in replaced):
            skipped.append((task_id, "แทนด้วย ODI variable (odi.variables.replaces_tasks)"))
            continue
        dml_file = Path(entry["dml_file"])
        if not dml_file.exists():
            skipped.append((task_id, "ไม่พบไฟล์ DML"))
            continue

        # ชื่อ procedure = ชื่อ task เดิม (ตัด task_<hash>_ ออก) ให้อ่านรู้เรื่องใน ODI
        proc_name = entry.get("procedure_name", f"PRC_{task_id}")
        if task_id.startswith("task_") and "_" in task_id[5:]:
            proc_name = task_id.split("_", 2)[2]

        i_trt = alloc()
        em.obj("SnpTrt", {
            "GlobalId": guid(f"trt:{task_id}"), "ITrt": i_trt,
            "IFolder": i_folder, "IProject": i_project,
            "TrtName": proc_name, "TrtType": "U", "ITxtTrtTxt": "null",
            "ITxtDelTxt": "null", "IndChange": "I",
            "KmTechno": techno, "KmSrcTechno": techno,
            "FirstDate": now, "LastDate": now, "FirstUser": user,
            "LastUser": user, "IntVersion": "1",
        })

        steps = parse_dml_steps(dml_file.read_text(encoding="utf-8"))
        for order, (step_name, sql) in enumerate(steps, 1):
            i_txt, i_line = alloc(), alloc()
            em.obj("SnpTxtHeader", {
                "GlobalId": guid(f"txt:{task_id}:{step_name}"), "ITxt": i_txt,
                "ITxtOrig": ITXT_ORIG_DEF, "Txt": odi_step_sql(sql), "Enc": "null", "SqlIndGrp": "2",
            })
            em.obj("SnpLineTrt", {
                "GlobalId": guid(f"line:{task_id}:{step_name}"),
                "ILineTrt": i_line, "ITrt": i_trt, "OrdTrt": order * 10,
                "SqlName": step_name, "DefITxt": i_txt, "ColITxt": "null",
                "DefTechno": techno, "ColTechno": techno,
                "DefLschemaName": lschema, "ColLschemaName": "null",
                "DefContextCode": ctx or "null", "ColContextCode": "null",
                "IRefTrt": "null", "IRefLineTrt": "null",
                "FirstDate": "null", "LastDate": "null",
                "FirstUser": "null", "LastUser": "null",
            })
        procs.append((task_id, proc_name, i_trt, len(steps)))

    if not procs:
        sys.exit("[ERROR] ไม่มี procedure ให้ generate")

    # ---------------- package + steps ----------------
    em.obj("SnpPackage", {
        "GlobalId": guid("package"), "IPackage": i_package, "IFolder": i_folder,
        "PackName": odi.get("package_name", "PKG_MIGRATION"), "ITxtPack": "null",
        "IndChange": "I", "FirstDate": now, "LastDate": now,
        "FirstUser": user, "LastUser": user, "IntVersion": "1",
    })
    # ลำดับใน package: Refresh Variable ทุกตัวก่อน แล้วตามด้วย procedure (ตาม Smart Export จริง)
    chain = [("V", name, i_var) for name, i_var in var_objs] + \
            [("T", (task_id, proc_name), i_trt) for task_id, proc_name, i_trt, _ in procs]
    step_ids = [alloc() for _ in chain]
    for n, ((kind, ident, ref_id), i_step) in enumerate(zip(chain, step_ids)):
        last = n == len(chain) - 1
        common = {
            "IStep": i_step, "IPackage": i_package,
            "IMapping": "null", "ITable": "null", "IMod": "null",
            "Nno": n, "PosX": 70 + (n % 5) * 140, "PosY": 100 + (n // 5) * 120,
            "OkNextStep": "null" if last else step_ids[n + 1],
            "KoNextStep": "null",
            "OkExit": 1 if last else 0, "OkExitCode": 0,
            "KoExit": 1, "KoExitCode": "null",
            "IndLogMethod": "Y", "IndChange": "I",
            "FirstDate": now, "LastDate": now, "FirstUser": user,
            "LastUser": user, "IntVersion": "1",
        }
        if kind == "V":
            em.obj("SnpStep", {**common, "GlobalId": guid(f"step:var:{ident}"), "StepName": ident,
                               "StepType": "V", "IVar": ref_id, "ITrt": "null", "VarOp": "=",
                               "ITxtVarValue": "null", "VarIncr": "null"})
        else:
            task_id, proc_name = ident
            em.obj("SnpStep", {**common, "GlobalId": guid(f"step:{task_id}"), "StepName": proc_name,
                               "StepType": "T", "ITrt": ref_id, "IVar": "null",
                               "ITxtVarValue": "null", "VarIncr": "null"})

    # ---------------- FK cross-reference ----------------
    for row in origtxt_rows:
        em.obj("SnpFKXRef", {
            "RefKey": f"SNP_ORIGTXT.{row['ITxtOrig']}", "RefObjGlobalId": "null",
            "RefObjFQName": "null", "RefObjFQType": "null", "RefObjFQNameLengths": "null",
        })

    em.out.append("</SunopsisExport>")
    output_path.write_text("\n".join(em.out) + "\n", encoding="ISO-8859-1", errors="replace")
    guid_path.write_text(json.dumps(guids, indent=2), encoding="utf-8")

    total_steps = sum(p[3] for p in procs)
    print(f"[OK] {output_path}")
    print(f"[SUMMARY] project={odi.get('project_code')} folder={odi.get('folder_name')} "
          f"package={odi.get('package_name')}")
    print(f"[SUMMARY] {len(procs)} procedure / {total_steps} step / ID {base}-{next_id}")
    for name, i in var_objs:
        print(f"    IVar={i} {name} (Refresh Variable)")
    for t, n, i, s in procs:
        print(f"    ITrt={i} {n} ({s} step)")
    for t, why in skipped:
        print(f"[SKIP] {t}: {why}")
    print(f"[SUMMARY] GlobalId map: {guid_path}")
    if "{{" in lschema:
        print(f"\n[ACTION REQUIRED] odi.logical_schema ยังเป็น placeholder '{lschema}' - "
              f"แทนด้วย logical schema จริงใน ODI Topology ก่อน import")
    print("[ACTION REQUIRED] ทดสอบ Smart Import เข้า ODI Dev ก่อนเสมอ")


if __name__ == "__main__":
    main()
