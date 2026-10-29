"""
read_run_results.py
--------------------
อ่านผลที่คนวางไว้ใน input/run_results/<pack>/ (จาก gen_run_pack.py) แล้วประเมินอัตโนมัติ -> run_packs/<pack>/REPORT.md

ประเมินเท่าที่มีไฟล์ — ขั้นที่ยังไม่มีผลจะขึ้น "ยังไม่ได้รัน"
    S1 smart_export_after_import.xml : GlobalId ตรงกับ _guid_map (update ไม่ใช่สร้างซ้ำ), object ซ้ำชื่อ, package chain, SQL ตรงกับที่ generate
    S2 preflight.csv                  : ประเมินแต่ละ check ตามเกณฑ์ + ORA error ระหว่างรัน
    S3 profile_result.csv             : header/ตารางครบ -> พร้อม --apply (copy ไป input/ แล้วรัน gen_ddl + gen_backfill)
    S4 odi_checklist.md               : ข้อที่ยังไม่ติ๊ก
    S5 session_log.csv                : สถานะต่อ step + จัดประเภท ORA error ด้วย KNOWN_ERRORS
    S6 post_run.csv                   : workflow_process_date (&WF_DATE ของ Phase 7), checkpoint, row count

Usage:
    python scripts/runpack/read_run_results.py --pack run_packs/rp01_YYYYMMDD [--apply-profile]
"""
import argparse
import csv
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from sync_guid_from_export import objects  # noqa: E402

# ORA code -> (สาเหตุที่รู้แล้ว, วิธีแก้ใน kit) — error ที่ไม่อยู่ในนี้ = ใหม่ ต้องให้คน/agent วิเคราะห์ ห้ามเดาแก้
KNOWN_ERRORS = {
    "ORA-00922": ("คำสั่งของ sqlplus (SET/SPOOL) ถูกส่งเข้า DB — ใช้ pack v2 (SELECT เดียว)", "gen_run_pack.py v2"),
    "ORA-00911": ("';' ท้าย SQL เดี่ยวใน ODI step", "build_odi_export.odi_step_sql() — regenerate XML"),
    "ORA-00923": ("SELECT ไม่มี FROM", "convert_sql.rule_add_from_dual"),
    "ORA-00933": ("alias เป็น reserved word / syntax Spark ค้าง", "convert_sql.rule_reserved_alias หรือ review SQL"),
    "ORA-00936": ("expression หาย — มักมาจาก alias reserved word", "convert_sql.rule_reserved_alias"),
    "ORA-00942": ("table/view ไม่พบ — ชื่อไม่มี prefix resolve ไม่ได้ หรือยังไม่สร้างตาราง", "preflight [2]/[7], synonym + grant (Q16)"),
    "ORA-01031": ("สิทธิ์ไม่พอ (TRUNCATE ต้องเป็น owner)", "preflight [6], Q9"),
    "ORA-00904": ("ชื่อคอลัมน์ไม่ถูก — DDL ไม่ตรง SQL หรือ repository คนละเวอร์ชัน", "gen_ddl.py / ตรวจ DDL"),
    "ORA-12899": ("ค่ายาวเกินคอลัมน์", "profile -> gen_ddl (Q6)"),
    "ORA-01722": ("แปลงเป็นตัวเลขไม่ได้", "ตรวจ data type / TO_NUMBER ใน SQL"),
    "ORA-01843": ("เดือนไม่ถูกต้องในการแปลงวันที่", "ตรวจ format mask TO_DATE/TO_TIMESTAMP"),
    "ORA-00001": ("unique constraint ซ้ำ (050300 merge key CDR_ID)", "ตรวจ dedup / การรันซ้ำ — ห้าม execute ใหม่ทั้ง package"),
    "ORA-06550": ("PL/SQL compile error — เช่น END ไม่มี ';' หรือ #variable ถูกแทนค่าใน SELECT INTO", "ตรวจ step PL/SQL"),
    "ORA-20001": ("precheck: landing ว่าง", "ingestion ของ landing (Q19)"),
    "ORA-20002": ("precheck: landing ค้างเกิน threshold", "ingestion / threshold"),
}
ODI_STATUS = {"D": "done", "E": "error", "M": "warning", "W": "waiting", "R": "running", "Q": "queued", "A": "done"}


