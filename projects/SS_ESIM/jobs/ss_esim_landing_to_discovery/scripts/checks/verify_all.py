"""
verify_all.py  (P2, 2026-09-29)
--------------------------------
ตรวจทุกชั้นแบบ offline แล้วเขียน output/verify/VERIFY_REPORT.md + verify.json (ให้ check_gate.py อ่าน)

  V1 static      : py_compile scripts, กฎ ODI step บน converted SQL (; / END; / '/' / non-latin1 / reserved alias / Spark-ism)
  V2 build       : PROJ_EXPORT.xml ไม่ stale, validate_odi_xml.py --source-check = 0 error, SQL ใน XML ตรงกับ DML ทุก step
  V3 portability : schema hardcode (เช่น <work_user>.) ที่ต้องแก้ตอนย้าย environment
  V4 state       : ความสอดคล้องของ MIGRATION_STATUS / OPEN_DECISIONS / PREFLIGHT / ADR / REVIEW_FLAGS
  V5 runtime     : Run Pack ล่าสุด — REPORT ใหม่กว่าผลไหม, assertion PASS กี่ข้อ
  (kit K4, 2026-09-30)
  V2 +studio     : Smart Export จาก Studio (input/odi_reference/) code = DML, GlobalId = _guid_map (ใช้โดย G4)
  V4 +review     : REVIEW_FLAGS ต้องมีไฟล์เมื่อมี converted SQL, PHASE4_REVIEW_LOG ครอบคลุม task ที่ถูก flag และไม่มี OPEN
  V6 schema      : DDL fallback VARCHAR2(4000), DML↔DDL table/column, ชนิดจริงของ landing (all_tab_columns) vs SQL
  V7 run pack    : ไม่มี SET/SPOOL/'/', latin-1, หลาย statement ต้องบอก Execute Script (Alt+X)
  V8 trace       : raw → converted → review → DML → XML → spec → test ต่อ task (output/verify/TRACEABILITY.md)
  V9 release     : backfill pack, CUTOVER_RUNBOOK (Rollback / Go-No-go / Parallel run), validation (ใช้โดย G7)

Usage:
    python scripts/checks/verify_all.py [--level V1,V2,...] [--quiet]
Exit code: 0 = ไม่มี FAIL, 1 = มี FAIL
"""
import argparse
import csv
import io
import json
import py_compile
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Windows: pipe ของ hook ใช้ code page ของเครื่อง -> บังคับ UTF-8 ไม่งั้นข้อความภาษาไทยทำ hook พัง
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
for _d in ("pipeline", "checks"):
    sys.path.insert(0, str(ROOT / "scripts" / _d))

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
ICON = {PASS: "✅", WARN: "⚠️", FAIL: "❌", INFO: "ℹ️"}

SPARKISM = [(r"`", "backtick"), (r"\bdate_format\s*\(", "date_format()"), (r"\bnow\s*\(\s*\)", "now()"),
            (r"\bconcat\s*\(", "concat()"), (r"\bnvl2\s*\(", "nvl2()"), (r"\bLIMIT\s+\d+", "LIMIT n"),
            (r"\b(explode|collect_list|collect_set|regexp_extract|split|element_at)\s*\(", "Spark function"),
            (r"\bAS\s+(long|string|double|boolean)\b", "Spark type in CAST"), (r"\b(bigint|string)\s*\(", "type constructor"),
            (r"\bTRY_CAST\s*\(", "TRY_CAST"), (r"\bINSERT\s+OVERWRITE\b", "INSERT OVERWRITE"), (r"\{\{", "placeholder {{")]


def load_config():
    p = ROOT / "config" / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def strip_comments(sql: str) -> str:
    return "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))


def code_only(sql: str) -> str:
    """ตัด comment และ string literal ออก (ใช้หา Spark-ism / reserved alias)"""
    s = re.sub(r"/\*.*?\*/", " ", strip_comments(sql), flags=re.S)
    return re.sub(r"'(?:[^']|'')*'", "''", s)


def is_plsql(sql: str) -> bool:
    return bool(re.match(r"(DECLARE|BEGIN)\b", strip_comments(sql).strip(), re.I))


def static_check_sql(path: Path) -> list:
    """คืน list ของ (status, message) — ใช้ซ้ำใน hook post_edit.py"""
    out = []
    sql = path.read_text(encoding="utf-8", errors="replace")
    body = strip_comments(sql).strip()
    name = path.name[:60]
    if is_plsql(sql):
        if not re.search(r"END\s*;\s*$", body, re.I):
            out.append((FAIL, f"{name}: PL/SQL ไม่จบด้วย END;"))
    elif body.endswith(";"):
        out.append((WARN, f"{name}: มี ';' ท้าย (generator ตัดให้ แต่ควรลบที่ต้นทาง)"))
    if re.search(r"^\s*/\s*$", sql, re.M):
        out.append((FAIL, f"{name}: มีบรรทัด '/'"))
    for i, l in enumerate(sql.splitlines(), 1):
        if any(ord(ch) > 255 for ch in l) and not l.lstrip().startswith("--"):
            out.append((FAIL, f"{name}:{i} ตัวอักษรนอก ISO-8859-1 นอก comment")); break
    code = code_only(sql)
    for rx, label in SPARKISM:
        if re.search(rx, code, re.I):
            out.append((FAIL, f"{name}: พบ {label} ค้าง"))
    try:
        from convert_sql import reserved_aliases
        bad = reserved_aliases(sql)
        if bad:
            out.append((FAIL, f"{name}: alias เป็น Oracle reserved word: {', '.join(sorted(bad))}"))
    except Exception as e:  # noqa
        out.append((WARN, f"{name}: ตรวจ reserved alias ไม่ได้ ({e})"))
    return out


