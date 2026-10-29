"""ติดต่อ GitHub ผ่าน gh CLI ตามกลไก ⑤

โหมด (shared/team.json github.mode):
  a = อ่านได้เอง · เขียนต้องถามทุกครั้ง  (ค่าตั้งต้น)
  b = ถามทุกครั้งทั้งอ่านและเขียน
  c = ไม่ติดต่อ GitHub เลย — บอกคำสั่ง / ขั้นตอนให้คนทำเอง แล้วให้คนพิมพ์ผลกลับ
คำสั่งต้องห้าม (ไม่มีโหมดไหนปลดได้ และโมดูลนี้ไม่มีโค้ดที่ทำสิ่งเหล่านี้):
  push เข้า main · force-push · ลบ branch / ใบงาน · แก้ settings ของ repo · แก้เลขใบงาน
"""
from __future__ import annotations

import json
import re

from . import common as C

JOB_LABEL = "job"
LOCK_LABEL = "odi-lock"
LOCK_TITLE = "ODI_DEV กำลังใช้งาน"
FORBIDDEN = re.compile(r"(\b(delete|transfer|archive|rename)\b|\brepo\s+edit\b|-X\s*(DELETE|PUT)\b|/protection\b|--force)", re.I)


def mode() -> str:
    return C.team().get("github", {}).get("mode", "a")


VALUE_OPTS = {"--body", "--title", "--comment", "--description", "--jq", "--color"}


def _verbs(args: list[str]) -> str:
    """ส่วนที่เป็นคำสั่ง (ไม่รวมข้อความใน --body / --title ฯลฯ) — ใช้ตรวจคำสั่งต้องห้าม"""
    out, skip = [], False
    for x in args:
        if skip:
            skip = False
            continue
        if x in VALUE_OPTS:
            skip = True
            continue
        out.append(x)
    return " ".join(out)


def show(args: list[str]) -> str:
    s = " ".join((x if len(x) < 60 and "\n" not in x else (x.split("\n")[0][:57] + "…")) for x in args)
    return "gh " + s


def _gh(args: list[str]) -> str:
    cmd = ["gh", *args]
    if FORBIDDEN.search(_verbs(args)):
        raise C.Stop(f"คำสั่งต้องห้ามตามกลไก ⑤: gh {' '.join(args)}")
    r = C.run(cmd, check=False)
    if r.returncode != 0:
        raise C.Stop(f"gh ล้มเหลว: gh {' '.join(args)}\n{(r.stderr or r.stdout).strip()[:600]}\n"
                     "ตรวจ `gh auth status` (login ด้วยบัญชีของคุณ · token จำกัดสิทธิ์เฉพาะ repo นี้)")
    return r.stdout


def ready() -> tuple[bool, str]:
    if mode() == "c":
        return False, "แบบคนทำเอง — ทีมตั้งให้คนทำงาน GitHub เอง"
    if not C.have("gh"):
        return False, "ไม่พบ gh (GitHub CLI) — ติดตั้งแล้ว `gh auth login` ครั้งเดียว"
    r = C.run(["gh", "auth", "status"], check=False)
    if r.returncode != 0:
        return False, "gh ยังไม่ได้ login — รัน `gh auth login` ด้วยบัญชีของคุณ"
    return True, ""


def read(desc: str, args: list[str]) -> str | None:
    """อ่าน GitHub · โหมด a อ่านเลย · b ถามก่อน · c คืน None (ผู้เรียกต้องให้คนทำเอง)"""
    m = mode()
    if m == "c":
        C.info(f"(แบบคนทำเอง) ไม่อ่าน GitHub เอง — ถ้าต้องการ ให้รัน: gh {' '.join(args)}")
        return None
    okk, why = ready()
    if not okk:
        C.warn(why)
        return None
    if m == "b" and not C.confirm(f"อ่าน GitHub: {desc}", show(args), why='ดูข้อมูลล่าสุดบน GitHub (ไม่เปลี่ยนอะไร)', if_no='ไม่อ่าน — ใช้ข้อมูลที่มีในเครื่อง หรือรันคำสั่งที่แสดงเอง'):
        C.info(f"ไม่อ่าน — คำสั่งสำหรับทำเอง: gh {' '.join(args)}")
        return None
    return _gh(args)