def detect_files(res: Path) -> dict:
    """จับคู่ไฟล์ใน results/ กับ step จาก **เนื้อหา** ไม่ใช่ชื่อ (DBeaver/SQL Developer ตั้งชื่อ export เอง)
    คืน {"S1": path, "S2": path, "S2c": path, "S3": path, "S5": path, "S6": path, "IMG": [paths]}"""
    found = {"IMG": []}
    for f in sorted(res.iterdir(), key=lambda x: x.stat().st_mtime):   # ไฟล์ใหม่กว่าทับไฟล์เก่า
        if f.name == "REPORT.md" or f.is_dir():
            continue
        suf = f.suffix.lower()
        if suf in (".png", ".jpg", ".jpeg"):
            found["IMG"].append(f); continue
        if suf == ".xml":
            head = f.read_text(encoding="iso-8859-1", errors="replace")[:400]
            if "SunopsisExport" in head:
                found["S1"] = f
            continue
        if suf not in (".csv", ".txt"):
            continue
        text = f.read_text(encoding="utf-8-sig", errors="replace")
        first = text.lstrip().splitlines()[0].upper() if text.strip() else ""
        cols = [c.strip().strip('"') for c in first.split(",")]
        data = [l.strip().strip('"').split('","')[0].split(",")[0] for l in text.strip().splitlines()[1:]]
        if "##CHECK" in text:
            found["S2"] = f
        elif "CHECK_ID" in cols:
            found["S2c" if data and all(x == "C" for x in data) else "S2"] = f
        elif {"TBL", "COL", "MAX_LEN"} <= set(cols):
            found["S3"] = f
        elif "DIAG_ID" in cols:
            found["S8"] = f
        elif {"TEST_ID", "ASSERTION", "RESULT"} <= set(cols):
            found["S7"] = f
        elif {"TEST_CASE", "RESULT"} <= set(cols):          # K8 2026-09-29: assertions แบบ S11c (1 แถวต่อ case)
            found["S7"] = f
        elif cols[:3] == ["SEQ", "ITEM", "VALUE"]:          # K8: diagnose แบบ S7_diagnose_zero_rows
            found["S8"] = f
        elif "SESS_NO" in cols and "NNO" in cols:            # K8: ต้องเป็น session log ราย step (S9e ไม่มี NNO)
            found["S5"] = f
        elif cols[:3] == ["ITEM", "NAME", "VALUE"]:
            found["S6"] = f
    return found


def read_csv_text(text: str):
    rows = list(csv.reader(io.StringIO(text)))
    return [r for r in rows if any(c.strip() for c in r)]


def ora_codes(text: str):
    # ตัดข้อความผลลัพธ์ของ preflight [7] ที่มีคำว่า ORA-00942 เป็นค่าในคอลัมน์ (ไม่ใช่ error จริง)
    text = re.sub(r"\*\*\* NOT RESOLVABLE -> ORA-\d{5} \*\*\*", "", text or "")
    return sorted(set(re.findall(r"ORA-\d{5}", text)))


def classify(codes):
    out = []
    for c in codes:
        k = KNOWN_ERRORS.get(c)
        out.append(f"`{c}` — {k[0]} → {k[1]}" if k else f"`{c}` — **ไม่เคยเจอ** → ต้องวิเคราะห์ (ห้ามเดาแก้)")
    return out


# ---------------- S1 ----------------
def eval_s1(res: Path, config: dict, xml=None):
    xml = xml or res / "smart_export_after_import.xml"
    err = res / "S1_error.txt"
    if err.exists():
        t = err.read_text(encoding="utf-8", errors="replace")
        return "❌", [f"Import error: {t.strip()[:300]}"] + classify(ora_codes(t)), []
    if not xml.exists():
        return "⏳", ["ยังไม่ได้รัน"], []
    notes0 = [f"ไฟล์: `{xml.name}`"]
    guid_path = Path(config["paths"]["output_odi_export"]).parent / "_guid_map.json"
    gmap = json.loads(guid_path.read_text(encoding="utf-8")) if guid_path.exists() else {}
    known = set(gmap.values())
    obs = list(objects(xml))
    main = [(c, f) for c, f in obs if c in ("SnpProject", "SnpFolder", "SnpPackage", "SnpTrt", "SnpStep", "SnpVar")]
    matched = [f for c, f in main if f.get("GlobalId") in known]
    unknown = [(c, f.get("TrtName") or f.get("StepName") or f.get("VarName") or f.get("ProjectName")) for c, f in main
               if f.get("GlobalId") not in known]
    names = [f["TrtName"] for c, f in obs if c == "SnpTrt"]
    dups = sorted({n for n in names if names.count(n) > 1})
    steps = {f["IStep"]: f for c, f in obs if c == "SnpStep"}
    first = next((f for f in steps.values() if f.get("Nno") == "0"), None)
    chain = []
    while first and len(chain) < 100:
        chain.append(first["StepName"]); first = steps.get(first.get("OkNextStep"))
    notes = notes0 + [f"GlobalId ตรงกับ `_guid_map.json`: {len(matched)}/{len(main)} object"]
    actions = []
    if unknown:
        notes.append("object ที่ GlobalId ไม่อยู่ใน map: " + ", ".join(f"{c}:{n}" for c, n in unknown[:10]))
        actions.append(f"รัน `python scripts/pipeline/sync_guid_from_export.py --export {xml.as_posix()}` ก่อน generate ครั้งถัดไป")
    if dups:
        notes.append("⚠️ procedure ชื่อซ้ำ (import สร้างซ้ำ): " + ", ".join(dups))
        actions.append("ลบ procedure ที่ซ้ำใน Studio (ตัวที่ GlobalId ไม่ตรง map) แล้ว export ใหม่")
    notes.append(f"package chain ({len(chain)} step): " + " → ".join(n[:6] for n in chain))
    status = "❌" if dups else ("⚠️" if unknown else "✅")
    return status, notes, actions