# ---------------------------------------------------------------- V1
def v1(cfg):
    res = []
    bad = []
    for p in sorted((ROOT / "scripts").rglob("*.py")):
        if ".bak-" in p.name or "__pycache__" in p.parts:
            continue
        try:
            py_compile.compile(str(p), doraise=True, cfile=str(ROOT / "output" / "verify" / "_pyc" / (p.stem + ".pyc")))
        except py_compile.PyCompileError as e:
            bad.append(f"{p.relative_to(ROOT)}: {str(e).splitlines()[-1][:120]}")
    res.append((FAIL if bad else PASS, "py_compile scripts/" + (": " + "; ".join(bad) if bad else " ผ่านทุกไฟล์")))
    # K12: task ใน scope.excluded_tasks ไม่เข้า ODI -> ไม่ตรวจกฎ ODI step
    conv = [p for p in sorted((ROOT / "output" / "sql" / "converted").glob("*.sql")) if not is_excluded(short_name(p.stem), cfg)]
    issues = [r for p in conv for r in static_check_sql(p)]
    res.extend(issues)
    if not any(s == FAIL for s, _ in issues):
        res.append((PASS, f"กฎ ODI step บน converted SQL {len(conv)} ไฟล์"))
    return res


# ---------------------------------------------------------------- V2
def _norm(sql: str) -> str:
    s = strip_comments(sql)
    if not is_plsql(s):
        s = re.sub(r";\s*$", "", s.rstrip())
    return re.sub(r"\s+", " ", s).strip()