def write(desc: str, args: list[str], manual_steps: str = "") -> str | None:
    """เขียน GitHub · ทุกโหมดต้องถามก่อน (โหมด c ไม่ทำเลย บอกขั้นตอนแทน)"""
    m = mode()
    if m != "c":
        okk, why = ready()
        if okk and C.confirm(f"เขียน GitHub: {desc}", show(args), why='บันทึกบน GitHub ตามขั้นตอนของงาน', if_no='ไม่ทำ — รันคำสั่งที่แสดงเองบน GitHub ได้'):
            out = _gh(args)
            log_action(desc, args)
            return out
        if not okk:
            C.warn(why)
    C.info("ทำเองได้ด้วยคำสั่งนี้:")
    C.info("   " + show(args))
    if manual_steps:
        C.info(f"หรือบนเว็บ: {manual_steps}")
    return None


def log_action(desc: str, args: list[str]):
    p = C.REGISTRY / "github_actions.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{C.now_iso()}\t{C.git_user()}\t{desc}\tgh {' '.join(args)}\n")


# ---------------------------------------------------------------- helpers
def me() -> str | None:
    out = read("ชื่อบัญชี GitHub ของคุณ", ["api", "user", "--jq", ".login"])
    return out.strip() if out else None


def ensure_labels():
    have = read("label ที่มีอยู่", ["label", "list", "--limit", "200", "--json", "name"])
    names = {x["name"] for x in json.loads(have)} if have else set()
    for name, color, desc in ((JOB_LABEL, "0E8A8A", "1 ใบต่อ 1 งาน migrate — เลขใบงาน = ที่มาของ id_base"),
                              (LOCK_LABEL, "E39B2D", "ใบงานปักหมุด: คนที่ถูก assign = คนที่กำลัง Smart Import เข้า ODI_DEV")):
        if name in names:
            C.ok(f"มี label `{name}` แล้ว")
            continue
        write(f"สร้าง label `{name}`", ["label", "create", name, "--color", color, "--description", desc],
              f"Issues → Labels → New label `{name}`")


def create_issue(title: str, body: str, label: str) -> int | None:
    out = write(f"เปิดใบงาน “{title}” (label {label})", ["issue", "create", "--title", title, "--body", body, "--label", label],
                f"Issues → New issue → ชื่อ “{title}” · ใส่ label `{label}`")
    if not out:
        return None
    m = re.search(r"/issues/(\d+)", out)
    return int(m.group(1)) if m else None


def list_issues(label: str, state: str = "all") -> list[dict] | None:
    out = read(f"รายการใบงาน label {label}", ["issue", "list", "--label", label, "--state", state, "--limit", "500",
                                             "--json", "number,title,state,assignees,updatedAt,url"])
    return json.loads(out) if out else None


def view_issue(n: int) -> dict | None:
    out = read(f"ใบงาน #{n}", ["issue", "view", str(n), "--json", "number,title,state,assignees,comments,url"])
    return json.loads(out) if out else None


def lock_issue_number() -> int | None:
    t = C.team()
    n = t.get("github", {}).get("lock_issue")
    if n:
        return int(n)
    found = list_issues(LOCK_LABEL, "open")
    if found:
        n = found[0]["number"]
        t["github"]["lock_issue"] = n
        C.save_team(t)
        return n
    return None


def comment(n: int, body: str, desc: str) -> bool:
    return write(desc, ["issue", "comment", str(n), "--body", body], f"เปิดใบงาน #{n} แล้ว comment: {body}") is not None


def assign_me(n: int) -> bool:
    return write(f"ใส่ชื่อคุณในใบงาน #{n} (assign)", ["issue", "edit", str(n), "--add-assignee", "@me"],
                 f"เปิดใบงาน #{n} → Assignees → เลือกชื่อคุณ") is not None


def unassign(n: int, login: str) -> bool:
    who = "@me" if not login else login
    return write(f"เอาชื่อ {login or 'คุณ'} ออกจากใบงาน #{n}", ["issue", "edit", str(n), "--remove-assignee", who],
                 f"เปิดใบงาน #{n} → Assignees → เอาชื่อออก") is not None


def close_issue(n: int, reason: str) -> bool:
    return write(f"ปิดใบงาน #{n} (not planned) พร้อมเหตุผล", ["issue", "close", str(n), "--reason", "not planned", "--comment", reason],
                 f"เปิดใบงาน #{n} → comment เหตุผล → Close as not planned") is not None
