"""ของที่ hook ใช้ร่วมกัน (P2 2026-09-29) — Claude Code ส่ง JSON ของ tool call ทาง stdin"""
import json
import sys
from pathlib import Path

# Windows: pipe ของ hook ใช้ code page ของเครื่อง -> บังคับ UTF-8 ไม่งั้นข้อความภาษาไทยทำ hook พัง
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]


def read_event():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except Exception:
        return {}


def rel_path(ev) -> str:
    """path ของไฟล์ที่ tool จะแก้ แบบ relative กับ root (ใช้ / เสมอ) — '' ถ้าไม่ใช่การแก้ไฟล์"""
    ti = ev.get("tool_input") or {}
    p = ti.get("file_path") or ti.get("notebook_path") or ""
    if not p:
        return ""
    pp = Path(p)
    if not pp.is_absolute():
        pp = Path(ev.get("cwd") or ROOT) / pp
    try:
        return pp.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return pp.as_posix()


def before_after(ev):
    """คืน (ข้อความเดิม, ข้อความหลังแก้) ของไฟล์ — รองรับ Write / Edit / MultiEdit"""
    ti = ev.get("tool_input") or {}
    rp = rel_path(ev)
    f = ROOT / rp
    old = f.read_text(encoding="utf-8", errors="replace") if rp and f.exists() else ""
    tool = ev.get("tool_name", "")
    if tool == "Write":
        return old, ti.get("content", "")
    edits = ti.get("edits") if tool == "MultiEdit" else [ti]
    new = old
    for e in edits or []:
        a, b = e.get("old_string", ""), e.get("new_string", "")
        if not a:
            new = b + new
        elif e.get("replace_all"):
            new = new.replace(a, b)
        else:
            new = new.replace(a, b, 1)
    return old, new


def added_lines(old: str, new: str):
    """บรรทัดที่มีใน new แต่ไม่มีใน old (เทียบแบบ multiset)"""
    from collections import Counter
    c = Counter(old.splitlines())
    out = []
    for l in new.splitlines():
        if c[l] > 0:
            c[l] -= 1
        else:
            out.append(l)
    return out