# ---------------- S2 ----------------
def eval_s2_v2(f: Path, fc):
    """preflight v2: 1 query คอลัมน์ CHECK_ID, CHECK_NAME, ITEM, RESULT, EXPECTED"""
    rows = list(csv.DictReader(io.StringIO(f.read_text(encoding="utf-8-sig", errors="replace"))))
    rows = [{k.strip().upper(): (v or "").strip() for k, v in r.items() if k} for r in rows]
    by = {}
    for r in rows:
        by.setdefault(r.get("CHECK_ID"), []).append(r)
    notes, actions, bad = [f"ไฟล์: `{f.name}` ({len(rows)} แถว)"], [], False
    for r in by.get("0", []):
        v19 = r["RESULT"].startswith("19.")
        notes.append(f"[0] {r['ITEM']} {r['RESULT']}" + ("" if v19 else
                     " ⚠️ ไม่ใช่ 19c (target จริง) — ผลใน Dev อาจต่างจาก Prod: ยืนยัน SQL บน 19c ก่อน cutover"))
    if fc and fc.exists():
        for r in csv.DictReader(io.StringIO(fc.read_text(encoding="utf-8-sig", errors="replace"))):
            r = {k.strip().upper(): (v or "").strip() for k, v in r.items() if k}
            ok = tuple(int(x) for x in re.findall(r"\d+", r.get("RESULT", ""))[:2]) >= (12, 2)
            notes.append(f"[C] COMPATIBLE = {r.get('RESULT')} {'✅' if ok else '❌ ต้อง >= 12.2'}"); bad |= not ok
    else:
        notes.append("[C] COMPATIBLE: ไม่ได้รัน S2c (option) — ถ้า DB 19c ปกติ >= 12.2")
    for r in by.get("2", []):
        ok = r["RESULT"] == r["EXPECTED"]
        notes.append(f"[2] target table {r['RESULT']}/{r['EXPECTED']} {'✅' if ok else '❌'}"); bad |= not ok
        if not ok:
            actions.append("รัน `S2a_create_tables_DRAFT.sql` (Execute Script) แล้วรัน S2b ใหม่")
    miss = [r["ITEM"] for r in by.get("2b", [])]
    if miss:
        notes.append("[2b] ตารางที่ขาด: " + ", ".join(miss))
    ext = by.get("5", [])
    nf = [r["ITEM"] for r in ext if r["RESULT"] == "NOT FOUND"]
    notes.append(f"[5] external object {len(ext) - len(nf)}/{len(ext)} พบ " + ("✅" if not nf else "❌ ไม่พบ: " + ", ".join(nf))
                 + "".join(f"\n    - {r['ITEM']}: {r['RESULT']}" for r in ext if r["RESULT"] != "NOT FOUND"))
    bad |= bool(nf)
    for r in by.get("6", []):
        notes.append(f"[6] {r['ITEM']} เป็น owner: {r['RESULT']} {'✅' if r['RESULT'] == 'YES' else '❌ ต้องมี DROP ANY TABLE (Q9)'}")
        bad |= r["RESULT"] != "YES"
    nr = [r["ITEM"] for r in by.get("7", []) if r["RESULT"] == "NOT RESOLVABLE"]
    n7 = len(by.get("7", []))
    notes.append(f"[7] name resolution {n7 - len(nr)}/{n7} " + ("✅" if not nr else "❌ " + ", ".join(nr)))
    if nr:
        bad = True; actions.append("สร้าง synonym + GRANT SELECT ให้ work user (user ที่ ODI ใช้ login) สำหรับ: " + ", ".join(nr))
    return ("❌" if bad else "✅"), notes, actions


