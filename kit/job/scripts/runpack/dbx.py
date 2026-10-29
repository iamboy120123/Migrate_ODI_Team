"""
dbx.py — ตัวกลางรัน SQL ของ workspace (2.10.0) · ใช้ร่วมกันโดย run_sql.py / run_pack.py / tools/workspace.py

กติกา (ตั้งใน init ข้อ 9 → shared/team.json "db"):
  ai_access   ai = AI รันได้ทุกคำสั่ง (ต้องได้รับอนุญาตก่อน) · human = คนรันทั้งหมด (ระบบแค่เตรียมไฟล์ + บอกขั้นตอน)
  select_mode ask = ถามก่อนทุกครั้งรวม SELECT · auto = SELECT รันต่อเนื่อง ถามเฉพาะคำสั่งที่เขียน / แก้โครงสร้าง
  users       split = SELECT ใช้ user อ่านอย่างเดียว · คำสั่งเขียนใช้ user ที่เขียนได้ · single = user เดียว
  read_odi_log  อนุญาตให้อ่านตาราง SNP_* ของ ODI (work repository)
การเชื่อมต่อ: shared/db.local.json {"default": "DEV", "connections": {"DEV": {host, port, service, user_ro, user_rw}}}
  (ไม่มีรหัสผ่าน · ไม่ขึ้น Git) · รหัสผ่าน: ตัวแปร ORA_RO_PASSWORD / ORA_RW_PASSWORD (environment อื่นเติม _<ENV> เช่น ORA_RW_PASSWORD_SIT)
  หรือพิมพ์ตอนรันใน Terminal (ไม่แสดงบนจอ ไม่เก็บ)

ประเภทคำสั่ง: read (SELECT/WITH) · write (INSERT/UPDATE/DELETE/MERGE) · ddl (CREATE/ALTER/DROP/TRUNCATE/…) · plsql (BEGIN/DECLARE/CALL)
  ลบแล้วกู้คืนไม่ได้ (destructive): DROP · TRUNCATE · DELETE / UPDATE ที่ไม่มี WHERE · ALTER … DROP → ต้องยืนยันด้วยชื่อตารางอีกชั้น
  ไฟล์ Blendata / Spark SQL ไม่รันเสมอ (คนรันบน Blendata) · คำสั่งเขียนลงตาราง SNP_* ของ ODI ไม่รันเสมอ
ทุกครั้งที่รันถูกบันทึก: งาน = status/DB_RUN_LOG.md (+ คำสั่งที่เขียน → status/DEPLOY_LOG.md) · workspace = registry/db_queries.log
"""
from __future__ import annotations

import csv
import datetime as dt
import getpass
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # root ของงาน (ถูกตั้งใหม่ด้วย set_root เมื่อเรียกจาก workspace)

READ_START = re.compile(r"^\s*(select|with)\b", re.I)
WRITE_START = re.compile(r"^\s*(insert|update|delete|merge)\b", re.I)
DDL_START = re.compile(r"^\s*(create|alter|drop|truncate|rename|comment|grant|revoke|analyze|purge|flashback)\b", re.I)
PLSQL_START = re.compile(r"^\s*(begin|declare|call|exec|execute)\b", re.I)
SKIP_START = re.compile(r"^\s*(commit|rollback|savepoint|set|spool|prompt|whenever|exit|quit|define|undefine|show|desc|describe)\b", re.I)
READ_BAD = re.compile(r"\bfor\s+update\b|\binto\s+[:\w]+\s+from\b", re.I)
SNP = re.compile(r"\bsnp_\w+", re.I)
NAME = r'((?:"[^"]+"|[\w$#]+)(?:\.(?:"[^"]+"|[\w$#]+))?)'


# ---------------------------------------------------------------- ที่อยู่ / ค่าตั้ง
def set_root(p: Path):
    global ROOT
    ROOT = Path(p).resolve()


