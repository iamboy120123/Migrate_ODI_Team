"""
check_inputs.py  (kit 2.8.0) -- ของที่ AI ต้องใช้ครบหรือยัง ก่อนสร้าง package ที่จะ Smart Import "ครั้งเดียว"

หลักการ: ODI Studio ถูกใช้ import แค่ครั้งเดียวตอนจบ (Smart Import) หลังจากนั้นเป็นเรื่องทดสอบ
ดังนั้นทุกอย่างที่ AI ต้องใช้ตอนสร้างไฟล์ต้องได้ครบ *ก่อน* build -- ไม่มีการ "import ลองดูก่อนแล้วเอาผลกลับมา"
สคริปต์นี้ไล่ทุกข้อในรอบเดียว แล้วบอกรายการที่ขาดทั้งหมดพร้อมวิธีหามา (ไม่ทยอยพบทีละอย่างตอน build)

Usage:
    python scripts/checks/check_inputs.py            # ตรวจทั้งหมด (ไม่เขียนไฟล์ใด ๆ)
    python scripts/checks/check_inputs.py --no-dry-run   # ข้ามการลอง build จริงแบบ dry-run
Exit code: 0 = ครบ พร้อมสร้าง package · 1 = ยังขาด
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))

MISSING = []   # (หมวด, รายการที่ขาด, วิธีได้มา)
NOTES = []     # คำเตือนที่ไม่บล็อก


def need(group, what, how):
    MISSING.append((group, what, how))


def note(group, what):
    NOTES.append((group, what))


CREATED = []


def place(rel):
    """สร้างโฟลเดอร์ปลายทางของไฟล์ที่ขอ (ถ้ายังไม่มี) แล้วคืน path เต็มให้ผู้ใช้วางไฟล์"""
    d = ROOT / rel
    try:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            CREATED.append(str(d))
    except OSError:
        pass
    return str(d)


def load_config():
    p = ROOT / "config" / "config.json"
    if not p.exists():
        need("config", "ไม่พบ config/config.json", "รัน setup_migrate.ps1 สร้างโปรเจกต์ก่อน")
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def check_config(cfg):
    odi = cfg.get("odi") or {}
    for k, label in [("project_code", "รหัสโปรเจกต์"), ("project_name", "ชื่อโปรเจกต์"), ("folder_name", "ชื่อ folder"),
                     ("package_name", "ชื่อ package"), ("logical_schema", "logical schema"), ("context_code", "context")]:
        if not str(odi.get(k) or "").strip():
            need("config", f"odi.{k} ว่าง ({label})", "ถาม SA แล้วบันทึกใน config/config.json (agent ถามในแชต)")
    mode = (cfg.get("schema_mode") or "literal").strip().lower()
    if mode == "literal" and not str(cfg.get("target_table_prefix") or "").strip():
        need("config", "schema_mode=literal แต่ target_table_prefix ว่าง (เช่น \"dssdev.\")",
             "ถาม SA ว่าตารางอยู่ schema ไหน (คำตอบ I4) หรือเปลี่ยนไปใช้ schema_mode=odiref")
    if mode not in ("literal", "odiref"):
        need("config", f"schema_mode ไม่ถูกต้อง: {mode!r}", "ใช้ literal หรือ odiref")
    return mode


def check_sources(cfg):
    paths = cfg.get("paths") or {}
    wf = ROOT / (paths.get("input_export_workflow") or "input/blendata/export_workflow.json")
    if not wf.exists():
        need("input", f"ไม่พบไฟล์ Blendata export ({wf})",
             f"export workflow เป็น JSON จาก Blendata แล้ววางที่ {place('input/blendata')} (ชื่อไฟล์เช่น export_workflow.json)")
    raw = ROOT / (paths.get("output_raw_sql") or "output/sql/raw")
    conv = ROOT / (paths.get("output_converted_sql") or "output/sql/converted")
    if not list(raw.glob("*.sql")):
        need("pipeline", "ยังไม่มี SQL ดิบ (output/sql/raw)", "รัน python scripts/pipeline/extract_workflow.py")
    if not list(conv.glob("*.sql")):
        need("pipeline", "ยังไม่มี SQL ที่แปลงแล้ว (output/sql/converted)", "รัน python scripts/pipeline/convert_sql.py")
    return raw, conv


def check_concat(cfg, raw):
    policy = (cfg.get("concat_policy") or "").strip()
    for f in raw.glob("*.sql"):
        if re.search(r"\bconcat\s*\(", f.read_text(encoding="utf-8", errors="replace"), re.I) and not policy:
            need("config", "SQL มี concat() แต่ยังไม่ได้เลือก concat_policy",
                 "ถาม SA: spark_null [แนะนำ: คง NULL แบบ Spark] หรือ plain_concat แล้วบันทึกใน config.json")
            break


def check_reference(cfg):
    import read_smart_export as rse
    ref = rse.find_reference(ROOT)
    why = ("export จาก ODI Studio ของ repository ปลายทางจริง: คลิกขวา Procedure ตัวอย่าง (หรือทั้ง project) -> Export -> "
           "Smart Export แล้ววางที่ " + place("input/odi_reference") + " (เช่น ODI_REFERENCE_DEV_yyyyMMdd.zip · ห้ามใช้ไฟล์จาก repository อื่น)")
    if not ref:
        need("reference", "ไม่มี Smart Export ของ repository ปลายทางใน input/odi_reference/", why)
        return
    try:
        if ref.suffix.lower() == ".zip":
            import zipfile
            with zipfile.ZipFile(ref) as z:
                xmls = [n for n in z.namelist() if n.lower().endswith(".xml")]
                text = z.read(xmls[0]).decode("utf-8", errors="replace") if len(xmls) == 1 else ""
        else:
            text = ref.read_text(encoding="utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        need("reference", f"อ่าน {ref.name} ไม่ได้: {e}", why)
        return
    if not text:
        need("reference", f"{ref.name} ไม่ใช่ Smart Export ที่มี XML 1 ไฟล์", why)
        return
    classes = set(re.findall(r'<Object class="com\.sunopsis\.dwg\.dbobj\.(\w+)"', text))
    for cls, label in [("SnpTrt", "Procedure ตัวอย่างอย่างน้อย 1 ตัว"), ("SnpLineTrt", "step ใน Procedure (command) อย่างน้อย 1 step"),
                       ("SnpPackage", "Package ตัวอย่าง 1 ตัว"), ("SnpStep", "step ใน Package อย่างน้อย 1 step"),
                       ("SnpConnect", "Data Server (Topology)"), ("SnpLschema", "Logical Schema (Topology)"),
                       ("SnpPschema", "Physical Schema (Topology)"), ("SnpContext", "Context (Topology)")]:
        if cls not in classes:
            need("reference", f"reference ไม่มี {label}", why + " โดยเลือกตัวอย่างที่มี object ชนิดนี้อยู่")
    odi = cfg.get("odi") or {}
    for key, label in [("logical_schema", "Logical Schema"), ("context_code", "Context")]:
        val = str(odi.get(key) or "")
        if val and val not in text:
            need("reference", f"ไม่พบ {label} '{val}' ใน reference (config ระบุไว้ แต่ Topology ใน reference ไม่มีชื่อนี้)",
                 "export reference จาก repository ที่ตั้ง Topology นี้ไว้แล้ว หรือแก้ config ให้ตรงกับชื่อใน Topology")


def table_names_from_sql(sql):
    import check_sql as cs
    masked = cs.mask_func_from(cs.mask(sql))
    ctes = cs.collect_ctes(masked)
    out = set()
    for m in cs._TABLE_INTRO.finditer(masked):
        k = m.end()
        if k < len(masked) and masked[k] == "(":
            continue
        im = cs._IDENT.match(masked, k)
        if not im:
            continue
        name = sql[im.start():im.end()].lower()
        base = name.split(".")[-1]
        if base in cs.BUILTIN_UNQUALIFIED or base in ctes or base in cs._NOT_A_TABLE:
            continue
        out.add(base)
    return out


def check_ddl(cfg, raw):
    ddl_dir = ROOT / "input" / "oracle_ddl"
    files = sorted(ddl_dir.glob("*.csv")) if ddl_dir.is_dir() else []
    how = ("รัน SQL ใน Oracle Dev: SELECT OWNER, TABLE_NAME, COLUMN_ID, COLUMN_NAME, DATA_TYPE, DATA_LENGTH, DATA_PRECISION, "
           "DATA_SCALE, NULLABLE, DATA_DEFAULT FROM ALL_TAB_COLUMNS WHERE TABLE_NAME IN (<ตารางที่ขาด>) แล้ว export เป็น CSV วางที่ " + place("input/oracle_ddl") + " (เช่น DDL_<ชื่อตาราง>.csv)")
    if not files:
        need("ddl", "ไม่มีไฟล์ DDL (input/oracle_ddl/*.csv)", how)
        return
    import check_sql as cs
    have = set()
    for f in files:
        try:
            have |= set(cs.load_ddl(str(f)))
        except (ValueError, OSError) as e:
            need("ddl", f"อ่าน {f.name} ไม่ได้: {e}", how)
    used = set()
    for f in raw.glob("*.sql"):
        used |= table_names_from_sql(f.read_text(encoding="utf-8", errors="replace"))
    manifest = ROOT / "output" / "dml" / "_manifest.json"
    if manifest.exists():
        try:
            for e in json.loads(manifest.read_text(encoding="utf-8")):
                if e.get("target_table") and not e.get("readonly"):  # K4: placeholder/read-only ไม่มีตารางปลายทาง
                    used.add(e["target_table"].split(".")[-1].lower())
        except (json.JSONDecodeError, OSError):
            pass
    missing = sorted(t for t in used if t not in have and not t.startswith("err_"))
    if missing:
        need("ddl", "DDL ไม่ครอบคลุมตาราง: " + ", ".join(missing) + " (ใช้ตรวจชนิดคอลัมน์ เช่น DATE/TIMESTAMP ตามกฎ D-R6)", how)


def check_partitions(cfg):
    p = ROOT / "config" / "partitions_check.csv"
    if not p.exists():
        return
    with open(p, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("PARTITIONS_EMPTY") or "").strip().upper() == "N" and not (r.get("DECISION") or "").strip():
                need("I14", f"ตาราง {r.get('TABLE_NAME')} (overwrite + partition ไม่ว่าง) ยังไม่มี DECISION",
                     "ถาม SA (I14): delete_by_partition [แนะนำ] หรือ truncate_all แล้วกรอกคอลัมน์ DECISION ใน config/partitions_check.csv")


def check_flags(cfg):
    p = ROOT / ((cfg.get("paths") or {}).get("review_flags") or "status/REVIEW_FLAGS.md")
    if not p.exists():
        return
    n = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[-1].upper() == "PENDING":
            n += 1
    if n:
        need("review", f"status/REVIEW_FLAGS.md ยังมี PENDING {n} จุด",
             "แก้ SQL ใน output/sql/converted/ ตามกฎ md15 appendix D (ถามผู้ใช้ทีละจุดเมื่อต้องตัดสินใจ) แล้วเปลี่ยนสถานะเป็น RESOLVED")


def check_gates():
    for g in ("G0", "G1", "G2"):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "checks" / "check_gate.py"), g],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
        if "WAIVED" in (r.stdout.splitlines() or [""])[0]:
            continue              # K4: gate WAIVED = ข้อที่ไม่ผ่านมี waiver ที่ SA อนุมัติครอบแล้ว (check_gate K11)
        for line in r.stdout.splitlines():
            if line.strip().startswith("❌"):
                msg = line.strip().lstrip("❌").strip()
                if "REVIEW_FLAGS PENDING" in msg:
                    continue          # รายงานแล้วในหมวด review
                need(g, msg, "ดู status/GATES.md ข้อ " + g + " และ /gate " + g)


def dry_run_build():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "pipeline" / "build_odi_export.py"), "--dry-run"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    out = r.stdout + "\n" + r.stderr
    if r.returncode != 0 or re.search(r"^\s+X ", out, re.M):
        errs = [l.strip() for l in out.splitlines() if l.strip().startswith(("X ", "[ERROR]"))]
        errs = errs[:15] or [out.strip().splitlines()[-1] if out.strip() else "build dry-run ล้มเหลว"]
        for e in errs:
            need("build", e[:300], "แก้ที่ต้นทาง (converted SQL / config / reference) แล้วรัน check_inputs ใหม่")
    for l in out.splitlines():
        if l.strip().startswith("!") and ("ONE example" in l or "built-in literal" in l):
            note("reference", l.strip()[:260])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-dry-run", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    if not cfg:
        print("[ยังไม่พร้อม] ขาด config/config.json")
        sys.exit(1)
    check_config(cfg)
    raw, _conv = check_sources(cfg)
    check_concat(cfg, raw)
    check_reference(cfg)
    check_ddl(cfg, raw)
    check_partitions(cfg)
    check_flags(cfg)
    check_gates()
    if not MISSING and not args.no_dry_run:
        dry_run_build()
    print("=" * 70)
    if CREATED:
        print("สร้างโฟลเดอร์ปลายทางให้แล้ว: " + ", ".join(CREATED))
    print("check_inputs: ของที่ AI ต้องใช้ก่อนสร้าง package สำหรับ Smart Import ครั้งเดียว")
    print("=" * 70)
    if MISSING:
        groups = {}
        for g, what, how in MISSING:
            groups.setdefault(g, []).append((what, how))
        n = 0
        for g, items in groups.items():
            print(f"\n[{g}]")
            for what, how in items:
                n += 1
                print(f"  {n}. ขาด: {what}")
                print(f"     วิธีได้มา: {how}")
        print(f"\n[ยังไม่พร้อม] ขาด {len(MISSING)} รายการ -- ห้ามสร้าง/ส่ง package ให้ผู้ใช้ import จนกว่าจะครบทุกข้อ "
              "(import ใน Studio ทำครั้งเดียวตอนจบ)")
    else:
        print("\n[พร้อม] ของครบ -- สร้าง package ได้ แล้วให้ผู้ใช้ Smart Import ไฟล์ zip ครั้งเดียว")
    if NOTES:
        print("\nคำเตือน (ไม่บล็อก):")
        for g, w in NOTES:
            print(f"  - [{g}] {w}")
    sys.exit(1 if MISSING else 0)


if __name__ == "__main__":
    main()