def eval_s2(res: Path, f=None, fc=None):
    f = f or res / "preflight.csv"
    if not f.exists():
        return "⏳", ["ยังไม่ได้รัน"], []
    text = f.read_text(encoding="utf-8", errors="replace")
    if "##CHECK" not in text:
        return eval_s2_v2(f, fc)
    parts = re.split(r"^##CHECK (\w+)##\s*$", text, flags=re.M)
    sections = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    notes, actions, bad = [], [], False

    def rows(k):
        r = read_csv_text(sections.get(k, ""))
        return r[0] if r else [], r[1:]

    for k, body in sections.items():
        for line in classify(ora_codes(body)):
            notes.append(f"[{k}] error: {line}"); bad = True
    h, r = rows("1")
    if r:
        v = r[0][h.index("VALUE")] if "VALUE" in h else r[0][1]
        ok = tuple(int(x) for x in re.findall(r"\d+", v)[:2]) >= (12, 2)
        notes.append(f"[1] COMPATIBLE = {v} {'✅' if ok else '❌ ต้อง >= 12.2'}"); bad |= not ok
    h, r = rows("2")
    if r:
        found, exp = r[0][1], r[0][2]
        ok = found == exp
        notes.append(f"[2] target table {found}/{exp} {'✅' if ok else '❌'}"); bad |= not ok
        if not ok:
            actions.append("รัน `S2a_create_tables_DRAFT.sql` (Dev) แล้วรัน S2b ใหม่")
    h, r = rows("2b")
    if r:
        notes.append("[2b] ตารางที่ขาด: " + ", ".join(x[0] for x in r))
    h, r = rows("5")
    if sections.get("5") is not None:
        objs = sorted({x[1] for x in r if len(x) > 1})
        notes.append(f"[5] external object พบ {len(objs)}: {', '.join(objs) or '-'} {'✅' if len(objs) >= 3 else '❌ ต้องครบ 3'}")
        bad |= len(objs) < 3
    h, r = rows("6")
    if r:
        notes.append(f"[6] {r[0][1]}")
    h, r = rows("7")
    if r:
        nr = [x[0] for x in r if "NOT RESOLVABLE" in ",".join(x)]
        notes.append(f"[7] name resolution: {len(r) - len(nr)}/{len(r)} resolve ได้ {'✅' if not nr else '❌ ' + ', '.join(nr)}")
        if nr:
            bad = True; actions.append("สร้าง synonym + GRANT SELECT ให้ work user (user ที่ ODI ใช้ login) สำหรับ: " + ", ".join(nr))
    return ("❌" if bad else "✅"), notes, actions


# ---------------- S3 ----------------
def eval_s3(res: Path, apply: bool, f=None):
    err, f = res / "S3_error.txt", (f or res / "profile_result.csv")
    if err.exists():
        t = err.read_text(encoding="utf-8", errors="replace").strip()
        return "❌", [f"Blendata error: {t[:300]}"], ["ส่ง error ให้ agent แก้ syntax ของ profile query (stack())"]
    if not f.exists():
        return "⏳", ["ยังไม่ได้รัน"], []
    rows = list(csv.DictReader(io.StringIO(f.read_text(encoding="utf-8-sig", errors="replace"))))
    need = {"tbl", "col", "max_len", "null_cnt", "row_cnt"}
    have = {k.strip().lower() for k in (rows[0].keys() if rows else [])}
    if not need <= have:
        return "❌", [f"header ไม่ครบ: มี {sorted(have)} ต้องมี {sorted(need)}"], ["export ใหม่ให้มี header 5 คอลัมน์"]
    prof_sql = Path("output/ddl/03_profile_source_lengths.sql").read_text(encoding="utf-8")
    expected = set(re.findall(r"^-- (\w+)$", prof_sql, flags=re.M))
    got = {r.get("tbl", "").strip().lower() for r in rows}
    missing = sorted(expected - got)
    notes = [f"{len(rows)} แถว, {len(got)} ตาราง" + (f" — ขาด: {', '.join(missing)}" if missing else " ✅ ครบ")]
    actions = []
    if apply:
        shutil.copy(f, Path("input/run_results/profile_result.csv"))
        for s in ("gen_ddl.py", "gen_backfill.py"):
            p = subprocess.run([sys.executable, f"scripts/pipeline/{s}"], capture_output=True, text=True)
            keep = [l for l in p.stdout.splitlines() if any(k in l for k in ("PROFILE", "SUMMARY", "[OK]"))]
            notes.append(f"{s}: " + (" | ".join(keep)[:300] or (p.stderr.strip()[:300] or "done")))
    else:
        actions.append(f"รันซ้ำด้วย `--apply-profile` เพื่อ copy ไป input/ แล้ว regenerate DDL + backfill")
    return ("⚠️" if missing else "✅"), notes, actions


