"""
read_smart_export.py
--------------------
อ่านค่าของ repository ปลายทางจาก Smart Export ที่วางไว้ที่ input/odi_reference/
(ไฟล์ .xml หรือ .zip ล่าสุด) แล้วรายงานค่า — อ่านอย่างเดียว ไม่เขียนทับ reference

อ่านอะไร:
  <Admin> : RepositoryVersion, OdiVersion, OriginMasterRepositoryID, OriginWorkRepositoryID
  SnpContext.ContextCode · SnpLschema.LschemaName
  SnpPschema.SchemaName / WschemaName · SnpConnect.UserName (ผ่าน IConnect)
ไม่อ่านและไม่เก็บ: ทุกฟิลด์ที่ชื่อมี "pass" (รหัสผ่าน / รหัสที่เข้ารหัส) — ห้ามนำมาใช้

สถานะ: ชื่อฟิลด์ของ Topology (SchemaName, WschemaName, UserName, IConnect) มาจากคำอธิบายใน
knowledge/reference/intake-questions.md ยังไม่เคยเทียบกับไฟล์ Smart Export จริงของ repository นี้
ถ้าอ่านไม่เจอ สคริปต์จะบอกใน "notes" และ "fields_seen" — อย่าเดาค่าแทน

Usage:
    python scripts/pipeline/read_smart_export.py [--root <โฟลเดอร์โปรเจกต์>] [--json] [--apply]
      --json   พิมพ์ผลเป็น JSON (ให้ Setup.ps1 อ่าน)
      --apply  เติมค่าที่ว่างใน config/config.json (odi.*) จาก reference — ไม่ทับค่าที่มีอยู่
exit code: 0 อ่านได้ · 2 ไม่พบไฟล์ / ไฟล์ใช้ไม่ได้ (structural)
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

SKIP_FIELD = re.compile(r"pass", re.I)
OBJ = re.compile(r'<Object class="[\w.]+\.(\w+)">(.*?)</Object>', re.S)
FIELD = re.compile(r'<Field name="(\w+)" type="[\w.\[\]]+">(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</Field>', re.S)
TOPO = ("SnpContext", "SnpLschema", "SnpPschema", "SnpConnect")


def find_reference(root: Path):
    d = root / "input" / "odi_reference"
    cands = [p for p in d.glob("*") if p.is_file() and p.suffix.lower() in (".xml", ".zip")] if d.is_dir() else []
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def read_text(p: Path) -> str:
    if p.suffix.lower() == ".zip":
        parts = []
        with zipfile.ZipFile(p) as z:
            for n in sorted(z.namelist()):
                if n.lower().endswith(".xml"):
                    parts.append(z.read(n).decode("iso-8859-1"))
        return "\n".join(parts)
    return p.read_bytes().decode("iso-8859-1")


def parse(p: Path) -> dict:
    x = read_text(p)
    r = {"file": p.name, "problems": [], "notes": []}
    if not x.strip():
        r["problems"].append("ไฟล์ว่างหรืออ่านไม่ได้")
        return r
    if 'containsCipherText="true"' in x:
        r["problems"].append("ไฟล์ถูกเข้ารหัส (containsCipherText=true) — export ใหม่โดยไม่ใส่ export key")
    adm = re.search(r"<Admin\b[^>]*>", x)
    if not adm:
        r["problems"].append("ไม่พบ <Admin> — ไม่ใช่ Smart Export จาก ODI Studio")
    else:
        a = dict(re.findall(r'(\w+)="([^"]*)"', adm.group(0)))
        r["repository_version"] = a.get("RepositoryVersion", "")
        r["odi_version"] = a.get("OdiVersion", "")
        r["origin_master_repository_id"] = a.get("OriginMasterRepositoryID", "")
        r["origin_work_repository_id"] = a.get("OriginWorkRepositoryID", "")
        for k in ("repository_version", "odi_version", "origin_master_repository_id", "origin_work_repository_id"):
            if r[k] == "":
                r["problems"].append(f"<Admin> ไม่มีค่า {k}")
    ctxs, lss, ps, cons, seen = [], [], [], {}, {}
    maxid = 0
    for m in OBJ.finditer(x):
        cls = m.group(1)
        if cls not in TOPO:
            continue
        f = {}
        for g in FIELD.finditer(m.group(2)):
            name = g.group(1)
            if SKIP_FIELD.search(name):
                continue
            f[name] = g.group(2) if g.group(2) is not None else g.group(3)
        seen.setdefault(cls, sorted(f))
        if cls == "SnpContext" and f.get("ContextCode"):
            ctxs.append(f["ContextCode"])
        elif cls == "SnpLschema" and f.get("LschemaName"):
            lss.append(f["LschemaName"])
        elif cls == "SnpConnect":
            cons[f.get("IConnect", "")] = {"name": f.get("ConName", ""), "user": f.get("UserName", "")}
        elif cls == "SnpPschema":
            ps.append({"schema": f.get("SchemaName", ""), "work_schema": f.get("WschemaName", ""),
                       "iconnect": f.get("IConnect", "")})
    for m in re.finditer(r'<Field name="I[A-Za-z]+" type="[\w.]+">(?:<!\[CDATA\[)?(\d+)', x):
        v = int(m.group(1))
        if v > maxid:
            maxid = v
    if not cons and "SnpConnect" not in x:
        r["problems"].append("ไม่พบ Topology (SnpConnect) — export ไม่ครบ หรือใช้ Export ธรรมดาแทน Smart Export")
    for ph in ps:
        c = cons.get(ph["iconnect"]) or {}
        ph["connection"] = c.get("name", "")
        ph["user"] = c.get("user", "")
        del ph["iconnect"]
    r["contexts"] = sorted(set(ctxs))
    r["logical_schemas"] = sorted(set(lss))
    r["physical_schemas"] = ps
    r["connections"] = [v for v in cons.values()]
    r["max_internal_id"] = maxid
    r["fields_seen"] = seen
    for label, vals, fld in (("context", r["contexts"], "SnpContext.ContextCode"),
                             ("logical schema", r["logical_schemas"], "SnpLschema.LschemaName"),
                             ("physical schema", [p for p in ps if p["schema"]], "SnpPschema.SchemaName"),
                             ("user", [p for p in ps if p["user"]], "SnpConnect.UserName")):
        if not vals:
            r["notes"].append(f"อ่าน {label} ไม่เจอ (ฟิลด์ {fld}) — ดู fields_seen ว่าไฟล์นี้ใช้ชื่อฟิลด์อะไร")
    return r


def unique(vals):
    vals = [v for v in vals if v]
    return vals[0] if len(set(vals)) == 1 else ""


def odi_values(r: dict) -> dict:
    """ค่าที่ไม่กำกวม (มีค่าเดียว) — ถ้ามีหลายค่าคืนว่าง ให้ผู้ใช้เลือก"""
    return {
        "repository_version": r.get("repository_version", ""),
        "odi_version": r.get("odi_version", ""),
        "origin_master_repository_id": r.get("origin_master_repository_id", ""),
        "origin_work_repository_id": r.get("origin_work_repository_id", ""),
        "context_code": unique(r.get("contexts", [])),
        "logical_schema": unique(r.get("logical_schemas", [])),
        "schema_name": unique([p["schema"] for p in r.get("physical_schemas", [])]),
        "work_user": unique([p["user"] for p in r.get("physical_schemas", [])]),
    }


def load_reference(root: Path):
    """คืน (info, error) — error != None = ใช้ไม่ได้ (structural)"""
    p = find_reference(root)
    if not p:
        return None, "ไม่พบ Smart Export ที่ input/odi_reference/ (.xml / .zip)"
    try:
        r = parse(p)
    except (zipfile.BadZipFile, OSError) as e:
        return None, f"อ่าน {p.name} ไม่ได้: {e}"
    if r["problems"]:
        return r, "; ".join(r["problems"])
    return r, None


def apply_to_config(root: Path, r: dict) -> list:
    cfgp = root / "config" / "config.json"
    cfg = json.loads(cfgp.read_text(encoding="utf-8"))
    odi = cfg.setdefault("odi", {})
    v = odi_values(r)
    changed = []
    for k in ("repository_version", "odi_version", "context_code", "logical_schema"):
        if v[k] and not odi.get(k):
            odi[k] = v[k]; changed.append(k)
    for k in ("origin_master_repository_id", "origin_work_repository_id"):
        if v[k] != "" and odi.get(k) in (None, ""):
            odi[k] = int(v[k]); changed.append(k)
    if v["work_user"] and not odi.get("work_user"):
        odi["work_user"] = v["work_user"].upper(); changed.append("work_user")
    if changed:
        cfgp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    r, err = load_reference(root)
    if r is None:
        if a.json:
            print(json.dumps({"found": False, "error": err}, ensure_ascii=True))
        else:
            print(f"[ERROR] {err}")
        sys.exit(2)
    r["found"] = True
    r["error"] = err
    r["values"] = odi_values(r)
    if a.json:
        print(json.dumps(r, ensure_ascii=True))
    else:
        print(f"ไฟล์: {r['file']}")
        for k, v in r["values"].items():
            print(f"  {k:30}: {v if v != '' else '(ไม่มีค่าเดียว / อ่านไม่เจอ)'}")
        for n in r["notes"]:
            print(f"  [NOTE] {n}")
        if err:
            print(f"[ERROR] {err}")
    if err:
        sys.exit(2)
    if a.apply:
        ch = apply_to_config(root, r)
        print(f"[OK] เติม config: {', '.join(ch) if ch else '(ไม่มีค่าว่างให้เติม)'}")


if __name__ == "__main__":
    main()
