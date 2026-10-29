"""
validate_odi_xml.py
--------------------
ตรวจ Smart Export XML แบบออฟไลน์ก่อน import (agent ยังเข้า ODI ตรงไม่ได้ -> จับให้ได้มากที่สุดก่อนถึงคน)

ตรวจ:
    V1 XML well-formed + encoding header
    V2 ทุก object มี field ครบ/เรียง/type ตรงกับ Smart Export ของ repository ปลายทาง (input/odi_reference/) + topology ครบ
       (SnpConnect/SnpContext/SnpLschema/SnpPschema — ไม่มี = ODI-10113) + <Admin> ตรง reference + ITxtOrig ทุกตัวอยู่ใน reference
    V3 GlobalId ไม่ว่าง/ไม่ซ้ำ (object หลัก)
    V4 internal reference ชี้ไปหา object ที่มีอยู่จริงในไฟล์ (ITrt, IVar, DefITxt, ITxtVarIn, ITxtVarValue,
       OkNextStep/KoNextStep, IPackage, IFolder, IProject, ITxtOrig) — เช่นบั๊ก ITxtVarValue=27463 (09-24)
    V5 package: Nno=0 มีตัวเดียว, chain ครอบคลุมทุก step, step สุดท้าย OkExit=1, ไม่มีวน
    V6 SQL ต่อ step: SQL เดี่ยวห้ามมี ';' ท้าย (ORA-00911), PL/SQL ต้องจบ 'END;', ห้ามมีบรรทัด '/',
       ห้ามมี Spark-ism ค้าง (backtick, date_format(, now(), concat(, `||` ok), placeholder '{{'
    V7 ตัวอักษรที่ encode เป็น ISO-8859-1 ไม่ได้ (กลายเป็น '?') — ใน comment = เตือน, นอก comment = ผิด
    V8 logical schema / context ไม่เป็น placeholder

Usage:
    python scripts/pipeline/validate_odi_xml.py [--xml output/odi_export/PROJ_EXPORT.xml] [--source-check]
      --source-check  ตรวจ V7 จากไฟล์ DML ต้นทางด้วย (XML ที่ encode แล้วเห็นแค่ '?')
"""
import argparse
import json
import re
import sys
import xml.dom.minidom
from pathlib import Path

REF_FIELDS = {  # field -> class ที่ต้องมี id นั้น
    "ITrt": ("SnpTrt", "ITrt"), "IVar": ("SnpVar", "IVar"), "DefITxt": ("SnpTxtHeader", "ITxt"),
    "ITxtVarIn": ("SnpTxtHeader", "ITxt"), "ITxtTrtTxt": ("SnpTxtHeader", "ITxt"), "ITxtVarValue": ("SnpTxtHeader", "ITxt"),
    "OkNextStep": ("SnpStep", "IStep"), "KoNextStep": ("SnpStep", "IStep"),
    "IPackage": ("SnpPackage", "IPackage"), "IFolder": ("SnpFolder", "IFolder"),
    "IProject": ("SnpProject", "IProject"), "ITxtOrig": ("SnpOrigTxt", "ITxtOrig"),
}
MAIN = ("SnpProject", "SnpFolder", "SnpPackage", "SnpTrt", "SnpStep", "SnpVar", "SnpTxtHeader", "SnpLineTrt")
SPARKISM = [(r"`", "backtick"), (r"\bdate_format\s*\(", "date_format()"), (r"\bnow\s*\(\s*\)", "now()"),
            (r"\bconcat\s*\(", "concat()"), (r"\bnvl2?\s*\([^)]*\)\s*::", "cast ::"), (r"\{\{", "placeholder {{")]


def parse(path: Path):
    x = path.read_text(encoding="iso-8859-1")
    objs = []
    for m in re.finditer(r'<Object class="([\w.]+)">(.*?)</Object>', x, re.S):
        fields = [(g.group(1), g.group(2), g.group(3) if g.group(3) is not None else g.group(4))
                  for g in re.finditer(r'<Field name="(\w+)" type="([\w.\[\]]+)">(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</Field>',
                                       m.group(2), re.S)]
        objs.append((m.group(1).split(".")[-1], fields))
    return x, objs