# ---------------- S4 ----------------
def eval_s4(pack: Path):
    f = pack / "odi_checklist.md"
    if not f.exists():
        return "⏳", ["ยังไม่ได้รัน"], []
    items = re.findall(r"^- \[( |x|X)\] (.+)$", f.read_text(encoding="utf-8"), flags=re.M)
    todo = [t for c, t in items if c == " "]
    if items and len(todo) == len(items):
        return "⏳", ["ยังไม่ได้ทำ (ยังไม่มีข้อไหนติ๊ก)"], []
    notes = [f"ติ๊กแล้ว {len(items) - len(todo)}/{len(items)}"] + [f"ยังไม่ทำ: {t[:90]}" for t in todo]
    blocking = [t for t in todo if "Topology" in t or "Package" in t or "Generate scenario" in t]
    return ("❌" if blocking else ("⚠️" if todo else "✅")), notes, []


# ---------------- S5 ----------------
def eval_s5(res: Path, f=None, imgs=()):
    f, t = (f or res / "session_log.csv"), res / "session_log.txt"
    if not f.exists() and not t.exists():
        if imgs:
            return "👁", [f"มีภาพหน้าจอ {', '.join(i.name for i in imgs)} — reader อ่านภาพไม่ได้ ให้ agent เปิดดู"], \
                ["agent: อ่านภาพหน้าจอแล้วสรุปผล S5"]
        return "⏳", ["ยังไม่ได้รัน"], []
    if not f.exists():
        text = t.read_text(encoding="utf-8", errors="replace")
        codes = ora_codes(text)
        return ("❌" if codes else "⚠️"), ["อ่านจาก session_log.txt (ข้อความอิสระ)"] + classify(codes), \
            ([] if codes else ["ไม่พบ ORA code — ตรวจผลเองหรือส่ง session_log.csv"])
    rows = list(csv.DictReader(io.StringIO(f.read_text(encoding="utf-8-sig", errors="replace"))))
    rows = [{k.strip().upper(): (v or "").strip() for k, v in r.items() if k} for r in rows]
    if not rows:
        return "⚠️", ["session_log.csv ว่าง — query ไม่เจอ session (ตรวจค่า LIKE ใน S5b)"], []
    sess = rows[0]
    notes = [f"session {sess.get('SESS_NO')} `{sess.get('SESS_NAME')}` context {sess.get('CONTEXT_CODE')} — "
             f"สถานะ **{ODI_STATUS.get(sess.get('SESS_STATUS'), sess.get('SESS_STATUS'))}** "
             f"({sess.get('SESS_BEG')} → {sess.get('SESS_END')})"]
    last = {}
    for r in rows:
        last[r.get("NNO")] = r
    failed, actions = [], []
    for nno in sorted(last, key=lambda x: int(x) if x.isdigit() else 999):
        r = last[nno]
        st = ODI_STATUS.get(r.get("STEP_STATUS"), r.get("STEP_STATUS") or "not run")
        runs = sum(1 for x in rows if x.get("NNO") == nno and x.get("NB_RUN"))
        cnt = "/".join(r.get(k) or "0" for k in ("NB_INS", "NB_UPD", "NB_DEL"))
        notes.append(f"step {nno} {r.get('STEP_NAME','')[:40]}: {st}, run {runs}x, ins/upd/del {cnt}")
        if r.get("STEP_STATUS") == "E":
            failed.append(r)
    for r in failed:
        # รวม error จากทุก attempt ของ step นี้ (retry อาจได้ error คนละตัว)
        codes = ora_codes(" ".join(x.get("ERROR_MESSAGE", "") for x in rows if x.get("NNO") == r.get("NNO")))
        notes.append(f"❌ step {r.get('NNO')} {r.get('STEP_NAME')}: {r.get('ERROR_MESSAGE','')[:200]}")
        notes += ["   " + c for c in classify(codes)]
        if any(c not in KNOWN_ERRORS for c in codes) or not codes:
            actions.append(f"step {r.get('NNO')}: error ใหม่ → ส่งให้ agent วิเคราะห์ก่อนแก้")
    if failed:
        actions.append("หลังแก้: ใช้ **Restart from failed step** เท่านั้น (ห้าม execute ใหม่ทั้ง package)")
    status = "✅" if sess.get("SESS_STATUS") == "D" and not failed else "❌"
    return status, notes, actions