def v2(cfg):
    res = []
    xml = ROOT / "output" / "odi_export" / "PROJ_EXPORT.xml"
    if not xml.exists():
        return [(FAIL, "ไม่มี output/odi_export/PROJ_EXPORT.xml — รัน /gen-export")]
    srcs = list((ROOT / "output" / "sql" / "converted").glob("*.sql")) + list((ROOT / "output" / "dml").glob("*.sql")) \
        + [ROOT / "config" / "config.json"]
    newer = [p for p in srcs if p.exists() and p.stat().st_mtime > xml.stat().st_mtime + 1]
    res.append((FAIL, "XML stale — ไฟล์ต้นทางใหม่กว่า PROJ_EXPORT.xml: " + ", ".join(p.name[:50] for p in newer[:5]))
               if newer else (PASS, "PROJ_EXPORT.xml ใหม่กว่าไฟล์ต้นทางทั้งหมด"))
    try:
        r = subprocess.run([sys.executable, "scripts/pipeline/validate_odi_xml.py", "--source-check"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        m = re.search(r"error\s+(\d+)\s*,?\s*warn\s+(\d+)", r.stdout)
        if m:
            e, w = int(m.group(1)), int(m.group(2))
            res.append((FAIL if e else (WARN if w else PASS), f"validate_odi_xml --source-check: error {e} warn {w}"))
        else:
            res.append((FAIL, "อ่านผล validate_odi_xml ไม่ได้: " + (r.stdout + r.stderr)[-200:]))
    except Exception as ex:
        res.append((FAIL, f"รัน validate_odi_xml ไม่ได้: {ex}"))
    # fidelity: SQL ใน XML = DML ทุก step
    try:
        diff, checked = dml_vs_xml(xml)
        res.append((FAIL, f"SQL ใน XML ไม่ตรงกับ DML {len(diff)}/{checked} step: " + ", ".join(diff[:5]))
                   if diff else (PASS, f"SQL ใน XML ตรงกับ DML ครบ {checked} step"))
    except Exception as ex:
        res.append((WARN, f"เทียบ SQL XML↔DML ไม่ได้: {ex}"))
    res += studio_state(xml)
    return res


def dml_vs_xml(xml: Path):
    """เทียบ SQL ทุก step ใน XML (PROJ_EXPORT หรือ Smart Export จาก Studio) กับ output/dml -> (diff, checked)"""
    from validate_odi_xml import parse
    _, objs = parse(xml)
    by = {}
    for cls, fields in objs:
        by.setdefault(cls, []).append({k: v for k, _, v in fields})
    txt = {o.get("ITxt"): o.get("Txt") or "" for o in by.get("SnpTxtHeader", [])}
    trt = {o.get("ITrt"): o.get("TrtName") for o in by.get("SnpTrt", [])}
    # kit 2.8.0: builder ของ md15 ตั้ง SqlName ตาม convention ของ reference (ไม่ใช่ชื่อ step) -> จับคู่ตามลำดับคำสั่ง (OrdTrt)
    lines_by_trt = {}
    for o in by.get("SnpLineTrt", []):
        lines_by_trt.setdefault(trt.get(o.get("ITrt"), "?"), []).append(o)
    xml_steps = {}
    for tn, lst in lines_by_trt.items():
        for idx, o in enumerate(sorted(lst, key=lambda x: int(x.get("OrdTrt") or 0)), 1):
            xml_steps[(tn, idx)] = _norm(txt.get(o.get("DefITxt"), ""))
    man = json.loads((ROOT / "output" / "dml" / "_manifest.json").read_text(encoding="utf-8"))
    diff, checked = [], 0
    for e in man:
        p = ROOT / e["dml_file"]
        if not p.exists():
            continue
        parts = re.split(r"^--\s*@@ODI_STEP:\s*(\S+)\s*$", p.read_text(encoding="utf-8"), flags=re.M)
        # K5: ชื่อ procedure มี prefix ได้ (เช่น PRC_) -> ใช้ procedure_name จาก manifest ก่อน, ไม่งั้นจับคู่ด้วยชื่อไฟล์
        names = [t for t in trt.values() if t]
        tname = e.get("procedure_name") if e.get("procedure_name") in names else \
            next((t for t in names if t == p.stem or t in p.stem or t.endswith("_" + short_name(p.stem))), None)
        for n, i in enumerate(range(1, len(parts), 2), 1):
            step, body = parts[i], parts[i + 1]
            checked += 1
            if xml_steps.get((tname, n)) != _norm(body):
                diff.append(f"{(tname or p.stem)[:40]}/{step}")
    return diff, checked


def latest_smart_export():
    xs = sorted((ROOT / "input" / "odi_reference").glob("*.xml"), key=lambda p: p.stat().st_mtime)
    return xs[-1] if xs else None


def studio_state(xml: Path):
    """kit K-G4: หลัง Smart Import — Smart Export จาก Studio (input/odi_reference/) ต้องมี code = DML และ GlobalId = _guid_map"""
    se = latest_smart_export()
    # K-E3 (setup_migrate 2.7.2): /sync-guid -> /gen-export makes PROJ_EXPORT.xml newer than the Smart Export (only GlobalIds change),
    # so compare against the newest DML file instead of PROJ_EXPORT.xml; code equality is still checked by dml_vs_xml below.
    dmls = [p for p in (ROOT / "output" / "dml").glob("*.sql")]
    ref_mtime = max((p.stat().st_mtime for p in dmls), default=xml.stat().st_mtime)
    if not se or se.stat().st_mtime + 1 < ref_mtime:
        return [(INFO, "Studio: ยังไม่มี Smart Export ที่ใหม่กว่า PROJ_EXPORT.xml ใน input/odi_reference/ (ต้องมีหลัง import — G4)")]
    res = []
    try:
        diff, checked = dml_vs_xml(se)
        res.append((FAIL, f"Studio ({se.name[:50]}): code ใน Studio ไม่ตรงกับ DML {len(diff)}/{checked} step: " + ", ".join(diff[:5])
                    + " — import แบบ Overwrite หรือยัง?")
                   if diff or not checked else (PASS, f"Studio ({se.name[:50]}): code ใน Studio ตรงกับ DML ครบ {checked} step"))
    except Exception as ex:
        res.append((WARN, f"Studio: เทียบ Smart Export ↔ DML ไม่ได้: {ex}"))
    try:
        r = subprocess.run([sys.executable, "scripts/pipeline/sync_guid_from_export.py", "--export", str(se), "--dry-run"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        m = re.search(r"เปลี่ยน\s+(\d+),\s*ใหม่\s+(\d+)", r.stdout)
        if m:
            ch = int(m.group(1)) + int(m.group(2))
            res.append((FAIL if ch else PASS, f"Studio: GlobalId map " + (f"ต่างจาก Studio {ch} key — รัน /sync-guid" if ch else "ตรงกับ Studio")))
        else:
            res.append((WARN, "Studio: อ่านผล sync_guid --dry-run ไม่ได้: " + (r.stdout + r.stderr)[-150:]))
    except Exception as ex:
        res.append((WARN, f"Studio: รัน sync_guid --dry-run ไม่ได้: {ex}"))
    return res


# ---------------------------------------------------------------- V3
def v3(cfg):
    res = []
    user = ((cfg.get("odi") or {}).get("work_user") or "").upper()
    if not user:
        return [(WARN, "ไม่มี odi.work_user ใน config/config.json — ตรวจ schema hardcode ไม่ได้ (ตั้งค่าแล้วรันใหม่)")]
    conv = sorted((ROOT / "output" / "sql" / "converted").glob("*.sql"))
    hits = {p.name[:50]: len(re.findall(rf"\b{user}\.", code_only(p.read_text(encoding='utf-8')), re.I)) for p in conv}
    tot = sum(hits.values())
    res.append((WARN if tot else PASS, f"schema `{user}.` hardcode {tot} จุด ใน {sum(1 for v in hits.values() if v)} ไฟล์"
                + (" — ต้องแทนก่อนย้าย SIT/PROD (G6)" if tot else "")))
    for p in conv:
        if re.search(r"\bJSON_TABLE\b|\bSQL_MACRO\b|\bBOOLEAN\b", code_only(p.read_text(encoding="utf-8")), re.I):
            res.append((WARN, f"{p.name[:50]}: ใช้ feature ที่ต้องยืนยันบน 19c"))
    return res


# ---------------------------------------------------------------- V4
def read(p):
    p = ROOT / p
    return p.read_text(encoding="utf-8") if p.exists() else ""


PENDING_ANSWER = re.compile(r"ยังไม่ทราบ|ยังขอไม่ได้|ยังไม่ได้|รอ(?:ถาม|ยืนยัน)|\bTBD\b", re.I)
BLANK = re.compile(r"_{3,}")


def decision_state(body: str):
    """(answered, reason) ของ Q หนึ่งข้อ — kit K8: ติ๊กแล้วยังไม่พอ
    ไม่ปิดถ้า (1) ตัวเลือกที่ติ๊กเป็น 'ยังไม่ทราบ / ยังขอไม่ได้' (2) บรรทัดที่ติ๊กหรือบรรทัดข้อเท็จจริง (bullet ที่ไม่ใช่ตัวเลือก) ยังมี ____"""
    ticked = [l for l in body.splitlines() if re.match(r"^\s*-\s*\[[xX]\]", l)]
    if not ticked:
        return False, "ยังไม่ติ๊ก"
    if any(PENDING_ANSWER.search(l) for l in ticked):
        return False, "ตัวเลือกที่ติ๊กคือยังไม่ทราบ/ยังขอไม่ได้"
    blanks = [l.strip()[:60] for l in body.splitlines()
              if BLANK.search(l) and (re.match(r"^\s*-\s*\[[xX]\]", l) or re.match(r"^\s*-\s+(?!\[)", l))]
    if blanks:
        return False, f"ติ๊กแล้วแต่ยังไม่กรอกค่า {len(blanks)} บรรทัด (เช่น `{blanks[0]}`)"
    return True, ""


def decisions(detail=False):
    """คืน [(qid, title, answered)] (detail=True → เพิ่ม reason)"""
    s = read("status/OPEN_DECISIONS.md")
    out = []
    for m in re.finditer(r"^### (Q\d+)\.\s*(.*?)$(.*?)(?=^### Q\d+\.|^## |\Z)", s, re.S | re.M):
        ok, why = decision_state(m.group(3))
        out.append((m.group(1), m.group(2).strip(), ok, why) if detail else (m.group(1), m.group(2).strip(), ok))
    return out


def preflight():
    s = read("status/PREFLIGHT_CHECKLIST.md")
    rows = re.findall(r"^\|\s*(\d+)\s*\|\s*([^|]*?)\s*\|", s, re.M)
    ok = sum(1 for _, st in rows if "✅" in st)
    m = re.search(r"passed \*\*(\d+)/(\d+)\*\*", s)
    return ok, len(rows), (int(m.group(1)) if m else None)


def adrs():
    out = []
    for p in sorted((ROOT / ".design" / "adr").glob("ADR-*.md")):
        if "ADR-000" in p.name:
            continue
        m = re.search(r"^- Status:\s*(.+)$", p.read_text(encoding="utf-8"), re.M)
        out.append((p.stem, (m.group(1).strip() if m else "?")))
    return out


def v4(cfg):
    res = []
    st = read("status/MIGRATION_STATUS.md")
    m = re.search(r"Updated:\s*(\d{4}-\d{2}-\d{2})\s*\(rev\.(\d+)\)", st)
    res.append((PASS, f"MIGRATION_STATUS rev.{m.group(2)} ({m.group(1)})") if m else (FAIL, "MIGRATION_STATUS ไม่มีบรรทัด Updated: … (rev.N)"))
    ds = decisions()
    open_q = [q for q, _, a in ds if not a]
    res.append((INFO, f"OPEN_DECISIONS: {len(ds)} ข้อ · ยังเปิด {len(open_q)}" + (f" ({', '.join(open_q)})" if open_q else "")))
    if open_q and re.search(r"^- (?!~~)[^\n]*ทุกข้อใน OPEN_DECISIONS ปิดแล้ว", st, re.M):
        res.append((FAIL, "MIGRATION_STATUS เขียนว่า OPEN_DECISIONS ปิดครบ แต่ยังเปิด " + ", ".join(open_q)))
    for q in open_q:
        if not re.search(rf"\b{q}\b", st):
            res.append((WARN, f"{q} ยังเปิดแต่ไม่ถูกอ้างใน MIGRATION_STATUS"))
    for q, t, ok, why in decisions(detail=True):
        if not ok and why != "ยังไม่ติ๊ก":
            res.append((WARN, f"{q} ({t[:30]}): {why} → ยังนับว่าเปิด"))
    ok, n, header = preflight()
    if header is not None and header != ok:
        res.append((FAIL, f"PREFLIGHT หัวเอกสารเขียน {header}/{n} แต่ตารางมี ✅ {ok}/{n}"))
    else:
        res.append((PASS if ok == n else INFO, f"PREFLIGHT {ok}/{n}"))
    ad = adrs()
    prop = [a for a, s in ad if s.lower().startswith("proposed")]
    res.append((INFO, f"ADR {len(ad)} ฉบับ · Proposed {len(prop)}" + (f" ({', '.join(a[:7] for a in prop)})" if prop else "")))
    res += review_state(cfg)
    return res


def flagged_tasks(rf: str) -> list:
    """task id ทุกตัวที่อยู่ในตาราง REVIEW_FLAGS (ข้ามแถว '-' = ไม่มีรายการค้าง)"""
    out = []
    for m in re.finditer(r"^\|\s*([^|\s][^|]*?)\s*\|[^\n]*\|\s*(PENDING|RESOLVED)\s*\|\s*$", rf, re.M):
        t = m.group(1).strip()
        if t not in ("-", "Task ID") and t not in out:
            out.append(t)
    return out


def review_log_rows(log: str) -> dict:
    """{task: [สถานะ]} จากตารางใน status/PHASE4_REVIEW_LOG.md (คอลัมน์แรก = task, คอลัมน์สุดท้าย = สถานะ)
    อ่านเฉพาะหัวข้อ "## บันทึกต่อ task" ถ้ามี (ตาราง Spark config ไม่ใช่ task)"""
    m = re.search(r"^##\s*บันทึกต่อ task[^\n]*\n(.*?)(?=^##\s|\Z)", log, re.S | re.M)
    if m:
        log = m.group(1)
    rows = {}
    for line in log.splitlines():
        if not line.startswith("|") or re.match(r"^\|\s*(-+|Task)\s*\|", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] and not cells[0].startswith("<"):
            rows.setdefault(cells[0].strip("`"), []).append(cells[-1].upper())
    return rows


def review_state(cfg):
    """REVIEW_FLAGS + PHASE4_REVIEW_LOG (kit K-G2): ไม่มีไฟล์ ≠ ไม่มีปัญหา"""
    res = []
    rf_path = ((cfg.get("paths") or {}).get("review_flags")) or "status/REVIEW_FLAGS.md"
    rf = read(rf_path)
    conv_dir = ROOT / ((cfg.get("paths") or {}).get("output_converted_sql") or "output/sql/converted")
    has_conv = any(conv_dir.glob("*.sql"))
    if not rf:
        res.append((FAIL if has_conv else INFO,
                    f"REVIEW_FLAGS ไม่มีไฟล์ `{rf_path}`" + (" ทั้งที่มี converted SQL — รัน convert_sql.py ใหม่" if has_conv else " (ยังไม่ถึง Phase 3)")))
        return res
    pend = len(re.findall(r"\|\s*PENDING\s*\|", rf))
    res.append((FAIL if pend else PASS, f"REVIEW_FLAGS PENDING {pend}"))
    flagged = flagged_tasks(rf)
    log = read("status/PHASE4_REVIEW_LOG.md")
    if not flagged:
        res.append((PASS, "PHASE4_REVIEW_LOG: ไม่มี task ที่ถูก flag"))
        return res
    if not log:
        res.append((FAIL, f"PHASE4_REVIEW_LOG ไม่มีไฟล์ แต่มี task ถูก flag {len(flagged)} ตัว"))
        return res
    rows = review_log_rows(log)
    miss = [t for t in flagged if not any(t == k or t.startswith(k) or k.startswith(t) for k in rows)]
    open_ = [k for k, sts in rows.items() if any(s in ("OPEN", "PENDING", "") for s in sts)]
    if miss:
        res.append((FAIL, f"PHASE4_REVIEW_LOG ไม่ครอบคลุม task ที่ถูก flag: {', '.join(miss[:5])}"))
    if open_:
        res.append((FAIL, f"PHASE4_REVIEW_LOG ยังมีรายการ OPEN: {', '.join(open_[:5])}"))
    if not miss and not open_:
        res.append((PASS, f"PHASE4_REVIEW_LOG ครอบคลุม {len(flagged)}/{len(flagged)} task · ไม่มี OPEN"))
    return res


# ---------------------------------------------------------------- V5
def latest_pack():
    packs = sorted([p for p in (ROOT / "run_packs").glob("rp*") if p.is_dir()], key=lambda p: p.stat().st_mtime)
    return packs[-1] if packs else None


def assertions(pack):
    """คืน (pass, total) จาก REPORT.md ของ pack"""
    rep = pack / "REPORT.md"
    if not rep.exists():
        return None
    m = re.search(r"## [^\n]*Assertions[^\n]*\n+- ไฟล์: `[^`]*` — PASS (\d+)/(\d+)", rep.read_text(encoding="utf-8"))
    return (int(m.group(1)), int(m.group(2))) if m else None


def v5(cfg):
    pack = latest_pack()
    if not pack:
        return [(INFO, "ยังไม่มี Run Pack")]
    res = [(INFO, f"Run Pack ล่าสุด: {pack.name}")]
    rep = pack / "REPORT.md"
    newer = [p for p in (ROOT / "input" / "run_results" / pack.name).glob("*") if rep.exists()
             and p.stat().st_mtime > rep.stat().st_mtime + 1]
    if not rep.exists():
        res.append((INFO, "ยังไม่มี REPORT.md (pack รอคนรัน)"))
    elif newer:
        res.append((WARN, f"มีผลใหม่กว่า REPORT.md {len(newer)} ไฟล์ — รัน `python scripts/runpack/read_run_results.py --pack run_packs/{pack.name}`"))
    a = assertions(pack)
    if not a:  # pack ล่าสุดอาจยังไม่มีผล (เช่น rp02 รอคนรัน) → ใช้ผล assertions ล่าสุดจาก pack ก่อนหน้า
        for p in sorted([p for p in (ROOT / "run_packs").glob("rp*") if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True):
            a = assertions(p)
            if a:
                res.append((INFO, f"assertions ล่าสุดมาจาก {p.name}"))
                break
    if a:
        res.append((PASS if a[0] == a[1] else FAIL, f"assertions PASS {a[0]}/{a[1]}"))
    else:
        res.append((INFO, "ยังไม่มีผล assertions"))
    return res


# ---------------------------------------------------------------- shared
def short_name(tid: str) -> str:
    """task_<hash>_<code>_<name> -> <code>_<name> (เหมือนชื่อ procedure)"""
    return tid.split("_", 2)[2] if tid.startswith("task_") and tid.count("_") >= 2 else tid


def jload(rel, default):
    p = ROOT / rel
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except Exception:
        return default


def result_csvs(need: set):
    """[(path, rows)] ของ CSV ใน input/run_results/ ที่มี header ครบตาม need (DBeaver NULL = ' ' -> '')"""
    out = []
    for p in sorted((ROOT / "input" / "run_results").glob("**/*.csv")):
        try:
            rows = list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8-sig", errors="replace"))))
        except Exception:
            continue
        rows = [{(k or "").strip().upper(): (v or "").strip() for k, v in r.items()} for r in rows]
        if rows and need <= set(rows[0]):
            out.append((p, rows))
    return out


def excluded_codes(cfg):
    return [str(x) for x in ((cfg.get("scope") or {}).get("excluded_tasks") or [])]


def is_excluded(key: str, cfg) -> bool:
    return any(key.startswith(c) or f"_{c}_" in f"_{key}_" for c in excluded_codes(cfg))


# ---------------------------------------------------------------- V6
def ddl_tables(text: str) -> dict:
    """{TABLE_SHORT: {COL: TYPE}} จาก CREATE TABLE ใน DDL"""
    out = {}
    for m in re.finditer(r"CREATE\s+TABLE\s+([\w.$#\"]+)\s*\((.*?)\n\s*\)\s*[^;]*;", text, re.S | re.I):
        cols = {}
        for line in m.group(2).splitlines():
            c = re.match(r"\s*\"?([A-Za-z][\w$#]*)\"?\s+([A-Za-z][\w]*(?:\s*\([^)]*\))?)", line)
            if c and c.group(1).upper() not in ("CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN"):
                cols[c.group(1).upper()] = c.group(2).upper()
        out[m.group(1).replace('"', "").split(".")[-1].upper()] = cols
    return out


def v6(cfg):
    """Schema / data contract (kit K-V6): DDL final + ชนิดจริงของ landing ตรงกับที่ SQL สมมติ"""
    res = []
    man = [e for e in jload("output/dml/_manifest.json", []) if not e.get("readonly")]
    ddl_p = ROOT / "output" / "ddl" / "01_create_tables.sql"
    if not ddl_p.exists():
        res.append((INFO, "ยังไม่มี output/ddl/01_create_tables.sql (Phase 6 — /gen-ddl)"))
    else:
        text = ddl_p.read_text(encoding="utf-8")
        tables = ddl_tables(text)
        fb = [l.strip().split()[0] for l in text.splitlines() if "VARCHAR2(4000)" in l.upper() and "TODO" in l.upper()]
        res.append((WARN if fb else PASS, f"DDL fallback VARCHAR2(4000) {len(fb)} คอลัมน์" +
                    (f" ({', '.join(fb[:6])}) — ต้องเป็น 0 ก่อน G6" if fb else "")))
        miss_t, miss_c = [], []
        for e in man:
            t = e["target_table"].split(".")[-1].upper()
            if t not in tables:
                miss_t.append(t)
                continue
            miss_c += [f"{t}.{c.upper()}" for c in e.get("columns") or [] if c.upper() not in tables[t]]
        res.append((FAIL, f"target ใน DML ไม่มีใน DDL: {', '.join(sorted(set(miss_t)))}") if miss_t
                   else (PASS, f"target ใน DML มีใน DDL ครบ {len({e['target_table'] for e in man})} ตาราง"))
        if miss_c:
            res.append((FAIL, f"คอลัมน์ใน DML ไม่มีใน DDL {len(miss_c)}: {', '.join(miss_c[:6])}"))
        mp = ROOT / "output" / "dml" / "_manifest.json"
        if mp.exists() and mp.stat().st_mtime > ddl_p.stat().st_mtime + 1:
            res.append((WARN, "DDL เก่ากว่า DML manifest — รัน gen_ddl.py ใหม่"))
    # landing / source data contract จากผล all_tab_columns (rp00_preflight P3 หรือ pack อื่น)
    cols = result_csvs({"TABLE_NAME", "COLUMN_NAME", "DATA_TYPE"})
    if not cols:
        res.append((INFO, "ยังไม่มีผล all_tab_columns ของ landing/source ใน input/run_results/ (/preflight → P3)"))
        return res
    src, missing_obj = {}, set()
    for _, rows in cols:
        for r in rows:
            if r["COLUMN_NAME"] == "MISSING_OBJECT":
                missing_obj.add(r["TABLE_NAME"])
            elif r["COLUMN_NAME"]:
                src[(r["TABLE_NAME"].upper(), r["COLUMN_NAME"].upper())] = r["DATA_TYPE"].upper()
    res.append((INFO, f"data contract: ชนิดคอลัมน์จริง {len(src)} คอลัมน์ จาก {', '.join(p.parent.parent.name for p, _ in cols[:3])}"))
    if missing_obj:
        res.append((WARN, f"source object ไม่พบใน Oracle: {', '.join(sorted(missing_obj))}"))
    typed = {c: t for (_, c), t in src.items() if re.match(r"(TIMESTAMP|DATE|NUMBER|FLOAT|BINARY_)", t)}
    bad = []
    for p in sorted((ROOT / "output" / "sql" / "converted").glob("*.sql")):
        code = code_only(p.read_text(encoding="utf-8"))
        for m in re.finditer(r"\b(TO_TIMESTAMP|TO_DATE|TO_NUMBER|TO_TIMESTAMP_TZ)\s*\(\s*(?:\w+\.)?\"?(\w+)\"?\s*[,)]", code, re.I):
            c = m.group(2).upper()
            if c in typed:
                fn, t = m.group(1).upper(), typed[c]
                wrong = (fn.startswith("TO_TIMESTAMP") or fn == "TO_DATE") and (t.startswith(("TIMESTAMP", "DATE"))) \
                    or fn == "TO_NUMBER" and t.startswith(("NUMBER", "FLOAT", "BINARY_"))
                if wrong:
                    bad.append(f"{p.stem[:30]}: {fn}({c}) แต่ {c} = {t}")
    res.append((FAIL, f"SQL แปลงชนิดซ้ำบนคอลัมน์ที่เป็นชนิดนั้นอยู่แล้ว (แปลงผ่าน NLS → NULL เงียบ ๆ, L1) {len(bad)}: " + "; ".join(bad[:4]))
               if bad else (PASS, "data contract: ไม่พบ TO_TIMESTAMP/TO_DATE/TO_NUMBER บนคอลัมน์ที่เป็นชนิดนั้นอยู่แล้ว"))
    return res


# ---------------------------------------------------------------- V7
_SQLPLUS_RE = re.compile(r"^\s*(SET\s+(SERVEROUTPUT|ECHO|FEEDBACK|PAGESIZE|LINESIZE|DEFINE|TIMING|VERIFY|HEADING|TERMOUT|SQLBLANKLINES)\b|SPOOL\b|PROMPT\b|WHENEVER\b|DEFINE\b|VARIABLE\b|ACCEPT\b|EXEC\b|EXECUTE\s+(?!IMMEDIATE\b))", re.I | re.M)


def _v7_generated_sql():
    """K9 (ver 16): SQL ที่ kit สร้างนอก run_packs (output/dba, backfill, ddl, validation) ก็ต้องรันใน DBeaver ได้เลย"""
    bad = []
    for d in ("dba", "backfill", "ddl", "validation"):
        for f in sorted((ROOT / "output" / d).glob("*.sql")):
            code = re.sub(r"--[^\n]*", "", code_only(f.read_text(encoding="utf-8", errors="replace")))
            tag = f"output/{d}/{f.name}"
            if _SQLPLUS_RE.search(code):
                bad.append(f"{tag}: คำสั่ง SQL*Plus (SET SERVEROUTPUT/SPOOL/EXEC/...) → ORA-00922/ORA-00900 ใน DBeaver")
            if re.search(r"^\s*/\s*$", code, re.M):
                bad.append(f"{tag}: มีบรรทัด '/'")
    return bad


def v7(cfg):
    """Run Pack hygiene (kit K-V7): สคริปต์ที่คนรันต้องรันได้ใน DBeaver โดยไม่ต้องแก้"""
    packs = sorted(p for p in (ROOT / "run_packs").glob("rp*") if p.is_dir())
    extra = _v7_generated_sql()
    if not packs and not extra:
        return [(INFO, "ยังไม่มี Run Pack")]
    res, bad, warn, n = [], [], [], 0
    bad += extra
    for pack in packs:
        readme = (pack / "README.md").read_text(encoding="utf-8") if (pack / "README.md").exists() else ""
        if not readme:
            warn.append(f"{pack.name}: ไม่มี README.md")
        for f in sorted(pack.glob("*.sql")):
            n += 1
            raw = f.read_text(encoding="utf-8", errors="replace")
            head = "\n".join(raw.splitlines()[:4]).lower()
            spark = "blendata" in f.name.lower() or "spark" in f.name.lower() or "not oracle" in head or "blendata" in head
            code = re.sub(r"--[^\n]*", "", code_only(raw))  # code_only ตัดเฉพาะ comment ทั้งบรรทัด -> ตัด inline comment ด้วย
            tag = f"{pack.name}/{f.name}"
            if not spark and re.search(r"^\s*(SET|SPOOL|PROMPT|WHENEVER)\b", code, re.I | re.M):
                bad.append(f"{tag}: คำสั่ง sqlplus (SET/SPOOL/...) → ORA-00922")
            if re.search(r"^\s*/\s*$", code, re.M):
                bad.append(f"{tag}: มีบรรทัด '/'")
            try:
                code.encode("iso-8859-1")
            except UnicodeEncodeError:
                warn.append(f"{tag}: อักขระนอก latin-1 นอก comment")
            stmts = len(re.findall(r";\s*(?:$|\n)", code))
            if not spark and stmts > 1:
                line = next((l for l in readme.splitlines() if f.name in l), "")
                if not re.search(r"Alt\+X|Execute Script", line + head, re.I):
                    warn.append(f"{tag}: {stmts} statement แต่ README ไม่บอก Execute Script (Alt+X)")
    res.append((FAIL, f"Run Pack รันไม่ได้ {len(bad)}: " + "; ".join(bad[:4])) if bad
               else (PASS, f"Run Pack {len(packs)} ชุด {n} สคริปต์ + SQL ใน output/dba|backfill|ddl|validation: ไม่มี SET/SPOOL/EXEC/'/'"))
    for w in warn[:6]:
        res.append((WARN, w))
    return res


# ---------------------------------------------------------------- V8
def v8(cfg):
    """Traceability (kit K-V8): raw → converted → review → DML → XML → spec → test ต่อ task -> output/verify/TRACEABILITY.md"""
    raw = jload("output/sql/raw/_manifest.json", [])
    if not raw:
        return [(INFO, "ยังไม่มี raw manifest (Phase 1)")]
    dml = {short_name(e["task_id"]): e for e in jload("output/dml/_manifest.json", [])}
    conv_dir = ROOT / "output" / "sql" / "converted"
    conv = {short_name(p.stem) for p in conv_dir.glob("*.sql")}
    xml_p = ROOT / "output" / "odi_export" / "PROJ_EXPORT.xml"
    xml = xml_p.read_text(encoding="iso-8859-1") if xml_p.exists() else ""
    rf = read(((cfg.get("paths") or {}).get("review_flags")) or "status/REVIEW_FLAGS.md")
    flagged = {short_name(t) for t in flagged_tasks(rf)} if rf else set()
    logrows = {short_name(k) for k in review_log_rows(read("status/PHASE4_REVIEW_LOG.md"))}
    tests = " ".join(p.read_text(encoding="utf-8", errors="replace") for p in (ROOT / "run_packs").glob("*/*assert*.sql"))
    rows, fails, warns = [], [], []
    replaced_codes = {str(t) for v in ((cfg.get("odi") or {}).get("variables") or []) for t in v.get("replaces_tasks", [])}
    for r in raw:
        # K15 (2026-10-01): non-SQL task ใน raw manifest มี task_id = task_<hash> เฉยๆ → ใช้ task_name (<code>_<name>)
        key = short_name(Path(r["raw_sql_file"]).stem) if r.get("raw_sql_file") else (r.get("task_name") or short_name(r.get("task_id", "")))
        if is_excluded(key, cfg):
            rows.append((key, "excluded", "", "", "", "", "", ""))
            continue
        if key.split("_", 1)[0] in replaced_codes:
            rows.append((key, "variable", "n/a", "n/a", "n/a", "✅" if xml else "⬜", "n/a", "n/a"))
            continue
        code = key.split("_", 1)[0]
        non_sql = not r.get("raw_sql_file")
        spec_p = ROOT / ".design" / "specs" / f"{key}.md"
        spec = "✅" if spec_p.exists() and "_(เติมจาก SQL)_" not in spec_p.read_text(encoding="utf-8") else ("📝" if spec_p.exists() else "⬜")
        c_ok = "n/a" if non_sql else ("✅" if key in conv else "⬜")
        rv = "n/a" if key not in flagged else ("✅" if any(key.startswith(k) or k.startswith(key) for k in logrows) else "⬜")
        d_ok = "✅" if key in dml else "⬜"
        x_ok = "✅" if xml and key in xml else "⬜"
        t_ok = "✅" if code and code in tests else "⬜"
        rows.append((key, "non-sql" if non_sql else "sql", c_ok, rv, d_ok, x_ok, spec, t_ok))
        if c_ok == "⬜" and conv:
            fails.append(f"{key}: ไม่มี converted SQL")
        if d_ok == "⬜" and dml:
            fails.append(f"{key}: ไม่มี DML")
        if x_ok == "⬜" and xml and d_ok == "✅":
            fails.append(f"{key}: ไม่มี procedure ใน PROJ_EXPORT.xml")
        if spec != "✅" and d_ok == "✅":
            warns.append(key)
    lines = ["# TRACEABILITY — " + ROOT.name, "", f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S} · `python scripts/checks/verify_all.py --level V8`", "",
             "✅ ครบ · ⬜ ยังไม่มี · 📝 spec ยังไม่เติม · n/a ไม่เกี่ยว", "",
             "| Task | Kind | Converted | Review log | DML | XML | Spec | Test (assert) |", "|---|---|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    d = ROOT / "output" / "verify"
    d.mkdir(parents=True, exist_ok=True)
    (d / "TRACEABILITY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = [(FAIL, f"traceability ขาด {len(fails)}: " + "; ".join(fails[:4])) if fails
           else (PASS, f"traceability {len(rows)} task — output/verify/TRACEABILITY.md")]
    if warns:
        res.append((WARN, f"spec ยังไม่เติม {len(warns)} task (/design): {', '.join(warns[:5])}"))
    return res


# ---------------------------------------------------------------- V9
def v9(cfg):
    """Release readiness (kit K-V9): artifact ของ Phase 8 ครบและไม่ stale — ใช้โดย G7 (ก่อนหน้านั้นเป็น INFO)"""
    res = []
    bf = ROOT / "output" / "backfill" / "00_README.md"
    ddl = ROOT / "output" / "ddl" / "01_create_tables.sql"
    if not bf.exists():
        res.append((INFO, "backfill pack: ยังไม่มี output/backfill/00_README.md (/cutover)"))
    elif ddl.exists() and ddl.stat().st_mtime > bf.stat().st_mtime + 1:
        res.append((WARN, "backfill pack เก่ากว่า DDL — รัน gen_backfill.py ใหม่"))
    else:
        res.append((PASS, f"backfill pack: {len(list(bf.parent.glob('*')))} ไฟล์"))
    rb = read("status/CUTOVER_RUNBOOK.md")
    if not rb:
        res.append((INFO, "status/CUTOVER_RUNBOOK.md: ยังไม่มี (/cutover → cutover-planner)"))
    else:
        need = {"Rollback": r"^#+.*rollback", "Go/No-go": r"^#+.*(go\s*/\s*no|no-go|go-no)", "Parallel run": r"^#+.*parallel"}
        miss = [k for k, pat in need.items() if not re.search(pat, rb, re.I | re.M)]
        res.append((WARN, f"status/CUTOVER_RUNBOOK.md ขาดหัวข้อ: {', '.join(miss)}") if miss else (PASS, "status/CUTOVER_RUNBOOK.md มี Rollback / Go-No-go / Parallel run"))
        todo = len(re.findall(r"_\(TBD\)_|\bTBD\b|____", rb))
        if todo:
            res.append((WARN, f"status/CUTOVER_RUNBOOK.md ยังมีช่อง TBD {todo} จุด"))
    val = ROOT / "output" / "validation" / "L1_row_count_oracle.sql"
    res.append((PASS, "validation L1 พร้อม") if val.exists() else (INFO, "validation: ยังไม่มี output/validation/ (/validation)"))
    return res


# ---------------------------------------------------------------- V12
def v12(cfg):
    """Hook self-test (kit K9): guard_owned_files / guard_bash block และ pass ตาม fixture, settings.json ผูก hook ครบ"""
    sys.path.insert(0, str(ROOT / "scripts" / "hooks"))
    import selftest
    rs = selftest.run_all()
    bad = [f"{n}: {d}" for ok, n, d in rs if not ok]
    if bad:
        return [(FAIL, m) for m in bad]
    return [(PASS, f"hook self-test {len(rs)} เคส ผ่านทั้งหมด")]


LEVELS = {"V1": ("Static", v1), "V2": ("Build", v2), "V3": ("Portability", v3), "V4": ("State consistency", v4), "V5": ("Runtime", v5),
          "V6": ("Schema / data contract", v6), "V7": ("Run Pack hygiene", v7), "V8": ("Traceability", v8), "V9": ("Release readiness", v9),
          "V12": ("Hook self-test", v12)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default=",".join(LEVELS))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    out = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "levels": {}}
    lines = [f"# VERIFY REPORT — {ROOT.name}", "", f"Generated: {out['generated']} · `python scripts/checks/verify_all.py`", ""]
    worst = PASS
    for lv in [x.strip().upper() for x in a.level.split(",") if x.strip()]:
        title, fn = LEVELS[lv]
        try:
            rs = fn(cfg)
        except Exception as ex:
            rs = [(FAIL, f"verifier error: {ex}")]
        st = FAIL if any(s == FAIL for s, _ in rs) else (WARN if any(s == WARN for s, _ in rs) else PASS)
        worst = FAIL if FAIL in (worst, st) else (WARN if WARN in (worst, st) else PASS)
        out["levels"][lv] = {"status": st, "items": [{"status": s, "msg": m} for s, m in rs]}
        lines += [f"## {ICON[st]} {lv} {title}", ""] + [f"- {ICON[s]} {m}" for s, m in rs] + [""]
    out["status"] = worst
    d = ROOT / "output" / "verify"
    d.mkdir(parents=True, exist_ok=True)
    (d / "VERIFY_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    (d / "verify.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    if not a.quiet:
        for lv, v in out["levels"].items():
            print(f"{ICON[v['status']]} {lv} {LEVELS[lv][0]}")
            for it in v["items"]:
                if it["status"] in (FAIL, WARN):
                    print(f"    {ICON[it['status']]} {it['msg']}")
        print(f"[RESULT] {ICON[worst]} {worst} — output/verify/VERIFY_REPORT.md")
    sys.exit(1 if worst == FAIL else 0)


if __name__ == "__main__":
    main()