def ws_root() -> Path | None:
    for p in [ROOT, *ROOT.parents]:
        if (p / "workspace.json").exists() or (p / "tools" / "workspace.py").exists():   # ระหว่าง init ยังไม่มี workspace.json
            return p
    return None


def is_job() -> bool:
    return (ROOT / "job.json").exists() or (ROOT / "config" / "config.json").exists()


def _read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def team_db() -> dict:
    w = ws_root()
    db = dict((_read_json(w / "shared/team.json") if w else {}).get("db") or {})
    if "select_mode" not in db:                                     # team.json รุ่น 2.9.0
        db["select_mode"] = "auto" if db.get("default_mode") == "auto" else "ask"
    db.setdefault("users", "split")
    db.setdefault("ai_access", "human")
    jm = _read_json(ROOT / "job.json") if (ROOT / "job.json").exists() else {}
    m = jm.get("db_mode")                                           # งานตั้งเองชนะค่าทีม
    if m == "human":
        db["ai_access"] = "human"
    elif m in ("auto", "ask") and db.get("ai_access") == "ai":
        db["select_mode"] = m
    return db


def connections() -> tuple[str, dict]:
    w = ws_root()
    raw = _read_json(w / "shared/db.local.json") if w else {}
    if raw and "connections" not in raw and raw.get("host"):        # รุ่น 2.9.0: แบนชั้นเดียว = DEV อ่านอย่างเดียว
        raw = {"default": "DEV", "connections": {"DEV": {**{k: raw[k] for k in ("host", "port", "service") if k in raw},
                                                       "user_ro": raw.get("user", ""), "user_rw": ""}}}
    return raw.get("default", "DEV"), raw.get("connections", {})


def pw_var(kind: str, env: str) -> str:
    d, _ = connections()
    base = "ORA_RO_PASSWORD" if kind == "ro" else "ORA_RW_PASSWORD"
    return base if env == d else f"{base}_{env}"


