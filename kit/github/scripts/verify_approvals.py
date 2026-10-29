"""
verify_approvals.py — CI (กลไก ③): ทุกบรรทัด ✅ ที่เพิ่มในไฟล์ตัดสินใจ / gate ของ PR ต้องมาจากผู้อนุมัติจริง

ไฟล์ที่ตรวจ: projects/*/jobs/*/status/{OPEN_DECISIONS,GATES,PREFLIGHT_CHECKLIST}.md
บรรทัด ✅ (รูปแบบ `✅ SA <YYYY-MM-DD> @<login>`) ที่เพิ่มใหม่ ผ่านเมื่อ:
  (1) commit ของผู้อนุมัติเอง: ผู้เขียน commit = <login> ∈ shared/approvers.txt และบรรทัดมี @<login> เดียวกัน หรือ
  (2) commit ของ GitHub Action approve-command: มี trailer `Approved-by: @<login> <ลิงก์ comment>` · <login> ∈ approvers · บรรทัดมี @<login>
บรรทัดที่แค่ย้ายที่ (ลบและเพิ่มข้อความเดิมใน commit เดียวกัน) ไม่นับ
ระบุตัวผู้เขียน commit: email ใน approvers.txt หรือ GitHub API (GITHUB_TOKEN) — ไม่มีทั้งสอง = ไม่ผ่าน (ไม่เดา)

Usage: python .github/scripts/verify_approvals.py --base <sha> --head <sha>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TRUSTED = Path(__file__).resolve().parents[2]   # สำเนาจาก base branch (รายชื่อผู้อนุมัติ + สคริปต์ที่ PR แก้ไม่ได้)
ROOT = Path.cwd()                                # working tree ของ PR ที่ตรวจ
FILES = re.compile(r"^projects/[^/]+/jobs/[^/]+/status/(OPEN_DECISIONS|GATES|PREFLIGHT_CHECKLIST)\.md$")
MARK = re.compile(r"✅\s*SA\s*\d{4}-\d{2}-\d{2}")
AT = re.compile(r"@([A-Za-z0-9-]+)")
TRAILER = re.compile(r"^Approved-by:\s*@([A-Za-z0-9-]+)\s+(\S+)", re.M)


def git(*a) -> str:
    return subprocess.run(["git", *a], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def approvers():
    out = {}
    p = TRUSTED / "shared/approvers.txt"
    for l in (p.read_text(encoding="utf-8") if p.exists() else "").splitlines():
        l = l.split("#", 1)[0].strip()
        if l:
            parts = l.split()
            out[parts[0].lstrip("@").lower()] = parts[1].lower() if len(parts) > 1 else ""
    return out


def login_of(sha: str, email: str, appr: dict) -> str | None:
    for lg, em in appr.items():
        if em and em == email.lower():
            return lg
    tok, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if tok and repo:
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{repo}/commits/{sha}",
                                         headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode("utf-8"))
            return ((d.get("author") or {}).get("login") or "").lower() or None
        except Exception:
            return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    a = ap.parse_args()
    appr = approvers()
    if not appr:
        print("❌ ไม่มีรายชื่อใน shared/approvers.txt")
        sys.exit(1)
    errs, okn = [], 0
    for sha in git("rev-list", "--reverse", f"{a.base}..{a.head}").split():
        meta = git("show", "-s", "--format=%ae%x00%an%x00%B", sha).split("\x00")
        email, name, body = (meta + ["", "", ""])[:3]
        files = [f for f in git("show", "--name-only", "--format=", sha).splitlines() if FILES.match(f)]
        if not files:
            continue
        for f in files:
            diff = git("show", "--format=", "--unified=0", sha, "--", f)
            added = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
            removed = {l[1:].strip() for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")}
            for l in added:
                if not MARK.search(l) or l.strip() in removed:
                    continue
                ats = [x.lower() for x in AT.findall(l)]
                bot = name.startswith("github-actions") or email.startswith("41898282+")
                if bot:
                    tr = TRAILER.search(body)
                    who = tr.group(1).lower() if tr else None
                    if not who or who not in appr or who not in ats:
                        errs.append(f"{sha[:8]} {f}: ✅ จาก bot ไม่มี Approved-by ของผู้อนุมัติที่ตรงกับบรรทัด → `{l.strip()[:90]}`")
                        continue
                else:
                    who = login_of(sha, email, appr)
                    if not who:
                        errs.append(f"{sha[:8]} {f}: ระบุผู้เขียน commit ({email}) ไม่ได้ — เพิ่ม email ใน approvers.txt หรือรันใน GitHub Actions")
                        continue
                    if who not in appr:
                        errs.append(f"{sha[:8]} {f}: ✅ ถูกเพิ่มโดย {who} ซึ่งไม่ใช่ผู้อนุมัติ → `{l.strip()[:90]}`")
                        continue
                    if who not in ats:
                        errs.append(f"{sha[:8]} {f}: บรรทัด ✅ ต้องมี @{who} (ผู้อนุมัติที่ commit) → `{l.strip()[:90]}`")
                        continue
                okn += 1
    for e in errs:
        print(f"❌ {e}")
    print(f"{'✅' if not errs else '⛔'} verify-approvals: ✅ ที่ตรวจผ่าน {okn} · ไม่ผ่าน {len(errs)}")
    if errs:
        print("วิธีแก้: ให้ผู้อนุมัติ comment `/approve <Q#|G#.M#|W#> [ตัวเลือก]` ใน PR หรือ commit บรรทัดนั้นจากบัญชีของผู้อนุมัติเอง")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
