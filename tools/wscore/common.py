"""ของที่ทุกคำสั่งของ workspace.py ใช้ร่วมกัน: path, อ่าน/เขียนไฟล์, การถามทีละข้อ, ค่าของทีม"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WS_VERSION = "2.10.0"
TOOLS = Path(__file__).resolve().parents[1]
ROOT = TOOLS.parent                      # โฟลเดอร์ workspace (repo)
SHARED = ROOT / "shared"
TARGET = SHARED / "target"
KIT = ROOT / "kit"
PROJECTS = ROOT / "projects"
REGISTRY = ROOT / "registry"
TEAM_JSON = SHARED / "team.json"
DB_LOCAL = SHARED / "db.local.json"      # host / port / service / user — ไม่ commit · ไม่มีรหัสผ่าน
WS_MARK = ROOT / "workspace.json"

INTERACTIVE = sys.stdin.isatty() or os.environ.get("WS_INTERACTIVE") == "1"
ASSUME_YES = False                       # --yes จากคนที่สั่งเอง (ไม่ใช้กับคำสั่งต้องห้าม)


class Stop(Exception):
    """หยุดแบบตั้งใจ (blocker) — ข้อความบอกว่าต้องเตรียมอะไร"""


# ---------------------------------------------------------------- output
def today() -> str:
    return _dt.date.today().isoformat()


def now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def ok(m):   print(f"   ✅ {m}")
def warn(m): print(f"   ⚠️  {m}")
def fail(m): print(f"   ❌ {m}")
def info(m): print(f"   {m}")
def hint(m): print(f"   💡 {m}")


def section(t):
    print()
    print(t)
    print("-" * 60)


def rel(p: Path) -> str:
    """path แบบ relative กับ workspace (ไม่พิมพ์ path ของเครื่อง)"""
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(p).name


# ---------------------------------------------------------------- files
def read_text(p: Path, default: str = "") -> str:
    p = Path(p)
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else default


def write_text(p: Path, text: str):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def read_json(p: Path, default=None):
    p = Path(p)
    if not p.exists():
        return {} if default is None else default
    return json.loads(p.read_text(encoding="utf-8-sig") or "{}")


def write_json(p: Path, obj):
    write_text(p, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha_text(p: Path) -> str:
    """sha ของไฟล์แบบไม่สนบรรทัด CRLF/LF (git แปลงบรรทัดตอน checkout บน Windows) — ใช้เทียบไฟล์ kit"""
    b = Path(p).read_bytes()
    if b"\0" not in b[:8000]:
        b = b.replace(b"\r\n", b"\n")
    return hashlib.sha256(b).hexdigest()


def copy_file(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def latin1_ok(s: str) -> bool:
    try:
        s.encode("iso-8859-1")
        return True
    except UnicodeEncodeError:
        return False


NAME_RX = re.compile(r"^[A-Za-z0-9_]+$")


# ---------------------------------------------------------------- team config
def team() -> dict:
    t = read_json(TEAM_JSON)
    t.setdefault("github", {}).setdefault("mode", "a")
    t.setdefault("db", {}).setdefault("ai_access", "human")
    t.setdefault("lock", {}).setdefault("expire_hours", 2)
    t.setdefault("ids", {}).setdefault("base", 90000)
    t["ids"].setdefault("step", 1000)
    t.setdefault("perf", {})
    return t


def save_team(t: dict):
    write_json(TEAM_JSON, t)


def require_workspace():
    if not WS_MARK.exists() or not TEAM_JSON.exists():
        raise Stop("ยังไม่ได้ตั้ง workspace — รัน `python tools/workspace.py init` ที่โฟลเดอร์ workspace ก่อน")


def approvers() -> list[dict]:
    """shared/approvers.txt: บรรทัดละคน `login [email]` · # = comment"""
    out = []
    for l in read_text(SHARED / "approvers.txt").splitlines():
        l = l.split("#", 1)[0].strip()
        if not l:
            continue
        parts = l.split()
        out.append({"login": parts[0].lstrip("@"), "email": parts[1] if len(parts) > 1 else ""})
    return out


# ---------------------------------------------------------------- jobs
def job_dirs() -> list[Path]:
    return sorted(p.parent for p in PROJECTS.glob("*/jobs/*/job.json"))