# ---------------- S6 ----------------
def eval_s6(res: Path, f=None):
    f = f or res / "post_run.csv"
    if not f.exists():
        return "⏳", ["ยังไม่ได้รัน"], []
    rows = read_csv_text(f.read_text(encoding="utf-8", errors="replace"))
    notes, wf, landing_rows, last_wpd, testdata = [f"ไฟล์: `{f.name}`"], None, None, {}, {}
    for r in rows[1:]:
        if len(r) < 3:
            continue
        item, name, value = r[0].strip(), r[1].strip(), r[2].strip()   # DBeaver export NULL เป็น " "
        if item == "STATUS":
            parts = value.split("|")
            wf = (parts[-1] if parts else "") or None
            success = parts[1] if len(parts) > 1 else ""
            notes.append(f"workflow_status: running={parts[0] if parts else ''} success={success} "
                         f"workflow_process_date={wf or '(ว่าง)'}")
            if success == "TRUE" and not wf:
                notes.append("   = run ล่าสุด**จบถึง 090000 แล้ว** (090000 TRUNCATE status แล้วเขียนแค่ success — "
                             "workflow_process_date จึงหายจากตารางนี้ เหมือน Blendata)")
        elif item == "STATUS_TEMP":
            notes.append(f"status_temp (success ของ run ก่อนหน้า ที่ 010000 อ่านไว้): {value or '(ว่าง)'}")
        elif item == "LAST_WPD":
            last_wpd[name] = value
        elif item == "TESTDATA":
            testdata[name] = value
        elif item == "LANDING":
            notes.append(f"landing: {name} = {value}")
            landing_rows = value.split("|")[-1]
        elif item == "CHECKPOINT":
            notes.append(f"{item.lower()}: {name} = {value}")
            if item == "CHECKPOINT" and value.split("|")[-1] in ("0", ""):
                notes.append("⚠️ checkpoint ว่าง — run ถัดไปจะอ่าน landing ตั้งแต่ต้น (COALESCE(MAX,0)); "
                             "ใน Dev ยอมรับได้ ก่อน parallel run ต้อง seed ตาม CUTOVER_RUNBOOK §2")
        elif item == "ROWCOUNT":
            notes.append(f"rows {name}: {value}")
    if last_wpd:
        notes.append("workflow_process_date ล่าสุดในตาราง transaction: " + ", ".join(f"{k}={v or '-'}" for k, v in last_wpd.items()))
        wf = wf or max((v for v in last_wpd.values() if v.strip()), default=None)
    errs = classify(ora_codes(f.read_text(encoding="utf-8", errors="replace")))
    notes += errs
    actions, status = [], ("❌" if errs else "✅")
    if testdata:
        # ผลที่คาดจาก S2d: TESTSA...01 -> VALID (MAP), ...02 -> TEMP (UNMAP), ...03 -> REJECT (MAN)
        expect = {"_VALID": ("TESTSA0000000001", "MAP"), "_TEMP": ("TESTSA0000000002", "UNMAP"),
                  "_REJECT": ("TESTSA0000000003", "MAN")}
        notes.append(f"ข้อมูลทดสอบ S2d: landing {testdata.get('LANDING', '?')} แถว")
        for suf, (iccid, st) in expect.items():
            k = next((k for k in testdata if k.endswith(suf)), None)
            if not k:
                continue
            got = testdata[k].split("|", 1)[1] if "|" in testdata[k] else testdata[k]
            ok = f"{iccid}:{st}" in got
            notes.append(f"   {'✅' if ok else '❌'} {k}: คาด {iccid}:{st} — ได้ {got}")
            if not ok and landing_rows not in ("0", ""):
                status = "❌"
                actions.append(f"{k}: ผลไม่ตรงที่คาด — ส่ง S5 log + ผล A1–A3 ของ S2d ให้ agent วิเคราะห์")
    if landing_rows in ("0", ""):
        status = "⚠️"
        notes.append("⚠️ **landing ใน Dev ว่าง (0 แถว)** — package รันได้แต่ไม่มีข้อมูลให้ประมวลผล → ทดสอบ logic/validation ไม่ได้; "
                     "v_lag_minutes จะได้ 999999 (ยังไม่มี Evaluate step จึงไม่ fail)")
        actions.append("โหลดข้อมูลเข้า `TB_LANDING_SS_ESIM` ใน Dev (ingestion ตาม Q19 หรือ copy ตัวอย่างที่ mask แล้ว) แล้วรัน S5–S6 ใหม่")
    if wf:
        actions.append(f"ใช้ `&WF_DATE = {wf}` ใน output/validation (Phase 7)")
    elif landing_rows not in ("0", ""):
        actions.append("ไม่พบ workflow_process_date — ใช้เวลาเริ่ม session จาก S5 แทน")
    return status, notes, actions


