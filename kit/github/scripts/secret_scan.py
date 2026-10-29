"""
secret_scan.py — CI: บรรทัดที่เพิ่มใน PR ต้องไม่มีรหัสผ่าน · connection string · host / IP · ผลรันจริง · กุญแจ

ไม่ผ่านเมื่อ:
  - ไฟล์ต้องห้าม: input/run_results/** · shared/db.local.json · _shared_* · *.pem / *.key / *.p12 / *.pfx / *.jks · .claude/settings.local.json
  - บรรทัดที่เพิ่มมี password= / pwd= · jdbc:oracle:thin:user/pass@ · private key · IPv4 ที่ไม่ใช่ตัวอย่าง (เว้น 0.0.0.0 / 127.0.0.1 / x.x.x.x ในเอกสาร)
ยกเว้น: ORA_RO_PASSWORD (ชื่อตัวแปร) · password: null · <password> · ไฟล์ Smart Export (.xml) บรรทัด <Field> (รหัสที่เข้ารหัสของ ODI — kit ไม่อ่าน)

Usage: python .github/scripts/secret_scan.py --base <sha> --head <sha>
"""
from __future__ import annotations

import argparse
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
BAD_PATH = re.compile(r"(^|/)input/run_results/|(^|/)shared/db\.local\.json$|(^|/)_shared_[^/]+$|\.(pem|key|p12|pfx|jks)$|(^|/)\.claude/settings\.local\.json$", re.I)
SECRET = re.compile(r"(password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"<>{}$,)]{3,}|jdbc:oracle:thin:[^@\s/]+/[^@\s]+@|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bghp_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}", re.I)
OK = re.compile(r"ORA_RO_PASSWORD|<password>|password\s*[:=]\s*(null|none|\"\"|''|<)|\*\*\*", re.I)
IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IP_OK = {"0.0.0.0", "127.0.0.1", "255.255.255.255"}


def git(*a):
    return subprocess.run(["git", *a], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    a = ap.parse_args()
    errs = []
    files = [f for f in git("diff", "--name-only", "--diff-filter=AM", f"{a.base}...{a.head}").splitlines() if f]
    for f in files:
        if BAD_PATH.search(f) and not f.endswith(".gitkeep"):
            errs.append(f"{f}: ไฟล์ต้องห้ามใน Git")
    for f in files:
        if f.lower().endswith((".zip", ".png", ".jpg", ".pptx", ".xlsx", ".pdf")):
            continue
        if f.endswith((".py", ".ps1", ".yml", ".cmd")) and (f.startswith(("tools/", "kit/", ".github/")) or "/scripts/" in f):
            continue  # โค้ดของ kit / เครื่องมือ — Code Owner review (ไม่ใช่ที่เก็บค่า)
        cur = None
        for l in git("diff", "--unified=0", f"{a.base}...{a.head}", "--", f).splitlines():
            if l.startswith("@@"):
                m = re.search(r"\+(\d+)", l)
                cur = int(m.group(1)) if m else None
                continue
            if not l.startswith("+") or l.startswith("+++"):
                continue
            s = l[1:]
            if f.lower().endswith(".xml") and "<Field name=" in s:
                cur = (cur or 0) + 1
                continue
            if SECRET.search(s) and not OK.search(s):
                errs.append(f"{f}:{cur}: อาจเป็นรหัสผ่าน / connection string / token")
            for ip in IP.findall(s):
                parts = [int(x) for x in ip.split(".")]
                if ip in IP_OK or any(p > 255 for p in parts) or re.search(r"version|v\d|\d+\.\d+\.\d+\.\d+-", s, re.I):
                    continue
                errs.append(f"{f}:{cur}: มี IP {ip} — ห้ามใส่ host / IP ในไฟล์ที่ขึ้น Git (ใช้ shared/db.local.json ซึ่งไม่ขึ้น Git)")
                break
            cur = (cur or 0) + 1
    for e in errs:
        print(f"❌ {e}")
    print(f"{'✅' if not errs else '⛔'} secret-scan: {len(files)} ไฟล์ · พบ {len(errs)}")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