def job_by_name(name: str) -> Path:
    name = name.strip().strip("/\\")
    p = (ROOT / name)
    if (p / "job.json").exists():
        return p.resolve()
    hits = [d for d in job_dirs() if d.name == name or f"{d.parent.parent.name}/{d.name}" == name.replace("\\", "/")]
    if not hits:
        hits = [d for d in job_dirs() if name.lower() in d.name.lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise Stop(f"ไม่พบงาน '{name}' — ดูรายชื่อด้วย `python tools/workspace.py status`")
    raise Stop(f"ชื่อ '{name}' ตรงหลายงาน: {', '.join(rel(h) for h in hits)} — ระบุให้ชัดขึ้น เช่น projects/<P>/jobs/<job>")


def job_meta(job: Path) -> dict:
    return read_json(job / "job.json")


def save_job_meta(job: Path, meta: dict):
    write_json(job / "job.json", meta)


# ---------------------------------------------------------------- asking (ทีละข้อ)
MODE_KEY = {"ก": "a", "ข": "b", "ค": "c", "a": "a", "b": "b", "c": "c"}

def _unknown_label(required: bool, d: str, skip: str) -> str:
    if not required:
        return "ยังไม่ทราบ — ข้ามไปก่อน"
    if d:
        return f"ยังไม่ทราบ — ใช้ค่าแนะนำ ({d}) ไปก่อน แก้ทีหลังได้"
    return "ยังไม่ทราบ — พักข้อนี้ไว้ (คำตอบที่ตอบแล้วถูกเก็บ รันใหม่ทำต่อจากข้อนี้)"


def ask(n: str, title: str, *, what: str = "", options: list[tuple[str, str]] | None = None,
        recommend: str | None = None, default: str | None = None, example: str = "",
        why: str = "", required: bool = True, validate=None, explain: str = "", paths: bool = False,
        use: str = "", rec: str = "", skip: str = "", more: str = "", unknown: bool = True, allow_text: bool = False) -> str:
    """ถาม 1 ข้อ · ตอบด้วย "เลข" ของตัวเลือกเท่านั้น (1, 2, 3 …) หรือพิมพ์คำตอบเอง (ข้อที่เป็นข้อความ)
    ทุกข้อแสดง: คืออะไร · ใช้ทำอะไร · ตัวเลือกมีเลข · แนะนำข้อไหนเพราะอะไร · ถ้าไม่ตอบ / ยังไม่ทราบ จะเกิดอะไร
    ? = คำอธิบายละเอียด (more) · q = พักไว้
    คืนค่า: key ของตัวเลือก (ค่าภายใน) · ข้อความที่พิมพ์ · "" เมื่อข้าม · "path:<...>" เมื่อวาง path"""
    d = default if default is not None else (recommend or "")
    entries = []                                  # (kind, value, label)
    if options:
        entries += [("opt", k, v) for k, v in options]
        if allow_text:
            entries.append(("type", None, "พิมพ์ใหม่เอง" + (f" (เช่น {example})" if example else "")))
    else:
        entries.append(("type", None, "พิมพ์คำตอบเอง" + (f" (เช่น {example})" if example else "")))
        if d:
            entries.append(("default", d, f"ใช้ค่านี้: {d}"))
    if unknown:
        dlab = dict(options or []).get(d, d) if d else d
        entries.append(("unknown", None, _unknown_label(required, dlab, skip)))
    rec_i = next((i for i, e in enumerate(entries, 1) if (e[0] == "opt" and e[1] == recommend) or e[0] == "default"), None)
    if rec_i is None and not options and not required:
        rec_i = next((i for i, e in enumerate(entries, 1) if e[0] == "unknown"), None)
    print()
    print("   " + "─" * 56)
    head = title.strip()
    print(f"[{n}] {head}" if n else f"❓ {head}")
    if what:
        print(f"   คืออะไร     {what}")
    if use:
        print(f"   ใช้ทำอะไร    {use}")
    print("   ตัวเลือก")
    for i, (kind, val, lab) in enumerate(entries, 1):
        print(f"     {i}  {lab}{'   ← แนะนำ' if i == rec_i else ''}")
    if rec_i:
        lab = entries[rec_i - 1][2]
        print(f"   👉 แนะนำ     {rec_i} ({lab}){f' — เพราะ {why}' if why else ''}")
    elif rec:
        print(f"   👉 แนะนำ     {rec}")
    if rec and rec_i:
        print(f"                {rec}")
    sk = skip or ("ข้ามได้" if not required else "ข้อนี้ต้องตอบ")
    if rec_i and sk.startswith(("ใช้ค่าแนะนำ", "กด Enter")):
        rest = sk.split(" ", 1)[1] if sk.startswith("ใช้ค่าแนะนำ ") else ""
        sk = f"กด Enter = เลือก {rec_i} (ค่าแนะนำ)" + (f" {rest}" if rest else "")
    elif rec_i:
        sk = f"กด Enter = เลือก {rec_i} · {sk}"
    print(f"   ถ้าไม่ตอบ    {sk}")
    if example and options and not allow_text:
        print(f"   ตัวอย่าง     {example}")
    if paths:
        print("   ตอบเป็น path ได้  วาง path ของไฟล์ / โฟลเดอร์ แล้วระบบก็อปมาให้ (ต้นฉบับไม่ถูกแตะ)")
    typed_ok = (not options) or allow_text
    hint = f"พิมพ์เลข 1–{len(entries)}" + (" หรือพิมพ์คำตอบได้เลย" if typed_ok else "") + (" หรือวาง path" if paths else "")
    print(f"   วิธีตอบ      {hint} · ? = อธิบายละเอียด · q = พักไว้ก่อน")
    if typed_ok:
        print(f"                (ถ้าคำตอบเป็นตัวเลข 1–{len(entries)} ให้เลือก 1 ก่อนแล้วค่อยพิมพ์)")

    def _more():
        parts = [x for x in (more, explain) if x] or [x for x in (what, use) if x] or ["ข้อนี้ไม่มีคำอธิบายเพิ่ม"]
        print("   ℹ️  อธิบายละเอียด")
        for x in parts:
            print(f"      {x}")
        print(f"      ถ้ายังไม่แน่ใจ: เลือก {rec_i} (ค่าที่แนะนำ)" if rec_i else "      ถ้ายังไม่แน่ใจ: เลือกข้อ 'ยังไม่ทราบ' หรือพิมพ์ q เพื่อพักไว้แล้วถามทีม")

    def _check(v):
        err = validate(v) if validate else None
        if err:
            warn(err)
            return None
        return v

    def _pick(i):
        kind, val, _ = entries[i - 1]
        if kind in ("opt", "default"):
            return val
        if kind == "unknown":
            if not required:
                info("ข้ามไปก่อน" + (f" — {skip}" if skip else ""))
                return ""
            if d:
                info(f"ใช้ {d} ไปก่อน (แก้ทีหลังได้)")
                return d
            raise Stop(f"พักข้อ “{title.strip()}” ไว้ — {skip or 'เตรียมคำตอบแล้วรันคำสั่งเดิมอีกครั้ง ระบบถามต่อจากข้อนี้'}")
        while True:                                                     # kind == "type"
            try:
                v = input("   พิมพ์คำตอบ (Enter = กลับไปเลือกใหม่): ").strip()
            except EOFError:
                v = ""
            if not v:
                return None
            if _check(v) is not None:
                return v

    tries = 0
    while True:
        if not INTERACTIVE:
            if d == "" and required:
                raise Stop(f"ข้อ “{title.strip()}” ต้องตอบ แต่รันแบบไม่โต้ตอบ — ใส่ค่าผ่าน parameter หรือรันใน Terminal")
            print(f"   > {d}  (ค่าตั้งต้น)")
            return d
        try:
            a = input(f"   คำตอบ{f' [Enter = {rec_i}]' if rec_i else ''}: ").strip()
        except EOFError:
            raise Stop("ไม่มีคำตอบจากหน้าจอ (input ปิด) — รันใหม่ใน Terminal")
        if a.lower() == "q":
            raise Stop("พักไว้ตามที่สั่ง — คำตอบที่ตอบแล้วถูกเก็บ รันคำสั่งเดิมอีกครั้งจะทำต่อจากข้อนี้")
        if a == "?":
            _more()
            continue
        if a == "" and rec_i:
            r = _pick(rec_i)
            if r is not None:
                return r
            continue
        if a.isdigit() and 1 <= int(a) <= len(entries):
            r = _pick(int(a))
            if r is not None:
                return r
            continue
        if paths and a:
            pth = Path(a.strip('"').strip("'")).expanduser()
            if pth.exists():
                return "path:" + str(pth.resolve())
        if typed_ok and a:
            if _check(a) is not None:
                return a
        else:
            warn(f"ตอบได้: {hint}")
        tries += 1
        if tries >= 3:
            print(f"   ตอบไม่ตรงรูปแบบ 3 รอบ — ถ้าไม่แน่ใจ พิมพ์ ? ดูคำอธิบาย หรือเลือก {rec_i or len(entries)} · q = พักไว้")
            tries = 0


def pick_numbers(n: int, what: str = " รายการ", example: str = "2,5") -> list[int]:
    """ขั้นย่อยหลังเลือก 'เลือกจากรายการ' — พิมพ์เลขลำดับคั่นด้วย , · คืน index เริ่ม 0 · Enter = ยกเลิก (คืน [])"""
    if not INTERACTIVE:
        return []
    while True:
        try:
            v = input(f"   พิมพ์เลขลำดับของ{what} คั่นด้วย , (เช่น {example}) · Enter = ยกเลิก: ").strip()
        except EOFError:
            return []
        if not v:
            return []
        parts = [x.strip() for x in v.replace(" ", ",").split(",") if x.strip()]
        if parts and all(x.isdigit() and 1 <= int(x) <= n for x in parts):
            return sorted({int(x) - 1 for x in parts})
        warn(f"ใส่ได้เฉพาะเลข 1–{n} คั่นด้วย ,")


def confirm(action: str, where: str = "", *, default_no: bool = False, why: str = "", if_no: str = "") -> bool:
    """ขออนุญาตก่อนทำสิ่งที่เปลี่ยนของข้างนอก (เช่น GitHub) — แสดงคำสั่งจริง · ตอบด้วยเลข 1 / 2"""
    print()
    print("   " + "─" * 56)
    print(f"❓ ขออนุญาต: {action}")
    if where:
        print(f"   คำสั่งจริง   {where}")
    if why:
        print(f"   ทำไปเพื่อ    {why}")
    no_txt = if_no or "ไม่ทำ — ระบบบอกคำสั่งให้คุณรันเองทีหลังได้"
    rec = 2 if default_no else 1
    print("   ตัวเลือก")
    print(f"     1  ทำเลย{'   ← แนะนำ' if rec == 1 else ''}")
    print(f"     2  ไม่ทำ — {no_txt}{'   ← แนะนำ' if rec == 2 else ''}")
    print(f"   👉 แนะนำ     {rec} — {'ตรวจคำสั่งด้านบนก่อน' if default_no else 'เป็นขั้นตอนปกติของงาน คำสั่งด้านบนคือทั้งหมดที่จะทำ'}")
    print(f"   ถ้าไม่ตอบ    กด Enter = เลือก {rec}")
    print("   วิธีตอบ      พิมพ์เลข 1 หรือ 2 · ? = อธิบายละเอียด")
    if ASSUME_YES:
        print("   (--yes จากคนที่สั่ง)")
        return True
    if not INTERACTIVE:
        print("   ไม่ได้รันแบบโต้ตอบ — ไม่ทำ (รันใหม่ใน Terminal หรือใส่ --yes ถ้าคุณเป็นคนสั่งเอง)")
        return False
    while True:
        try:
            a = input(f"   คำตอบ [Enter = {rec}]: ").strip()
        except EOFError:
            a = ""
        if a == "?":
            print("   ℹ️  อธิบายละเอียด")
            print(f"      ระบบจะรันคำสั่งที่แสดงในบรรทัด 'คำสั่งจริง' เท่านั้น ไม่มีอะไรแอบทำเพิ่ม")
            print(f"      {why or ''}")
            print("      AI ห้าม push เข้า main · force-push · ลบ branch / ใบงาน · แก้ตั้งค่า repo เสมอ ไม่ว่าจะตอบอะไร")
            print(f"      ถ้าเลือก 2: {no_txt}")
            continue
        a = a or str(rec)
        if a in ("1", "2"):
            return a == "1"
        warn("ตอบได้: พิมพ์เลข 1 หรือ 2")


# ---------------------------------------------------------------- processes
def run(cmd: list[str], cwd: Path | None = None, check: bool = True, capture: bool = True, env=None) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=capture, text=True, encoding="utf-8",
                       errors="replace", env=env)
    if check and r.returncode != 0:
        raise Stop(f"คำสั่งล้มเหลว: {' '.join(cmd)}\n{(r.stderr or r.stdout or '').strip()[:800]}")
    return r