def eval_s7(res: Path, f=None):
    """S7 test assertions: 1 แถวต่อ assertion (TEST_ID, TBL, ASSERTION, ACTUAL, EXPECTED, RESULT)"""
    if not f or not f.exists():
        return "⏳", ["ยังไม่ได้รัน (หลัง S2d + S5 สำเร็จ)"], []
    rows = list(csv.DictReader(io.StringIO(f.read_text(encoding="utf-8-sig", errors="replace"))))
    rows = [{k.strip().upper(): (v or "").strip() for k, v in r.items() if k} for r in rows]
    fails = [r for r in rows if r.get("RESULT") != "PASS"]
    if rows and "TEST_CASE" in rows[0]:                     # K8: format S11c
        notes = [f"ไฟล์: `{f.name}` — PASS {len(rows) - len(fails)}/{len(rows)}"]
        for r in rows:
            mark = "✅" if r.get("RESULT") == "PASS" else "❌"
            notes.append(f"{mark} {r.get('TEST_CASE')}: คาด {r.get('EXP_TBL')}/{r.get('EXP_STATUS')} · ได้ "
                         f"{r.get('ACT_TBL') or '-'}/{r.get('ACT_STATUS') or '-'} ({r.get('ROWS_FOUND')} แถว)")
        actions = ["ส่งผลให้ agent วิเคราะห์ case ที่ ❌ (แยก fact / สมมติฐาน)"] if fails else []
        return ("✅" if not fails else "❌"), notes, actions
    names = {"1": "#1 MAP→valid", "2": "#2 UNMAP→temp", "3": "#3 MAN→reject", "S": "state หลัง run"}
    notes = [f"ไฟล์: `{f.name}` — PASS {len(rows) - len(fails)}/{len(rows)}"]
    for t in ("1", "2", "3", "S"):
        grp = [r for r in rows if r.get("TEST_ID") == t]
        if grp:
            bad = [r for r in grp if r.get("RESULT") != "PASS"]
            notes.append(f"{'✅' if not bad else '❌'} {names[t]}: {len(grp) - len(bad)}/{len(grp)}")
    for r in fails:
        notes.append(f"   ❌ [{r.get('TEST_ID')}] {r.get('TBL')} · {r.get('ASSERTION')}: ได้ `{r.get('ACTUAL') or '(null)'}` คาด `{r.get('EXPECTED')}`")
    actions = []
    if any(r.get("TEST_ID") == "1" and r.get("ASSERTION") == "row_count" and r.get("RESULT") != "PASS" for r in rows):
        actions.append("#1 ไม่ถึง valid — ตรวจ A3 ของ S2d (มี mapping ไหม) และ A2 (master cdr_type '1')")
    if fails and not actions:
        actions.append("ส่งผล S7 ให้ agent วิเคราะห์ — assertion ที่ fail = logic ใน ODI ต่างจากที่อ่านจาก SQL ต้นทาง")
    return ("✅" if not fails else "❌"), notes, actions


