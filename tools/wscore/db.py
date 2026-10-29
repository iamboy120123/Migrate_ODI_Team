"""ต่อฐานจาก workspace (init ข้อ 9–10 · update-target · ตรวจก่อน import) — ใช้ตัวรันเดียวกับงาน: kit/job/scripts/runpack/dbx.py

ทุกครั้งถามเป็นเลข: 1 ให้ระบบรันเลย / 2 ฉันรันเอง (ตามกติกาทีม: คำสั่งเขียนถามเสมอ · SELECT ถามเมื่อ select_mode = ask)
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

from . import common as C

_DBX = None


def dbx(root: Path | None = None):
    global _DBX
    if _DBX is None:
        p = C.ROOT / "kit/job/scripts/runpack/dbx.py"
        spec = importlib.util.spec_from_file_location("ws_dbx", p)
        _DBX = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_DBX)
    _DBX.set_root(root or C.ROOT)
    return _DBX


def need_driver() -> bool:
    try:
        import oracledb  # noqa: F401
        return False
    except ImportError:
        return True


def ready() -> tuple[bool, str]:
    d, cons = dbx().connections()
    if not cons:
        return False, "ยังไม่มีค่าการเชื่อมต่อ (shared/db.local.json) — ตั้งใน init ข้อ 9 หรือ `python tools/workspace.py db-connect`"
    if need_driver():
        return False, ("เครื่องนี้ยังไม่มีตัวต่อ Oracle ของ Python (python-oracledb) — ติดตั้งครั้งเดียว: pip install oracledb "
                       "(ไม่ต้องลง Oracle Client) หรือเลือกข้อ 'ติดตั้งตัวต่อ Oracle ให้'")
    return True, ""


def install_driver() -> bool:
    C.info("กำลังติดตั้ง python-oracledb …")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--user", "oracledb"], capture_output=True, text=True)
    if r.returncode != 0:
        C.fail("ติดตั้งไม่สำเร็จ: " + ((r.stderr or r.stdout).strip().splitlines() or ["?"])[-1][:200])
        C.hint("ถ้าเครื่องต่ออินเทอร์เน็ตไม่ได้ / บริษัทบล็อก pip ให้ขอ IT ติดตั้ง หรือเลือกรันเองใน DBeaver")
        return False
    import importlib
    import site
    try:
        sys.path.append(site.getusersitepackages())
    except Exception:
        pass
    importlib.invalidate_caches()
    ok = not need_driver()
    (C.ok if ok else C.warn)("ติดตั้งแล้ว" if ok else "ติดตั้งแล้วแต่ยังโหลดไม่ได้ — ปิด Terminal แล้วรันใหม่")
    return ok


def run(target: Path, purpose: str, out_dir: Path | None = None, env: str | None = None, root: Path | None = None) -> str:
    """แสดงแผน → ถาม (ตามกติกาทีม) → รัน · คืน 'ran' / 'human' / 'error' / 'cancel' · root = โฟลเดอร์งาน (log ลง status/ ของงาน)"""
    X = dbx(root)
    plan = X.make_plan(str(target), env, None, False, out_dir)
    print(X.render(plan))
    if plan["todo"] and not plan["items"]:
        C.info("ระบบไม่รันไฟล์นี้ — ขั้นตอนให้คนรัน:")
        for line in X.human_steps(plan, plan["todo"]):
            print("   " + line)
        return "human"
    if X.needs_question(plan):
        a = C.ask("", f"   ขออนุญาตรันบนฐาน {plan['env']}: {purpose}",
                  options=[("run", "ให้ระบบรันเลย (ตามแผนด้านบนเท่านั้น)"), ("self", "ฉันรันเอง (ระบบบอกขั้นตอนทีละขั้น)")],
                  recommend="run", use='ทุกครั้งก่อนรัน SQL ระบบต้องได้รับอนุญาต (กติกาทีม)', skip='ใช้ค่าแนะนำ (ให้ระบบรัน)', unknown=False, more='ให้ระบบรัน = ต่อฐานแล้วรันเฉพาะคำสั่งในแผนด้านบน บันทึกทุกครั้ง · ฉันรันเอง = ระบบบอกขั้นตอนให้คุณรันใน DBeaver (เปิดไฟล์ไหน · เพื่ออะไร · export แบบไหน · วางที่ไหน) · ดูชื่อฐานในกรอบด้านบนก่อนตอบ')
        if a == "self":
            for line in X.human_steps(plan):
                print("   " + line)
            return "human"
    confirm = []
    for t in plan["destructive"]:
        v = input(f"   ⚠️  พิมพ์ชื่อตาราง {t} เพื่อยืนยันว่าจะลบ / ล้าง (Enter เปล่า = ยกเลิก): ").strip()
        if not v:
            return "cancel"
        confirm.append(v)
    try:
        res = X.execute(plan, f"คนที่ Terminal ({C.git_user() or '?'})", confirm, interactive=C.INTERACTIVE)
    except SystemExit as e:
        C.fail(str(e).replace("[ERROR] ", ""))
        return "error"
    return "ran" if res["ok"] else "error"


def test_connection(env: str | None = None) -> bool:
    tmp = C.REGISTRY / "tmp_db"
    tmp.mkdir(parents=True, exist_ok=True)
    sp = tmp / "ping.sql"
    sp.write_text("SELECT USER AS DB_USER, SYSDATE AS DB_TIME FROM dual\n", encoding="utf-8")
    st = run(sp, "ทดสอบการเชื่อมต่อ (SELECT USER FROM dual)", tmp, env)
    out = tmp / "ping.csv"
    if st == "ran" and out.exists():
        C.ok("ต่อฐานได้ · " + out.read_text(encoding="utf-8-sig").splitlines()[-1])
        return True
    return False


def fetch_columns(owner: str, reason: str = "") -> bool:
    """ดึงคอลัมน์ทั้ง schema จากฐาน → _incoming → ตรวจ / diff / archive"""
    from . import target as T
    ok, why = ready()
    if not ok:
        C.fail(why)
        return False
    sqlp = T.columns_sql(owner)
    tmp = C.REGISTRY / "tmp_db"
    st = run(sqlp, f"ดึงคอลัมน์ของ schema {owner} (SELECT จาก all_tab_columns)", tmp)
    res = tmp / (sqlp.stem + ".csv")
    if st != "ran" or not res.exists():
        return False
    n = max(len(res.read_text(encoding="utf-8-sig").splitlines()) - 1, 0)
    if n == 0:
        res.unlink(missing_ok=True)
        C.warn(f"ได้ 0 แถว — schema {owner} อาจสะกดผิด หรือ user ไม่มีสิทธิ์เห็นตาราง (ให้ DBA grant SELECT)")
        return False
    T.INCOMING.mkdir(parents=True, exist_ok=True)
    dst = T.INCOMING / f"all_tab_columns_{owner or 'schema'}_{C.now_iso()[:10]}.csv"
    shutil.move(str(res), dst)
    C.ok(f"ดึงได้ {n} แถว → {C.rel(dst)}")
    return "columns" in T.intake_incoming(reason or "ดึงคอลัมน์จากฐาน", interactive_reason=not reason)


# ---------------------------------------------------------------- ตั้งค่าการเชื่อมต่อ (init ข้อ 9 · db-connect)
def configure_connection(env: str | None, users: str, old: dict | None = None) -> tuple[str, dict]:
    old = old or {}
    if not env:
        env = C.ask("", "   ฐานข้อมูลนี้เป็น environment ไหน", options=[("DEV", "DEV — ฐานพัฒนา / ทดสอบ"), ("SIT", "SIT — ทดสอบรวม"), ("PROD", "PROD — ฐานจริง")],
                    recommend="DEV", allow_text=True, validate=lambda v: None if C.NAME_RX.match(v) else "ใช้ A-Z 0-9 _ เท่านั้น", use='ชื่อนี้ขึ้นตัวใหญ่ทุกครั้งที่ AI ขออนุญาตรัน เพื่อให้รู้ว่ากำลังจะรันบนฐานไหน', skip='ใช้ค่าแนะนำ (DEV)', more='DEV = ฐานพัฒนา / ทดสอบ (ใส่ mock data ได้) · SIT = ทดสอบรวม · PROD = ฐานจริง (ระวัง: คำสั่งที่เขียนจะแก้ข้อมูลจริง) · พิมพ์ชื่ออื่นได้ (A-Z 0-9 _) · เพิ่มฐานอื่นทีหลัง: python tools/workspace.py db-connect --env SIT').upper()
    if env == "PROD":
        C.warn("PROD = ฐานจริง — AI ยังต้องขออนุญาตทุกครั้ง และคำสั่งที่ลบแล้วกู้คืนไม่ได้ต้องพิมพ์ชื่อตารางยืนยัน · ตรวจ SQL ก่อนตอบ 1 ทุกครั้ง")
    c = {}
    c["host"] = C.ask("", f"   host ของ Oracle {env}", default=old.get("host") or None, example="10.0.0.12 หรือ devdb.company.local", use='ที่อยู่เครื่องฐานข้อมูล (เก็บในเครื่องคุณเท่านั้น ไม่ขึ้น Git)', rec='ดูจาก connection ใน DBeaver (ช่อง Host)', skip='ระบบพักไว้ — ดูค่าจาก DBeaver หรือถาม DBA แล้วรันใหม่', more='ใน DBeaver: คลิกขวา connection ของฐานนี้ → Edit Connection → ช่อง Host · เป็นได้ทั้ง IP (10.0.0.12) หรือชื่อเครื่อง (devdb.company.local)')
    c["port"] = C.ask("", "   port", default=str(old.get("port") or "1521"), validate=lambda v: None if v.isdigit() else "ใส่ตัวเลข", use='port ของฐานข้อมูล', skip='ใช้ค่าแนะนำ', more='Oracle ส่วนใหญ่ใช้ 1521 · ดูได้ใน DBeaver ช่อง Port')
    c["service"] = C.ask("", "   service name", default=old.get("service") or None, example="DEVPDB", use='ชื่อ service ของฐาน (คนละอย่างกับชื่อ schema)', rec='ดูใน DBeaver ช่อง Database / Service name', skip='ระบบพักไว้ — ดูค่าแล้วรันใหม่', more='ใน DBeaver: Edit Connection → ช่อง Database (แบบ Service Name) · ตัวอย่าง DEVPDB, ORCLPDB1')
    if users == "split":
        c["user_ro"] = C.ask("", "   username ที่อ่านอย่างเดียว (ใช้กับ SELECT)", default=old.get("user_ro") or None, example="ODI_RO", use='user ที่ SELECT ได้อย่างเดียว ใช้กับคำสั่งตรวจสอบ (รหัสผ่านไม่ถามที่นี่)', rec='ขอ user read-only จาก DBA', skip='ระบบพักไว้ — ขอ user จาก DBA แล้วรันใหม่', more='รหัสผ่านไม่ถูกเก็บในไฟล์ใด ๆ — ตั้งเป็นตัวแปร ORA_RO_PASSWORD บนเครื่อง (ฐานอื่นเติม _<ENV>) หรือพิมพ์ตอนรันใน Terminal')
        c["user_rw"] = C.ask("", "   username ที่เขียนได้ (ใช้กับ INSERT / DELETE / TRUNCATE / DDL)", default=old.get("user_rw") or None,
                             example="ODI_RW", required=False, use='user ที่ใช้กับคำสั่งเขียน / แก้โครงสร้าง (INSERT · DELETE · TRUNCATE · CREATE · DROP)', rec='ขอ user จาก DBA ที่มีสิทธิ์เฉพาะ schema ของงาน', skip='ยังไม่มี = คำสั่งที่เขียนให้คนรันเองไปก่อน · ได้ user แล้ว: workspace.py db-connect', more='รหัสผ่านตั้งเป็นตัวแปร ORA_RW_PASSWORD บนเครื่อง (ฐานอื่นเติม _<ENV>) · ควรเป็น user ที่เขียนได้เฉพาะ schema ของงาน ไม่ใช่ SYSTEM / DBA')
        if not c["user_rw"]:
            C.warn("ยังไม่มี user ที่เขียนได้ — คำสั่งที่เขียนจะให้คนรันเองไปก่อน · ได้ user แล้ว: python tools/workspace.py db-connect")
    else:
        c["user_rw"] = C.ask("", "   username (ใช้กับทุกคำสั่ง)", default=old.get("user_rw") or None, example="ODI_DEV", use='user เดียวที่ใช้กับทุกคำสั่ง (อ่านและเขียน)', rec='ขอ user จาก DBA ที่มีสิทธิ์เฉพาะ schema ของงาน', skip='ระบบพักไว้ — ขอ user จาก DBA แล้วรันใหม่', more='รหัสผ่านตั้งเป็นตัวแปร ORA_RW_PASSWORD บนเครื่อง (ฐานอื่นเติม _<ENV>) · ควรเป็น user ที่เขียนได้เฉพาะ schema ของงาน ไม่ใช่ SYSTEM / DBA')
        c["user_ro"] = ""
    return env, c


def password_notice(env: str, users: str):
    import os
    X = dbx()
    need = [X.pw_var("rw", env)] if users == "single" else [X.pw_var("ro", env), X.pw_var("rw", env)]
    miss = [v for v in need if not os.environ.get(v)]
    if miss:
        C.warn("AI (Claude Code) พิมพ์รหัสผ่านแทนคนไม่ได้ — ต้องตั้งตัวแปรบนเครื่องก่อน AI จะรันเองได้: " + " · ".join(miss))
        C.hint("ตั้งครั้งเดียวต่อเครื่อง: เปิด PowerShell พิมพ์  setx " + miss[0] + " \"รหัสผ่าน\"  (ทำทีละตัว) แล้วปิดเปิด Terminal และ Claude Code ใหม่ · ห้ามพิมพ์รหัสในแชท")


def offer_test(env: str):
    while True:
        drv = need_driver()
        tc = C.ask("", "   ทดสอบการเชื่อมต่อตอนนี้ไหม", options=([("install", "ติดตั้งตัวต่อ Oracle (pip install oracledb) แล้วทดสอบ")] if drv else []) +
                   [("test", "ทดสอบเลย (SELECT USER FROM dual — อ่านอย่างเดียว)"), ("skip", "ไม่ทดสอบตอนนี้")],
                   recommend="install" if drv else "test", why="รู้ทันทีว่า host / service / user / รหัสผ่านถูก ก่อน AI ต้องใช้จริง", use='ตรวจว่าค่าการเชื่อมต่อและรหัสผ่านใช้ได้จริง ก่อน AI ต้องใช้ตอนทำงาน', skip='ใช้ค่าแนะนำ', unknown=False, more='ทดสอบ = ระบบต่อฐานแล้วรัน SELECT USER FROM dual (อ่านอย่างเดียว ไม่แตะข้อมูล · ถามอนุญาตตามกติกาทีม) · ถ้ายังไม่มีตัวแปรรหัสผ่าน ระบบให้พิมพ์ตอนนั้น (ไม่แสดงบนจอ ไม่เก็บ) · ติดตั้งตัวต่อ = pip install oracledb ครั้งเดียวต่อเครื่อง · ไม่ทดสอบ = ไปต่อได้ แต่ถ้าค่าผิดจะรู้ตอน AI ต่อฐานครั้งแรก')
        if tc == "skip":
            return
        if tc == "install" and not install_driver():
            continue
        if test_connection(env):
            return


def run_db_connect(args):
    """เพิ่ม / แก้การเชื่อมต่อฐาน (เช่น SIT / PROD หรือได้ user ที่เขียนได้แล้ว)"""
    C.require_workspace()
    t = C.team()
    db = t.get("db") or {}
    if db.get("ai_access") != "ai":
        raise C.Stop("ทีมตั้งให้คนรันทั้งหมด (init ข้อ 9) — ถ้าจะให้ AI เข้าฐาน ให้แก้ shared/team.json \"db\".\"ai_access\" เป็น \"ai\" ผ่าน PR ของทีม")
    X = dbx()
    d, cons = X.connections()
    env = (args.env or "").upper() or None
    env, c = configure_connection(env, db.get("users", "split"), cons.get(env or "", {}))
    cons[env] = c
    C.write_json(C.DB_LOCAL, {"default": d if cons.get(d) else env, "connections": cons})
    C.ok(f"บันทึกการเชื่อมต่อ {env} ใน shared/db.local.json (ไม่ขึ้น Git · ไม่มีรหัสผ่าน)")
    password_notice(env, db.get("users", "split"))
    offer_test(env)
