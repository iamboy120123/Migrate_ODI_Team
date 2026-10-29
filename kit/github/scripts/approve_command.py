"""
approve_command.py — GitHub Action (กลไก ③): ผู้อนุมัติ comment ใน PR แล้วระบบบันทึก ✅ ให้

รูปแบบ comment (บรรทัดละข้อ):
  /approve Q14 B          เลือกตัวเลือก B ของ Q14 ใน status/OPEN_DECISIONS.md
  /approve G2.M1          ติ๊ก manual checklist ใน status/GATES.md
  /approve W1             อนุมัติ waiver W1 ใน Waiver log ของ status/GATES.md
  /approve <job>:Q14 B    ระบุงาน เมื่อ PR แตะหลายงาน
บรรทัดที่ได้: `… ✅ SA <YYYY-MM-DD> @<ผู้อนุมัติ> <ลิงก์ comment>` · commit โดย github-actions พร้อม trailer `Approved-by: @<login> <ลิงก์>`
ผู้ comment ต้องอยู่ใน shared/approvers.txt · Q ที่ติ๊กตัวเลือกอื่นไว้แล้ว = ไม่แก้ (ใช้ /decide ในแชทของงาน)

env: COMMENT_BODY · COMMENTER · COMMENT_URL · BASE_REF (สาขาปลายทางของ PR)
ผลลัพธ์: แก้ไฟล์ใน working tree + เขียน .approve_result.md (ข้อความตอบกลับ) · exit 1 = ไม่มีอะไรถูกบันทึก
"""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TRUSTED = Path(__file__).resolve().parents[2]   # สำเนาจาก base branch (รายชื่อผู้อนุมัติ + สคริปต์ที่ PR แก้ไม่ได้)
ROOT = Path.cwd()                                # working tree ของ PR ที่ตรวจ
CMD = re.compile(r"^/approve\s+(?:([\w-]+):)?(Q\d+|G\d\.M\d+|W\d+)\b(?:\s+([A-Za-z]))?", re.M)


def approvers():
    p = TRUSTED / "shared/approvers.txt"
    return {l.split("#")[0].split()[0].lstrip("@").lower() for l in (p.read_text(encoding="utf-8") if p.exists() else "").splitlines() if l.split("#")[0].strip()}


def changed_jobs(base: str) -> list[Path]:
    out = subprocess.run(["git", "diff", "--name-only", f"origin/{base}...HEAD"], cwd=str(ROOT), capture_output=True, text=True).stdout
    jobs = sorted({"/".join(l.split("/")[:4]) for l in out.splitlines() if re.match(r"^projects/[^/]+/jobs/[^/]+/", l)})
    return [ROOT / j for j in jobs]


def apply_q(p: Path, q: str, choice: str, mark: str):
    t = p.read_text(encoding="utf-8")
    m = re.search(rf"^### {q}\.\s.*?(?=^### Q\d+\.|^## |\Z)", t, re.S | re.M)
    if not m:
        return f"ไม่พบ {q} ใน {p.name}"
    sec = m.group(0)
    if re.search(r"^\s*-\s*\[[xX]\]", sec, re.M):
        return f"{q} มีคำตอบแล้ว — เปลี่ยนคำตอบให้ใช้ /decide {q} ในแชทของงาน (บอกผลกระทบก่อน)"
    if not choice:
        return f"{q} ต้องระบุตัวเลือก เช่น /approve {q} A"
    rx = re.compile(rf"^(\s*-\s*)\[ \](\s*{choice}\))(.*)$", re.M)
    if not rx.search(sec):
        return f"{q} ไม่มีตัวเลือก {choice})"
    sec2 = rx.sub(lambda mm: f"{mm.group(1)}[x]{mm.group(2)}{mm.group(3)} {mark}", sec, count=1)
    p.write_text(t.replace(sec, sec2, 1), encoding="utf-8")
    return None


def apply_g(p: Path, gid: str, mark: str):
    t = p.read_text(encoding="utf-8")
    rx = re.compile(rf"^(\s*-\s*)\[ \](\s*{re.escape(gid)}\b.*)$", re.M)
    if not rx.search(t):
        return f"ไม่พบ {gid} ที่ยังไม่ติ๊กใน {p.name}"
    p.write_text(rx.sub(lambda mm: f"{mm.group(1)}[x]{mm.group(2)} {mark}", t, count=1), encoding="utf-8")
    return None


def apply_w(p: Path, wid: str, mark: str):
    t = p.read_text(encoding="utf-8")
    lines = t.splitlines()
    for i, l in enumerate(lines):
        cells = l.strip().strip("|").split("|")
        if len(cells) >= 6 and cells[0].strip() == wid:
            if "✅" in cells[4]:
                return f"{wid} อนุมัติแล้ว"
            cells[4] = f" {mark} "
            lines[i] = "|" + "|".join(cells) + "|"
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return None
    return f"ไม่พบ waiver {wid} ใน {p.name}"


def main():
    body, who, url = os.environ.get("COMMENT_BODY", ""), os.environ.get("COMMENTER", "").lower(), os.environ.get("COMMENT_URL", "")
    base = os.environ.get("BASE_REF", "main")
    res = []
    if who not in approvers():
        res.append(f"❌ @{who} ไม่อยู่ใน shared/approvers.txt — ไม่บันทึก")
    else:
        jobs = changed_jobs(base)
        mark = f"✅ SA {dt.date.today().isoformat()} @{who} {url}"
        done = 0
        for m in CMD.finditer(body):
            jname, iid, choice = m.group(1), m.group(2), (m.group(3) or "").upper()
            cand = [j for j in jobs if not jname or j.name == jname]
            fname = "OPEN_DECISIONS.md" if iid.startswith("Q") else "GATES.md"
            cand = [j for j in cand if (j / "status" / fname).exists()]
            if len(cand) != 1:
                res.append(f"❌ {iid}: PR นี้แตะ {len(cand)} งานที่มี {fname} — ระบุงาน เช่น /approve <job>:{iid}")
                continue
            p = cand[0] / "status" / fname
            err = apply_q(p, iid, choice, mark) if iid.startswith("Q") else (apply_g(p, iid, mark) if iid.startswith("G") else apply_w(p, iid, mark))
            if err:
                res.append(f"❌ {iid}: {err}")
            else:
                done += 1
                res.append(f"✅ {iid}{' ' + choice if choice else ''} → `{p.relative_to(ROOT).as_posix()}`")
        if done == 0 and not res:
            res.append("❌ ไม่พบคำสั่ง /approve ที่อ่านได้")
    (ROOT / ".approve_result.md").write_text("**approve-command**\n\n" + "\n".join(f"- {r}" for r in res) +
                                             "\n\nเจ้าของงาน: `git pull` เพื่อเอาบรรทัด ✅ มา\n", encoding="utf-8")
    print("\n".join(res))
    sys.exit(0 if any(r.startswith("✅") for r in res) else 1)


if __name__ == "__main__":
    main()