def eval_s8(res: Path, f=None):
    """S8 วินิจฉัยว่าทำไมข้อมูลทดสอบไม่ถูกประมวลผล"""
    if not f or not f.exists():
        return "⏳", ["ยังไม่ได้รัน (ใช้เมื่อ S6/S7 ไม่เห็นผลของข้อมูลทดสอบ)"], []
    all_rows = [[c.strip() for c in r] for r in read_csv_text(f.read_text(encoding="utf-8-sig", errors="replace"))]
    if all_rows and [c.upper() for c in all_rows[0][:3]] == ["SEQ", "ITEM", "VALUE"]:   # K8: format S7 diagnose
        return "👁", [f"ไฟล์: `{f.name}`"] + [f"{r[0]} {r[1]}: {r[2] or '(null)'}" for r in all_rows[1:] if len(r) >= 3], \
               ["agent อ่านค่าแล้วสรุป (diagnose ไม่มี PASS/FAIL ในตัว)"]
    rows = all_rows[1:]
    d = {}
    for r in rows:
        if len(r) >= 3:
            d.setdefault(r[0], []).append((r[1], r[2]))
    notes, actions, status = [f"ไฟล์: `{f.name}`"], [], "✅"
    for k in sorted(d):
        for item, val in d[k]:
            notes.append(f"{k} {item}: {val or '(null)'}")
    last_run = max((v for i, v in d.get("D1", []) if v), default="")
    ins = next((v for i, v in d.get("D2", []) if "insert" in i), "")
    last_ins = ins.split("|")[-1] if ins else ""
    if last_run and last_ins and last_run < last_ins:
        status = "⚠️"
        notes.append(f"➡️ run ล่าสุดจบ {last_run} **ก่อน** insert ข้อมูลทดสอบ {last_ins} → ยังไม่ได้รัน package หลัง S2d")
        actions.append("รัน package ใน ODI (S5) อีกครั้ง แล้วรัน S6 + S7 ใหม่")
    elif last_run and last_ins:
        status = "❌"
        notes.append(f"➡️ run ล่าสุด {last_run} **หลัง** insert {last_ins} แต่ไม่มีผล → 020000 ไม่เห็นข้อมูล: "
                     "ODI น่าจะ connect ด้วย user อื่น (ชื่อที่ไม่มี prefix อ่านตารางของ schema อื่น) — ดู D3")
        actions.append("ตรวจ Topology: data server ของ logical schema / context ที่ใช้ ต้อง login เป็น work user (S4 ข้อ 1-2)")
    multi = [i for i, v in d.get("D3", []) if "," in v]
    if multi:
        notes.append("⚠️ ตารางชื่อซ้ำหลาย schema: " + ", ".join(multi))
    d4 = next((v for i, v in d.get("D4", [])), "")
    if d4.startswith("0|"):
        status = "❌"; actions.append("ไม่มี master cdr_type '1' — ใช้ S2d v2 (B1 เพิ่มให้) หรือโหลด reference data จริง")
    d5 = next((v for i, v in d.get("D5", [])), "")
    if d5.endswith("|0"):
        actions.append("ไม่มี mapping ESIM ที่ใช้ได้ — S2d v2 (B2) เพิ่ม mapping ทดสอบให้ รายการ #1 จึงจะเป็น MAP")
    return status, notes, actions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--apply-profile", action="store_true")
    args = ap.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    pack = Path(args.pack)
    res = Path("input") / "run_results" / pack.name   # ผลจากคน (อ่านอย่างเดียว)
    if not res.is_dir():
        sys.exit(f"[ERROR] ไม่พบ {res.as_posix()} — วางผลที่คน export ไว้ในโฟลเดอร์นี้ก่อน")
    d = detect_files(res)
    evals = [
        ("S1 ODI Smart Import", eval_s1(res, config, d.get("S1"))),
        ("S2 Oracle preflight", eval_s2(res, d.get("S2"), d.get("S2c"))),
        ("S3 Profile", eval_s3(res, args.apply_profile, d.get("S3"))),
        ("S4 ODI checklist", eval_s4(pack)),
        ("S5 ODI Dev run", eval_s5(res, d.get("S5"), d.get("IMG", []))),
        ("S6 Post-run state", eval_s6(res, d.get("S6"))),
        ("Assertions (S8b / S11c)", eval_s7(res, d.get("S7"))),
        ("Diagnose (S7)", eval_s8(res, d.get("S8"))),
    ]
    out = [f"# REPORT — {pack.name}", "", "| Step | ผล |", "|---|---|"]
    out += [f"| {name} | {st} |" for name, (st, _, _) in evals]
    all_actions = []
    for name, (st, notes, actions) in evals:
        out += ["", f"## {st} {name}", ""] + [f"- {n}" for n in notes]
        all_actions += [f"{name.split()[0]}: {a}" for a in actions]
    out += ["", "## ต้องทำต่อ", ""] + ([f"- [ ] {a}" for a in all_actions] or ["- ไม่มี"])
    pending = [n for n, (st, _, _) in evals if st == "⏳"]
    if pending:
        out += ["", "ยังไม่มีผล: " + ", ".join(pending)]
    (pack / "REPORT.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    for name, (st, _, _) in evals:
        print(f"{st} {name}")
    print(f"[OK] {pack / 'REPORT.md'}")


if __name__ == "__main__":
    main()