def git(*args, cwd: Path | None = None, check: bool = True) -> str:
    return run(["git", *args], cwd=cwd, check=check).stdout.strip()


def have(exe: str) -> bool:
    return shutil.which(exe) is not None


def python_exe() -> str:
    return sys.executable or "python"


def powershell_exe() -> str | None:
    for e in ("pwsh", "powershell"):
        if have(e):
            return e
    return None


def git_user() -> str:
    return git("config", "user.name", check=False) or os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"


def copy_into(src: str, dest: Path, exts: tuple = ()) -> int:
    """ก็อป (ไม่ย้าย ไม่แก้ต้นฉบับ) ไฟล์เดียว หรือทุกไฟล์ในโฟลเดอร์ ลง dest · exts ว่าง = ทุกชนิด"""
    import shutil
    s = Path(src)
    dest.mkdir(parents=True, exist_ok=True)
    files = [s] if s.is_file() else [f for f in s.rglob("*") if f.is_file()]
    n = 0
    for f in files:
        if exts and f.suffix.lower() not in exts:
            continue
        to = dest / (f.name if s.is_file() else f.relative_to(s))
        to.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, to)
        n += 1
    (ok if n else warn)(f"ก็อป {n} ไฟล์จาก {s} มาที่ {rel(dest)} (ต้นฉบับไม่ถูกแตะ)" if n else f"ไม่มีไฟล์ที่ใช้ได้ใน {s}")
    return n