# ---------------------------------------------------------------- แยก / จัดประเภท SQL
def strip_comments(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    out = []
    for line in s.splitlines():
        buf, q, i = "", False, 0
        while i < len(line):
            c = line[i]
            if c == "'":
                q = not q
            if not q and line[i:i + 2] == "--":
                break
            buf += c
            i += 1
        out.append(buf)
    return "\n".join(out)


def split_statements(text: str) -> list[str]:
    """แยกคำสั่ง: บล็อก PL/SQL จบด้วยบรรทัด '/' · คำสั่งอื่นจบด้วย ';' (ไม่นับใน quote)"""
    body = strip_comments(text)
    out, cur, q, in_plsql = [], "", False, False
    for line in body.splitlines(keepends=True):
        if not cur.strip() and PLSQL_START.match(line) or (not cur.strip() and re.match(r"^\s*create\s+(or\s+replace\s+)?(procedure|function|package|trigger|type)\b", line, re.I)):
            in_plsql = True
        if in_plsql:
            if line.strip() == "/":
                out.append(cur.strip()); cur = ""; in_plsql = False
            else:
                cur += line
            continue
        if line.strip() == "/":
            if cur.strip():
                out.append(cur.strip()); cur = ""
            continue
        for c in line:
            if c == "'":
                q = not q
            if c == ";" and not q:
                if cur.strip():
                    out.append(cur.strip())
                cur = ""
            else:
                cur += c
    if cur.strip():
        out.append(cur.strip().rstrip(";").strip())
    return [s for s in out if s]


def _tables(sql: str, verb: str) -> list[str]:
    pats = {
        "drop": rf"^\s*drop\s+table\s+{NAME}",
        "truncate": rf"^\s*truncate\s+table\s+{NAME}",
        "delete": rf"^\s*delete\s+(?:from\s+)?{NAME}",
        "update": rf"^\s*update\s+{NAME}",
        "alter": rf"^\s*alter\s+table\s+{NAME}",
    }
    m = re.search(pats.get(verb, r"$^"), sql, re.I)
    return [m.group(1).replace('"', "").upper()] if m else []


def classify(sql: str) -> dict:
    s = sql.strip()
    verb = (re.match(r"^\s*(\w+)", s) or [None, ""])[1].lower()
    r = {"sql": s, "verb": verb, "kind": "", "destructive": False, "tables": [], "snp": bool(SNP.search(s)), "why": ""}
    if SKIP_START.match(s):
        r["kind"] = "skip"; r["why"] = "คำสั่งของ SQL*Plus / จัดการ transaction (ระบบจัดการให้เอง)"
    elif READ_START.match(s):
        if READ_BAD.search(s):
            r["kind"] = "write"; r["why"] = "SELECT ที่ล็อกแถว / เขียนตัวแปร"
        else:
            r["kind"] = "read"
    elif WRITE_START.match(s):
        r["kind"] = "write"
        if verb in ("delete", "update") and not re.search(r"\bwhere\b", s, re.I):
            r["destructive"] = True; r["tables"] = _tables(s, verb); r["why"] = f"{verb.upper()} ไม่มี WHERE = ทั้งตาราง"
    elif DDL_START.match(s):
        r["kind"] = "ddl"
        if verb in ("drop", "truncate"):
            r["destructive"] = True; r["tables"] = _tables(s, verb); r["why"] = f"{verb.upper()} กู้คืนไม่ได้"
        elif verb == "alter" and re.search(r"\bdrop\b", s, re.I):
            r["destructive"] = True; r["tables"] = _tables(s, "alter"); r["why"] = "ALTER … DROP ลบคอลัมน์ / constraint"
    elif PLSQL_START.match(s):
        r["kind"] = "plsql"; r["why"] = "บล็อก PL/SQL / เรียก procedure (อาจเขียนข้อมูล)"
    else:
        r["kind"] = "ddl"; r["why"] = "ไม่รู้จักชนิดคำสั่ง — ถือเป็นคำสั่งแก้โครงสร้าง"
    if r["destructive"] and not r["tables"]:
        r["tables"] = ["?"]
    return r


def classify_file(f: Path) -> dict:
    text = f.read_text(encoding="utf-8-sig", errors="replace")
    head = text[:600].lower()
    if re.search(r"blendata|spark", f.name.lower()) or re.search(r"blendata|spark sql", head):
        return {"file": f, "kind": "blendata", "why": "สคริปต์ของ Blendata (Spark SQL) — คนรันบน Blendata", "stmts": []}
    stmts = [classify(s) for s in split_statements(text)]
    run = [s for s in stmts if s["kind"] != "skip"]
    if not run:
        return {"file": f, "kind": "empty", "why": "ไม่มีคำสั่งให้รัน", "stmts": stmts}
    kinds = {s["kind"] for s in run}
    kind = "read" if kinds == {"read"} else "write"
    return {"file": f, "kind": kind, "why": "", "stmts": stmts}


# ---------------------------------------------------------------- แผน (plan) — สิ่งที่จะรัน แสดงให้คนเห็นก่อนเสมอ
def _rel(p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except Exception:
        return Path(p).as_posix()


def collect(target: str, only: str | None = None) -> tuple[str, list[Path], Path]:
    """target = ชื่อ pack (rp01) / โฟลเดอร์ / ไฟล์ .sql → (ชื่อ, ไฟล์, โฟลเดอร์ผล)"""
    p = (ROOT / target) if not Path(target).is_absolute() else Path(target)
    if p.is_file():
        files, name = [p], p.stem
        out = ROOT / "input" / "run_results" / "adhoc"
    else:
        if not p.is_dir():
            packs = sorted(x for x in (ROOT / "run_packs").glob(f"{target}*") if x.is_dir())
            if not packs:
                raise SystemExit(f"[ERROR] ไม่พบ {target} (ไฟล์ .sql / โฟลเดอร์ / run_packs/{target}*)")
            p = packs[-1]
        files, name = sorted(p.glob("*.sql")), p.name
        out = ROOT / "input" / "run_results" / p.name
    if only:
        pre = tuple(x.strip() for x in only.split(",") if x.strip())
        files = [f for f in files if f.name.startswith(pre)]
    if not files:
        raise SystemExit(f"[ERROR] {name}: ไม่มีไฟล์ .sql" + (f" ที่ขึ้นต้นด้วย {only}" if only else ""))
    return name, files, out


def make_plan(target: str, env: str | None = None, only: str | None = None, compile_: bool = False, out_dir: Path | None = None) -> dict:
    db = team_db()
    d, cons = connections()
    env = (env or d).upper()
    name, files, out = collect(target, only)
    out = Path(out_dir) if out_dir else out
    items, todo = [], []
    for f in files:
        c = classify_file(f)
        reason = ""
        if c["kind"] == "blendata":
            reason = c["why"]
        elif c["kind"] == "empty":
            continue
        elif any(s["snp"] and s["kind"] != "read" for s in c["stmts"]):
            reason = "คำสั่งเขียนลงตาราง SNP_* ของ ODI — ระบบไม่รันเสมอ (แก้ผ่าน ODI Studio)"
        elif any(s["snp"] for s in c["stmts"]) and not db.get("read_odi_log"):
            reason = "อ่านตาราง SNP_* ของ ODI — ทีมยังไม่อนุญาตให้ AI อ่าน work repository (init ข้อ 9)"
        elif db.get("ai_access") != "ai":
            reason = "ทีมตั้งให้คนรันทั้งหมด (init ข้อ 9)"
        elif compile_ and c["kind"] != "read":
            reason = "โหมดคอมไพล์รับเฉพาะ SELECT"
        if reason:
            todo.append({"file": _rel(f), "why": reason, "kind": c["kind"]})
            continue
        items.append({"file": _rel(f), "sha": hashlib.sha256(f.read_bytes()).hexdigest(), "kind": c["kind"],
                      "stmts": [{k: s[k] for k in ("sql", "kind", "verb", "destructive", "tables", "why")} for s in c["stmts"] if s["kind"] != "skip"]})
    has_write = any(i["kind"] != "read" for i in items)
    destr = sorted({t for i in items for s in i["stmts"] if s["destructive"] for t in s["tables"]})
    pid = hashlib.sha256(json.dumps([env, [(i["file"], i["sha"]) for i in items], compile_], sort_keys=True).encode()).hexdigest()[:10]
    plan = {"id": pid, "created": dt.datetime.now().isoformat(timespec="seconds"), "target": name, "env": env,
            "env_known": env in cons, "out": _rel(out), "items": items, "todo": todo, "has_write": has_write,
            "destructive": destr, "compile": compile_, "ai_access": db.get("ai_access"), "select_mode": db.get("select_mode"),
            "users": db.get("users")}
    pdir = ROOT / ".dbx" / "plans"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{pid}.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def needs_question(plan: dict) -> bool:
    """ต้องถามคนก่อนรันไหม — คำสั่งเขียนถามเสมอ · SELECT ถามเมื่อ select_mode = ask"""
    if not plan["items"]:
        return False
    return plan["has_write"] or plan.get("select_mode") != "auto"


def human_steps(plan: dict, items: list | None = None) -> list[str]:
    """ขั้นตอนให้คนรันเอง (ทีละไฟล์ · 4 ข้อ: เปิดไฟล์ไหน · เพื่ออะไร · export แบบไหน · วางที่ไหน)"""
    rows = []
    src = items if items is not None else [{"file": i["file"], "kind": i["kind"], "why": ""} for i in plan["items"]] + plan["todo"]
    for n, it in enumerate(src, 1):
        where = "Blendata (Spark SQL)" if it.get("kind") == "blendata" else f"DBeaver ที่ต่อ Oracle {plan['env']}"
        is_read = it.get("kind") == "read"
        rows += [f"ไฟล์ที่ {n}: {it['file']}",
                 f"  1) เปิดไฟล์ {it['file']} ใน {where}",
                 f"  2) เพื่อ: {'ดึงข้อมูลมาให้ AI ตรวจ' if is_read else 'สร้าง / แก้ข้อมูลหรือตารางตามสคริปต์'}" + (f" ({it['why']})" if it.get("why") else ""),
                 "  3) " + ("Ctrl+Enter แล้ว export ผลเป็น CSV (UTF-8 มีหัวคอลัมน์)" if is_read else
                            "Execute Script (Alt+X) · จดจำนวนแถว / ข้อความที่ได้"),
                 "  4) " + (f"วางไฟล์ CSV ที่ {plan['out']}/ ชื่อเดียวกับไฟล์ .sql" if is_read else
                            "บอก AI ว่ารันแล้ว (AI จะบันทึก status/DEPLOY_LOG.md และตรวจผลด้วย SELECT ให้)")]
    return rows


def render(plan: dict) -> str:
    L = ["=" * 64, f"  ฐานข้อมูล: {plan['env']}" + ("" if plan["env_known"] else "  (ยังไม่มีค่าการเชื่อมต่อ — workspace.py db-connect)"),
         f"  เป้าหมาย: {plan['target']} · แผน {plan['id']}", "=" * 64]
    if plan["items"]:
        L.append(f"สิ่งที่จะรัน ({len(plan['items'])} ไฟล์):")
        for it in plan["items"]:
            w = sum(1 for s in it["stmts"] if s["kind"] != "read")
            L.append(f"  • {it['file']} — {len(it['stmts'])} คำสั่ง" + (f" (เขียน / แก้โครงสร้าง {w})" if w else " (อ่านอย่างเดียว)"))
            for s in it["stmts"]:
                tag = {"read": "อ่าน", "write": "เขียนข้อมูล", "ddl": "แก้โครงสร้าง", "plsql": "PL/SQL"}.get(s["kind"], s["kind"])
                flag = "  ⚠️ ลบแล้วกู้คืนไม่ได้: " + s["why"] if s["destructive"] else ""
                sql = " ".join(s["sql"].split())
                L.append(f"      [{tag}] {sql[:220]}{' …' if len(sql) > 220 else ''}{flag}")
    if plan["todo"]:
        L.append(f"ระบบไม่รันให้ ({len(plan['todo'])} ไฟล์ — คนทำเอง):")
        for t in plan["todo"]:
            L.append(f"  👤 {t['file']}: {t['why']}")
    if plan["destructive"]:
        L.append(f"⚠️  มีคำสั่งที่ลบแล้วกู้คืนไม่ได้ — ต้องยืนยันด้วยชื่อตาราง: {', '.join(plan['destructive'])}")
    return "\n".join(L)


def question_text(plan: dict) -> str:
    q = [f"❓ ขออนุญาตรันบนฐาน {plan['env']} (แผน {plan['id']})",
         "   1  ให้ AI / ระบบรันเลย   ← แนะนำ",
         "   2  ฉันรันเอง (ระบบบอกขั้นตอนทีละไฟล์)"]
    if plan["destructive"]:
        q.append(f"   ถ้าเลือก 1: ต้องพิมพ์ชื่อตารางยืนยันอีกชั้น — {', '.join(plan['destructive'])}")
    return "\n".join(q)


# ---------------------------------------------------------------- รัน
def _password(kind: str, env: str, interactive: bool) -> str | None:
    var = pw_var(kind, env)
    pw = os.environ.get(var)
    if pw:
        return pw
    if interactive:
        print(f"   ยังไม่มีตัวแปร {var} — พิมพ์รหัสผ่านของ user {'อ่านอย่างเดียว' if kind == 'ro' else 'ที่เขียนได้'} ({env})")
        print("   ตัวอักษรไม่แสดงบนจอ · ใช้ครั้งนี้ครั้งเดียว ไม่เก็บลงไฟล์ · Enter เปล่า = ยกเลิก")
        try:
            return getpass.getpass("   รหัสผ่าน: ") or None
        except (EOFError, KeyboardInterrupt):
            return None
    return None


def _connect(env: str, kind: str, interactive: bool):
    _, cons = connections()
    c = cons.get(env)
    if not c:
        raise SystemExit(f"[ERROR] ยังไม่มีค่าการเชื่อมต่อของ {env} — รัน `python tools/workspace.py db-connect --env {env}` ที่ root ของ workspace")
    single = team_db().get("users") == "single"
    if single:
        kind = "rw"
        user = c.get("user_rw") or c.get("user_ro") or ""
    else:
        user = c.get("user_rw" if kind == "rw" else "user_ro") or ""
    if not user:
        raise SystemExit(f"[ERROR] ยังไม่มี user {'ที่เขียนได้' if kind == 'rw' else 'อ่านอย่างเดียว'} ของ {env} — "
                         f"ขอจาก DBA แล้วรัน `python tools/workspace.py db-connect --env {env}` · ระหว่างนี้เลือก 'ฉันรันเอง'")
    pw = _password(kind, env, interactive)
    if not pw:
        raise SystemExit(f"[ERROR] ไม่มีรหัสผ่าน ({pw_var(kind, env)}) — AI พิมพ์รหัสแทนคนไม่ได้: ให้คนตั้งตัวแปร "
                         f"(Windows: setx {pw_var(kind, env)} \"…\" แล้วปิดเปิด Terminal และ Claude Code ใหม่) "
                         f"หรือให้คนรันคำสั่งเดียวกันเองใน Terminal (ระบบถามรหัสแบบไม่แสดงบนจอ) · ห้ามพิมพ์รหัสในแชท")
    try:
        import oracledb
    except ImportError:
        raise SystemExit("[ERROR] เครื่องนี้ยังไม่มีตัวต่อ Oracle ของ Python — ติดตั้งครั้งเดียว: pip install oracledb (ไม่ต้องลง Oracle Client)")
    try:
        conn = oracledb.connect(user=user, password=pw, dsn=f"{c['host']}:{c.get('port', 1521)}/{c['service']}")
    except Exception as e:
        raise SystemExit(f"[ERROR] ต่อฐาน {env} ไม่ได้: {str(e).splitlines()[0][:200]} — ตรวจ host / port / service / user / รหัสผ่าน")
    conn.autocommit = False
    return conn, user


def _log(line: str, md_row: list[str] | None = None, deploy: list[str] | None = None):
    w = ws_root()
    if is_job() and (ROOT / "status").exists():
        p = ROOT / "status" / "DB_RUN_LOG.md"
        if not p.exists():
            p.write_text("# DB_RUN_LOG — ทุกครั้งที่ระบบ / AI รัน SQL (สร้างโดย dbx.py · ห้ามแก้มือ)\n\n"
                         "| เวลา | ฐาน | แผน | ไฟล์ | ชนิด | ผล | อนุญาตโดย |\n|---|---|---|---|---|---|---|\n", encoding="utf-8")
        if md_row:
            with open(p, "a", encoding="utf-8") as fh:
                fh.write("| " + " | ".join(x.replace("|", "/") for x in md_row) + " |\n")
        if deploy:
            dp = ROOT / "status" / "DEPLOY_LOG.md"
            if not dp.exists():
                dp.write_text("# DEPLOY_LOG — สิ่งที่ทำในระบบจริง (DDL · ตั้งค่า · scenario)\n\n| รายการ | วันที่ | หลักฐาน | โดย | หมายเหตุ |\n|---|---|---|---|---|\n", encoding="utf-8")
            with open(dp, "a", encoding="utf-8") as fh:
                fh.write("| " + " | ".join(x.replace("|", "/") for x in deploy) + " |\n")
    if w:
        (w / "registry").mkdir(parents=True, exist_ok=True)
        with open(w / "registry" / "db_queries.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _who() -> str:
    try:
        import subprocess
        return subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, cwd=str(ROOT), timeout=5).stdout.strip() or "?"
    except Exception:
        return "?"


def deploy_row(it: dict, ts: str, env: str, msg: str, by: str) -> list[str]:
    """แถวของ status/DEPLOY_LOG.md: | รายการ | วันที่ | หลักฐาน | โดย | หมายเหตุ | — รายการขึ้นต้น DDL / DML ให้ /status นับขั้น 05.1"""
    kind = "DDL" if any(s["kind"] == "ddl" for s in it.get("stmts", [])) or it.get("kind") == "ddl" else "DML"
    return [f"{kind} {it['file']}", ts[:10], f"{msg} · status/DB_RUN_LOG.md", by, f"ฐาน {env}"]


def load_plan(pid: str) -> dict:
    p = ROOT / ".dbx" / "plans" / f"{pid}.json"
    if not p.exists():
        raise SystemExit(f"[ERROR] ไม่พบแผน {pid} — สร้างแผนก่อนด้วย --plan แล้วให้คนอนุญาต")
    return json.loads(p.read_text(encoding="utf-8"))


def execute(plan: dict, approved_by: str, confirm: list[str] | None = None, interactive: bool = False,
            read_only_call: bool = False) -> dict:
    """รันตามแผน (ไฟล์ต้องไม่เปลี่ยนหลังแสดงให้คนดู) · คืน {ok, rows, errors}"""
    if plan.get("ai_access") != "ai" or team_db().get("ai_access") != "ai":
        raise SystemExit("[ERROR] ทีมตั้งให้คนรันทั้งหมด (init ข้อ 9) — ระบบไม่รันให้ ดูขั้นตอนให้คนรันด้วย --plan")
    if read_only_call and plan["has_write"]:
        raise SystemExit("[ERROR] แผนนี้มีคำสั่งที่เขียน / แก้โครงสร้าง — ต้องขออนุญาตก่อนแล้วใช้ --execute <แผน>")
    for it in plan["items"]:
        f = ROOT / it["file"]
        if not f.exists() or hashlib.sha256(f.read_bytes()).hexdigest() != it["sha"]:
            raise SystemExit(f"[ERROR] {it['file']} ถูกแก้หลังสร้างแผน {plan['id']} — สร้างแผนใหม่แล้วขออนุญาตใหม่")
    if plan["destructive"]:
        got = {x.strip().upper() for x in (confirm or []) if x.strip()}
        need = set(plan["destructive"])
        if "?" in need:
            raise SystemExit("[ERROR] มีคำสั่งลบที่ระบบอ่านชื่อตารางไม่ออก — ให้คนรันเอง")
        if got != need:
            raise SystemExit(f"[ERROR] ต้องยืนยันชื่อตารางให้ครบและตรง: {', '.join(sorted(need))} (ได้: {', '.join(sorted(got)) or '-'})")
    env = plan["env"]
    out = ROOT / plan["out"]
    out.mkdir(parents=True, exist_ok=True)
    single = team_db().get("users") == "single"
    conns = {}
    res = {"ok": True, "rows": {}, "errors": []}
    who = _who()
    try:
        if single:
            conns["rw"] = _connect(env, "rw", interactive)
        else:
            if any(it["kind"] == "read" for it in plan["items"]):
                conns["ro"] = _connect(env, "ro", interactive)
                conns["ro"][0].cursor().execute("SET TRANSACTION READ ONLY")
            if plan["has_write"]:
                conns["rw"] = _connect(env, "rw", interactive)
        for it in plan["items"]:
            kind = "rw" if (it["kind"] != "read" and "rw" in conns) else ("ro" if "ro" in conns else "rw")
            conn, user = conns[kind]
            cur = conn.cursor()
            t0 = dt.datetime.now()
            try:
                total, last_rows = 0, None
                for s in it["stmts"]:
                    sql = s["sql"]
                    if plan["compile"] and s["kind"] == "read":
                        sql = f"SELECT * FROM ({sql}) WHERE 1 = 0"
                    cur.execute(sql)
                    if s["kind"] == "read":
                        cols = [d[0] for d in cur.description or []]
                        rows = cur.fetchall() if cols else []
                        last_rows = (cols, rows)
                    else:
                        total += max(cur.rowcount or 0, 0)
                if it["kind"] != "read":
                    conn.commit()
                if last_rows is not None and not plan["compile"]:
                    cols, rows = last_rows
                    with open(out / (Path(it["file"]).stem + ".csv"), "w", encoding="utf-8-sig", newline="") as fh:
                        w = csv.writer(fh)
                        w.writerow(cols)
                        for r in rows:
                            w.writerow(["" if v is None else (v.isoformat(sep=" ") if hasattr(v, "isoformat") else v) for v in r])
                if last_rows is not None:
                    msg = ("ผ่าน (คอมไพล์ได้)" if plan["compile"] else f"{len(last_rows[1])} แถว") + (f" · เปลี่ยน {total} แถว" if it["kind"] != "read" else "")
                else:
                    msg = f"สำเร็จ · เปลี่ยน {total} แถว"
                if it["kind"] == "read" and last_rows and not last_rows[1] and not plan["compile"]:
                    msg += " (0 แถว — ไม่นับว่าผ่าน ตรวจเงื่อนไข)"
                res["rows"][it["file"]] = msg
                print(f"  ✅ {it['file']}: {msg} · {(dt.datetime.now() - t0).total_seconds():.1f}s")
                ts = dt.datetime.now().isoformat(timespec="seconds")
                _log(f"{ts} {who} {'WRITE' if it['kind'] != 'read' else 'READ'} {user}@{env} plan={plan['id']} {it['file']} → {msg} approved={approved_by}",
                     [ts, env, plan["id"], it["file"], "เขียน / แก้" if it["kind"] != "read" else "อ่าน", msg, approved_by],
                     deploy_row(it, ts, env, msg, f"AI ({user}) · อนุญาตโดย {approved_by}") if it["kind"] != "read" else None)
            except Exception as e:
                if it["kind"] != "read":
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                m = str(e).splitlines()[0][:200]
                res["ok"] = False
                res["errors"].append((it["file"], m))
                print(f"  ❌ {it['file']}: {m}" + ("  (คำสั่งแก้โครงสร้าง (DDL) commit ทันทีที่รัน — ตรวจสภาพตารางด้วย SELECT)" if any(s["kind"] == "ddl" for s in it["stmts"]) else ""))
                ts = dt.datetime.now().isoformat(timespec="seconds")
                _log(f"{ts} {who} ERROR {user}@{env} plan={plan['id']} {it['file']}: {m}", [ts, env, plan["id"], it["file"], it["kind"], "ERROR: " + m, approved_by])
                if not plan["compile"]:
                    print("  (error ที่ไม่รู้จัก: ส่งข้อความนี้ให้ AI /diagnose — ไม่เดา) · หยุดที่ไฟล์นี้ ไฟล์ถัดไปไม่รัน")
                    break
    finally:
        for conn, _u in conns.values():
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
    if plan["compile"]:
        vp = ROOT / "output" / "verify" / "sql_compile.txt"
        vp.parent.mkdir(parents=True, exist_ok=True)
        vp.write_text("# คอมไพล์ SQL กับฐานจริง (WHERE 1=0) — " + dt.datetime.now().isoformat(timespec="seconds") + "\n" +
                      "\n".join(f"{f}\tOK\t" for f in res["rows"]) + ("\n" if res["rows"] else "") +
                      "\n".join(f"{f}\tERROR\t{m}" for f, m in res["errors"]) + "\n", encoding="utf-8")
    return res


def write_todo(plan: dict):
    out = ROOT / plan["out"]
    out.mkdir(parents=True, exist_ok=True)
    p = out / "_HUMAN_TODO.md"
    if not plan["todo"]:
        return None
    L = [f"# ไฟล์ใน {plan['target']} ที่คนต้องทำเอง ({len(plan['todo'])} ไฟล์)", "", "ทำทีละไฟล์ตามลำดับ · AI จะบอกทีละไฟล์", ""]
    L += human_steps(plan, plan["todo"])
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    return p
