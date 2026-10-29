"""
PreToolUse hook (Bash) — ปิดช่องที่ agent เขียนทับไฟล์ที่ห้ามแก้ผ่าน shell แทน Edit/Write  (K9 2026-09-30)

ไฟล์ที่ป้องกัน = LOCKED เดียวกับ guard_owned_files.py: PROJ_EXPORT.xml, _guid_map.json,
input/**/export_workflow.json, input/odi_reference/*.xml, input/blendata/**

Block (exit 2) เมื่อคำสั่งมีไฟล์เหล่านี้เป็นเป้าหมายของการเขียน / ย้าย / ลบ:
  redirect (> >>), tee, sed -i, mv, rm/del, cp/copy (ปลายทาง), Set-Content/Out-File/..., truncate, dd of=,
  git checkout/restore/reset/clean/rm, และ python/node/perl inline ที่ open(..,'w') / write_text / unlink ฯลฯ
อ่านอย่างเดียว (cat, head, grep, validate_odi_xml.py <xml>) ผ่านตามปกติ
best-effort ไม่ใช่ sandbox — คำสั่งที่ประกอบชื่อไฟล์จากตัวแปรจับไม่ได้ (ชั้นสุดท้ายคือ deny ใน settings.json + git)
"""
import re
import sys

from _common import read_event

LOCK = r"(?:PROJ_EXPORT\.xml|_guid_(?:map|keys)\.json|export_workflow\.json|input/odi_reference(?:/[^\s'\"|;&>]*)?|input/blendata(?:/[^\s'\"|;&>]*)?)"
LOCK_RX = re.compile(LOCK, re.I)
REDIRECT = re.compile(r">>?\s*[\"']?[^\s\"'|;&]*" + LOCK, re.I)
DESTRUCTIVE = re.compile(
    r"(?:^|[\s(])(?:tee|mv|move|ren|rename|rm|del|erase|rd|rmdir|truncate|shred|ln|attrib|chmod|icacls|"
    r"sed\s+-[a-z]*i\w*|perl\s+-[a-z]*i\w*|dd|install|"
    r"set-content|add-content|out-file|clear-content|remove-item|move-item|rename-item|new-item|set-itemproperty)\b", re.I)
COPYLIKE = re.compile(r"(?:^|[\s(])(?:cp|copy|copy-item|xcopy|robocopy)\b", re.I)
GIT_MUT = re.compile(r"\bgit\s+(?:checkout|restore|reset|clean|rm|mv|stash|apply|am|cherry-pick|revert)\b", re.I)
INLINE = re.compile(r"\b(?:python\d?|py|node|perl|ruby|powershell|pwsh)\b[^|;&]*?(?:\s-c\b|\s-e\b|\s-command\b|<<|\s-\s*$)", re.I)
INLINE_WRITE = re.compile(
    r"open\([^)]*[\"'][wax+]|write_text|write_bytes|\.write\(|unlink|os\.remove|shutil\.(?:move|copy|rmtree)|os\.replace|os\.rename|"
    r"writeFile|Set-Content|Out-File|Remove-Item", re.I)


def norm(cmd: str) -> str:
    return cmd.replace("\\", "/")


def segments(cmd: str):
    return [s for s in re.split(r"&&|\|\||[;|\n]", cmd) if s.strip()]


def violation(cmd: str):
    c = norm(cmd)
    if not LOCK_RX.search(c):
        return None
    if REDIRECT.search(c):
        return "redirect (> / >>) ไปยังไฟล์ที่ห้ามแก้"
    if INLINE.search(c) and INLINE_WRITE.search(c):
        return "inline script เขียน/ลบไฟล์ที่ห้ามแก้"
    for seg in segments(c):
        locks = LOCK_RX.findall(seg)
        if not locks:
            continue
        if GIT_MUT.search(seg):
            return "git คำสั่งที่เปลี่ยนไฟล์ที่ห้ามแก้"
        if DESTRUCTIVE.search(seg):
            return "คำสั่งเขียน/ย้าย/ลบ ที่อ้างถึงไฟล์ที่ห้ามแก้"
        if COPYLIKE.search(seg):
            toks = [t for t in re.split(r"\s+", seg.strip()) if t and not t.startswith("-")]
            if toks and LOCK_RX.search(toks[-1]):
                return "copy ทับไฟล์ที่ห้ามแก้"
    return None


def main():
    ev = read_event()
    if ev.get("tool_name") not in ("Bash", "PowerShell"):
        sys.exit(0)
    cmd = (ev.get("tool_input") or {}).get("command", "")
    why = violation(cmd)
    if why:
        sys.stderr.write(
            f"[guard_bash] BLOCKED: {why} (CLAUDE.md §5)\n"
            "ไฟล์ของ generator / ของจริงจากระบบต้นทาง ห้ามแก้ผ่าน shell — แก้ที่ต้นทาง (converted SQL / config / script) แล้ว regenerate\n"
            "ถ้าต้องการอ่าน ใช้ cat/head/grep ได้ตามปกติ\n")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