def parse_text(x: str):
    objs = []
    for m in re.finditer(r'<Object class="([\w.]+)">(.*?)</Object>', x, re.S):
        fields = [(g.group(1), g.group(2), g.group(3) if g.group(3) is not None else g.group(4))
                  for g in re.finditer(r'<Field name="(\w+)" type="([\w.\[\]]+)">(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</Field>',
                                       m.group(2), re.S)]
        objs.append((m.group(1).split(".")[-1], fields))
    return x, objs


def read_reference_text(p: Path) -> str:
    if p.suffix.lower() == ".zip":
        import zipfile
        with zipfile.ZipFile(p) as z:
            n = [n for n in z.namelist() if n.lower().endswith(".xml")][0]
            return z.read(n).decode("iso-8859-1")
    return p.read_text(encoding="iso-8859-1")


def strip_comments(sql: str) -> str:
    # K-E2 (setup_migrate 2.7.2): strip /* ... */ block comments too (placeholder keeps original Spark SQL in a comment - I12 rule 7)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))


def is_plsql(sql: str) -> bool:
    return bool(re.match(r"(DECLARE|BEGIN)\b", strip_comments(sql).strip(), re.I))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("--xml", default=None)
    ap.add_argument("--source-check", action="store_true")
    args = ap.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    path = Path(args.xml or config["paths"]["output_odi_export"])
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import read_smart_export as rse
    refp = rse.find_reference(Path("."))
    # K7 (SS_PAYMENT_3BB_VDO2 2026-10-16): ใช้ reference ตัวที่ build ใช้จริง (build-spec.json) ไม่ใช่ไฟล์ใหม่สุด
    # เพราะ Smart Export หลัง import (หลักฐาน G4) อาจมีแค่ project ของเรา ไม่มี SnpOrigTxt ครบ -> V2 error เท็จ
    try:
        _bs = json.loads((Path("output/odi_export/build-spec.json")).read_text(encoding="utf-8"))
        _rp = (Path("output/odi_export") / _bs.get("reference_smartexport", "")).resolve()
        if _bs.get("reference_smartexport") and _rp.is_file():
            refp = _rp
    except Exception:
        pass
    if not refp:
        print("[ERROR] ไม่พบ Smart Export ใน input/odi_reference/ — ตรวจ XML เทียบ repository ปลายทางไม่ได้")
        return 1
    ref_text = read_reference_text(refp)
    _, ref_objs = parse_text(ref_text)
    tpl = {}
    for c, f in ref_objs:
        tpl.setdefault(c, [(n, t) for n, t, _ in f])
    errors, warns, info = [], [], []

    # V1
    try:
        raw = path.read_bytes()
        xml.dom.minidom.parseString(raw)
        head = raw[:80].decode("latin-1")
        if "ISO-8859-1" not in head:
            warns.append(f"V1 encoding header ไม่ใช่ ISO-8859-1: {head.splitlines()[0]}")
        info.append("V1 well-formed ✅")
    except Exception as e:
        errors.append(f"V1 XML parse ไม่ผ่าน: {e}")
        report(errors, warns, info); return 1
    text, objs = parse(path)
    by_cls = {}
    for c, f in objs:
        by_cls.setdefault(c, []).append({n: v for n, _, v in f})

    # V2 (เทียบกับ reference ของ repository ปลายทาง ไม่ใช่ template ของ generator)
    for c, f in objs:
        want = tpl.get(c)
        if not want:
            warns.append(f"V2 {c}: reference ไม่มี object class นี้ (ตรวจ field ไม่ได้)"); continue
        got = [(n, t) for n, t, _ in f]
        if got != want:
            missing = [n for n, _ in want if n not in dict(got)]
            extra = [n for n, _ in got if n not in dict(want)]
            errors.append(f"V2 {c}: field ไม่ตรง reference (ขาด {missing[:5]}, เกิน {extra[:5]}, หรือลำดับ/type ต่าง)")
    for c in ("SnpConnect", "SnpContext", "SnpLschema", "SnpPschema"):
        if not by_cls.get(c):
            errors.append(f"V2 ไม่มี {c} ในไฟล์ — topology ต้องฝังมาด้วย ไม่งั้น ODI-10113 Broken Link")
    ref_head = re.search(r"<Admin\b([^>]*)/?>", ref_text)
    out_head = re.search(r"<Admin\b([^>]*)/?>", text)
    if ref_head and out_head:
        ra = dict(re.findall(r'(\w+)="([^"]*)"', ref_head.group(1)))
        oa = dict(re.findall(r'(\w+)="([^"]*)"', out_head.group(1)))
        for k in ra:
            if k != "Created" and ra[k] != oa.get(k):
                errors.append(f"V2 <Admin {k}> = {oa.get(k)!r} ไม่ตรง reference ({ra[k]!r}) — import ผิด repository")
    ref_orig = {dict((n, v) for n, _, v in f).get("ITxtOrig") for c, f in ref_objs if c == "SnpOrigTxt"}
    for o in by_cls.get("SnpOrigTxt", []):
        if o.get("ITxtOrig") not in ref_orig:
            errors.append(f"V2 SnpOrigTxt ITxtOrig={o.get('ITxtOrig')} ไม่มีใน reference (SnpsInexistantObjectException ตอน import)")
    if not any(e.startswith("V2") for e in errors):
        info.append(f"V2 field/topology/Admin/ITxtOrig ตรง reference ({len(objs)} object) ✅")

    # V3
    seen = {}
    for c in MAIN:
        for o in by_cls.get(c, []):
            g = o.get("GlobalId")
            if c in ("SnpTxtHeader", "SnpLineTrt") and g in (None, "null"):
                continue
            if not g or g == "null":
                errors.append(f"V3 {c} {o.get('TrtName') or o.get('StepName') or ''}: GlobalId ว่าง")
            elif g in seen:
                errors.append(f"V3 GlobalId ซ้ำ {g}: {seen[g]} และ {c}")
            else:
                seen[g] = c
    if not any(e.startswith("V3") for e in errors):
        info.append(f"V3 GlobalId ไม่ซ้ำ ({len(seen)} object) ✅")

    # V4
    ids = {(c, k): {o.get(k) for o in by_cls.get(c, [])} for c, k in set(REF_FIELDS.values())}
    nref = 0
    for c, lst in by_cls.items():
        if c not in MAIN:
            continue  # topology/FK object (SnpMtxt, SnpConnect, ...) อ้าง id ใน master repository ที่ไม่อยู่ในไฟล์
        for o in lst:
            for fld, (tc, tk) in REF_FIELDS.items():
                v = o.get(fld)
                if v in (None, "null", ""):
                    continue
                if (c, fld) == (tc, tk):
                    continue  # id ของตัวเอง
                nref += 1
                if v not in ids[(tc, tk)]:
                    name = o.get("TrtName") or o.get("StepName") or o.get("VarName") or o.get("SqlName") or ""
                    errors.append(f"V4 {c} {name}: {fld}={v} ชี้ไป {tc} ที่ไม่มีในไฟล์")
    if not any(e.startswith("V4") for e in errors):
        info.append(f"V4 internal reference ครบ ({nref} reference) ✅")

    # V5
    steps = {o["IStep"]: o for o in by_cls.get("SnpStep", [])}
    firsts = [o for o in steps.values() if o.get("Nno") == "0"]
    if len(firsts) != 1:
        errors.append(f"V5 step Nno=0 มี {len(firsts)} ตัว (ต้อง 1)")
    else:
        chain, cur, vis = [], firsts[0], set()
        while cur and cur["IStep"] not in vis:
            vis.add(cur["IStep"]); chain.append(cur)
            cur = steps.get(cur.get("OkNextStep"))
        if cur:
            errors.append(f"V5 package วน (loop) ที่ step {cur['StepName']}")
        if len(chain) != len(steps):
            errors.append(f"V5 chain ครอบคลุม {len(chain)}/{len(steps)} step — มี step ลอย: "
                          + ", ".join(o["StepName"] for o in steps.values() if o["IStep"] not in vis))
        if chain and chain[-1].get("OkExit") != "1":
            warns.append(f"V5 step สุดท้าย {chain[-1]['StepName']} OkExit={chain[-1].get('OkExit')} (ควร 1)")
        if not any(e.startswith("V5") for e in errors):
            info.append(f"V5 package chain {len(chain)} step: " + " → ".join(o["StepName"][:6] for o in chain) + " ✅")

    # V6 + V7 (XML)
    txt = {o["ITxt"]: o.get("Txt") or "" for o in by_cls.get("SnpTxtHeader", [])}
    trt = {o["ITrt"]: o["TrtName"] for o in by_cls.get("SnpTrt", [])}
    nsql = 0
    for o in by_cls.get("SnpLineTrt", []):
        sql = txt.get(o.get("DefITxt"), ""); nsql += 1
        where = f"{trt.get(o['ITrt'], '?')[:30]}/{o.get('SqlName')}"
        body = strip_comments(sql).strip()
        if is_plsql(sql):
            if not re.search(r"END\s*;\s*$", body, re.I):
                errors.append(f"V6 {where}: PL/SQL ไม่จบด้วย 'END;' (PLS-00103)")
        elif body.endswith(";"):
            errors.append(f"V6 {where}: SQL เดี่ยวมี ';' ท้าย (ORA-00911 ผ่าน JDBC)")
        if re.search(r"^\s*/\s*$", sql, re.M):
            errors.append(f"V6 {where}: มีบรรทัด '/' (คำสั่ง SQL*Plus ใช้ใน ODI step ไม่ได้)")
        code = re.sub(r"'(?:[^']|'')*'", "''", body)
        for rx, label in SPARKISM:
            if re.search(rx, code, re.I):
                errors.append(f"V6 {where}: พบ {label} (Spark-ism/placeholder ค้าง)")
        for l in sql.splitlines():
            if "??" in l:
                (warns if l.strip().startswith("--") else errors).append(
                    f"V7 {where}: ตัวอักษรนอก ISO-8859-1 กลายเป็น '?' {'(comment)' if l.strip().startswith('--') else '(นอก comment!)'}: {l.strip()[:60]}")
    if not any(e.startswith("V6") for e in errors):
        info.append(f"V6 SQL {nsql} step ผ่าน (; / END; / '/' / Spark-ism) ✅")

    # V7 source
    if args.source_check:
        man = json.loads(Path(config["paths"]["dml_manifest"]).read_text(encoding="utf-8"))
        for e in man:
            p = Path(e["dml_file"])
            if not p.exists():
                continue
            for i, l in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if any(ord(ch) > 255 for ch in l) and not l.lstrip().startswith("--"):
                    errors.append(f"V7 {p.name}:{i} ตัวอักษรนอก ISO-8859-1 นอก comment: {l.strip()[:60]}")

    # V9 credential ต้องเป็น null
    for o in by_cls.get("SnpConnect", []) + by_cls.get("SnpConnectProp", []):
        for k, v in o.items():
            if re.search(r"(Pass|Pwd)", k) and v not in (None, "", "null"):
                errors.append(f"V9 {k} ใน Topology มีค่า — ช่องรหัสผ่านต้องเป็น null เสมอ (ห้ามฝัง credential)")
    # V8
    for o in by_cls.get("SnpLineTrt", []) + by_cls.get("SnpVar", []):
        for k in ("DefLschemaName", "LschemaName", "DefContextCode"):
            if "{{" in (o.get(k) or ""):
                errors.append(f"V8 {k} ยังเป็น placeholder {o.get(k)}"); break
    return report(errors, warns, info)


def report(errors, warns, info):
    for l in info:
        print(f"  {l}")
    for l in sorted(set(warns)):
        print(f"[WARN] {l}")
    for l in errors:
        print(f"[ERROR] {l}")
    print(f"\n[RESULT] {'❌ ไม่ผ่าน' if errors else '✅ ผ่าน'} — error {len(errors)}, warn {len(set(warns))}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
