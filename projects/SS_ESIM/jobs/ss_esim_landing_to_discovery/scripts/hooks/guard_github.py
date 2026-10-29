"""
PreToolUse hook (Bash / PowerShell) — กลไก ⑤ AI ติดต่อ GitHub ต้องได้รับอนุญาต (workspace 2.9.0)

ชั้นที่ 2 จาก 3 ชั้น (1 = permission ของ Claude Code ใน .claude/settings.json ถามก่อนทุกคำสั่งเขียน ·
3 = branch protection + token จำกัดสิทธิ์บน GitHub)

Block (exit 2) เสมอ ไม่มีโหมดไหนปลดได้:
  push เข้า main / master (รวม `git push` เฉย ๆ ขณะอยู่บน main) · force-push (--force, -f, --force-with-lease, +refspec)
  ลบ branch บน remote (--delete, :ref) · gh repo edit/delete/rename/archive · gh issue delete/transfer · gh label delete
  gh api ที่ DELETE / PUT / PATCH หรือแตะ branch protection · แก้เลขใบงาน
แบบคนทำเอง (คนทำเองทั้งหมด): block ทุกคำสั่ง gh และ git push / fetch / pull — ให้ AI บอกคำสั่งให้คนรันเอง
โหมดของงาน: job.json github_mode (ถ้าตั้ง) > shared/team.json github.mode
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from _common import ROOT, read_event


def ws_root():
    for p in [ROOT, *ROOT.parents]:
        if (p / "workspace.json").exists():
            return p
    return None


def mode() -> str:
    try:
        m = json.loads((ROOT / "job.json").read_text(encoding="utf-8")).get("github_mode")
        if m:
            return m
    except Exception:
        pass
    w = ws_root()
    try:
        return json.loads((w / "shared/team.json").read_text(encoding="utf-8")).get("github", {}).get("mode", "a") if w else "a"
    except Exception:
        return "a"


def current_branch() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(ROOT), capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


SEG = re.compile(r"&&|\|\||[;|\n]")


def check_segment(s: str, m: str):
    t = s.strip()
    low = t.lower()
    is_push = re.search(r"\bgit\b(?:\s+-c\s+\S+)*\s+push\b", low)
    is_gh = re.match(r"^(?:\S*[\\/])?gh(?:\.exe)?\s", low)
    if is_push:
        toks = t.split()
        i = [k for k, x in enumerate(toks) if x == "push"][0]
        rest = toks[i + 1:]
        flags = [x for x in rest if x.startswith("-")]
        args = [x for x in rest if not x.startswith("-")]
        if any(f in ("-f", "--force", "--force-with-lease", "--force-if-includes", "--mirror", "--prune") or f.startswith("--force") for f in flags) or \
                any(re.match(r"^-[a-z]*f", f) for f in flags if not f.startswith("--")):
            return "force-push ห้ามเสมอ"
        if "--delete" in flags or "-d" in flags or any(a.startswith(":") for a in args[1:]):
            return "ลบ branch บน remote ห้ามเสมอ"
        if any(a.startswith("+") for a in args):
            return "force-push (+refspec) ห้ามเสมอ"
        refs = args[1:] if len(args) > 1 else []
        targets = [r.split(":")[-1] for r in refs]
        if any(t in ("HEAD", "@") for t in targets):
            cb = current_branch()
            targets = [cb if t in ("HEAD", "@") else t for t in targets]
        if any(x in ("main", "master", "refs/heads/main", "refs/heads/master", "HEAD:main") for x in targets) or "--all" in flags:
            return "push เข้า main ห้ามเสมอ — ใช้ PR"
        if not refs and current_branch() in ("main", "master"):
            return "ตอนนี้อยู่บน main — push เข้า main ห้ามเสมอ (สลับไป branch ของงานก่อน)"
        if m == "c":
            return "แบบคนทำเอง: AI ไม่ push เอง — บอกคำสั่งให้คนรัน"
        return None
    if is_gh:
        if re.search(r"\bgh\s+repo\s+(edit|delete|rename|archive|unarchive)\b", low) or re.search(r"\bgh\s+(issue|pr)\s+(delete|transfer)\b", low) \
                or re.search(r"\bgh\s+label\s+delete\b", low) or re.search(r"\bgh\s+secret\b|\bgh\s+variable\s+(set|delete)\b|\bgh\s+ruleset\b", low):
            return "เปลี่ยนการตั้งค่า / ลบของบน GitHub ห้ามเสมอ"
        if re.search(r"\bgh\s+api\b", low) and (re.search(r"(-x|--method)\s*(delete|put|patch)\b", low) or "protection" in low):
            return "gh api ที่ลบ / แก้การตั้งค่า ห้ามเสมอ"
        if re.search(r"\bgh\s+issue\s+edit\b", low) and re.search(r"--title\b.*#?\d+|--milestone", low) and "[job]" in low:
            return "แก้ชื่อ / เลขใบงานของงาน ห้ามเสมอ"
        if m == "c":
            return "แบบคนทำเอง: AI ไม่ใช้ gh เอง — บอกคำสั่งให้คนรัน"
        return None
    if m == "c" and re.search(r"\bgit\b(?:\s+-c\s+\S+)*\s+(fetch|pull)\b", low):
        return "แบบคนทำเอง: AI ไม่อ่าน GitHub เอง — บอกคำสั่งให้คนรัน"
    return None


def violation(cmd: str, m: str):
    for s in SEG.split(cmd.replace("\\\n", " ")):
        if s.strip():
            why = check_segment(s, m)
            if why:
                return why
    return None


def main():
    ev = read_event()
    if ev.get("tool_name") not in ("Bash", "PowerShell"):
        sys.exit(0)
    cmd = (ev.get("tool_input") or {}).get("command", "")
    why = violation(cmd, mode())
    if why:
        sys.stderr.write(f"[guard_github] BLOCKED: {why} (กลไก ⑤ · kit/CLAUDE.kit.md)\n"
                         "บอกคนว่าต้องการทำอะไร และให้คำสั่งที่คนรันเองได้ — ห้ามหาทางอ้อม\n")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--test":
        print(violation(" ".join(sys.argv[3:]), sys.argv[2]) or "ALLOW")
    else:
        main()
