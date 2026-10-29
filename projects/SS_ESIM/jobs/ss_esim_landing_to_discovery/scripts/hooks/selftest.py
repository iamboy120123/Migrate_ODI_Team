"""
Self-test ของ hooks (kit K9 2026-09-30) — ยิง event จำลองเข้า hook จริงผ่าน stdin แล้วเช็ก exit code
ใช้โดย verify_all.py V12  ·  รันเดี่ยว: python scripts/hooks/selftest.py

expect 2 = ต้องถูก block · expect 0 = ต้องผ่าน
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

SA = "✅ SA 2026-09-30"


def edit(path, new="x", old="x"):
    return {"tool_name": "Edit", "cwd": str(ROOT), "tool_input": {"file_path": path, "old_string": old, "new_string": new}}


def write(path, content):
    return {"tool_name": "Write", "cwd": str(ROOT), "tool_input": {"file_path": path, "content": content}}


def bash(cmd):
    return {"tool_name": "Bash", "cwd": str(ROOT), "tool_input": {"command": cmd}}


OWNED = [
    ("แก้ PROJ_EXPORT.xml", edit("output/odi_export/PROJ_EXPORT.xml"), 2),
    ("แก้ _guid_map.json", edit("output/odi_export/_guid_map.json"), 2),
    ("แก้ _guid_keys.json", edit("output/odi_export/_guid_keys.json"), 2),
    ("แก้ export_workflow.json", edit("input/sample_test/export_workflow.json"), 2),
    ("แก้ smart_export xml", edit("input/odi_reference/a.xml"), 2),
    ("แก้ input/blendata (ล็อก)", edit("input/blendata/README.md"), 2),
    ("แก้ knowledge/reference (ล็อก)", edit("knowledge/reference/migration-rules.md"), 2),
    ("เขียน knowledge/reference ใหม่ (ล็อก)", write("knowledge/reference/x.md", "x"), 2),
    ("แก้ knowledge/lessons-learned.md (ไม่ล็อก)", edit("knowledge/lessons-learned.md"), 0),
    ("แก้ knowledge/reference (ล็อก)", edit("knowledge/reference/migration-rules.md"), 2),
    ("เขียน knowledge/reference ใหม่ (ล็อก)", write("knowledge/reference/x.md", "x"), 2),
    ("แก้ knowledge/lessons-learned.md (ไม่ล็อก)", edit("knowledge/lessons-learned.md"), 0),
    ("แก้ export_workflow.sample.json (ไม่ล็อก)", edit("input/export_workflow.sample.json"), 0),
    ("ติ๊ก [X] ไม่มี SA", write("status/OPEN_DECISIONS.md", "- [X] Q99 ตัดสินแล้ว\n"), 2),
    ("ติ๊ก [x] มี SA", write("status/OPEN_DECISIONS.md", f"- [x] Q99 ตัดสินแล้ว {SA}\n"), 0),
    ("ติ๊ก GATES [x] ไม่มี SA", write("status/GATES.md", "- [x] G2.M1 ok\n"), 2),
    ("waiver ไม่มี SA", write("status/GATES.md", "| W1 | G2 | x | y | someone | active |\n"), 2),
    ("waiver มี SA+วันที่", write("status/GATES.md", "| W1 | G2 | x | y | SA 2026-09-30 | active |\n"), 0),
    ("PREFLIGHT ✅ ไม่มี SA", write("status/PREFLIGHT_CHECKLIST.md", "| 1 | ✅ | env |\n"), 2),
    ("PREFLIGHT ✅ มี SA+วันที่", write("status/PREFLIGHT_CHECKLIST.md", "| 1 | ✅ SA 2026-09-30 | env |\n"), 0),
    ("ADR → Accepted", write(".design/adr/ADR-099-x.md", "- Status: Accepted\n"), 2),
    ("ADR → Proposed", write(".design/adr/ADR-099-x.md", "- Status: Proposed\n"), 0),
    ("แก้ converted SQL", edit("output/sql/converted/nofile.sql"), 0),
]

BASH = [
    ("redirect ทับ PROJ_EXPORT.xml", bash("echo x > output/odi_export/PROJ_EXPORT.xml"), 2),
    ("redirect แบบ backslash", bash("echo x >> output\\odi_export\\_guid_map.json"), 2),
    ("sed -i _guid_map", bash("sed -i 's/a/b/' output/odi_export/_guid_map.json"), 2),
    ("rm export_workflow.json", bash("rm input/sample_test/export_workflow.json"), 2),
    ("rm ไฟล์ใน input/blendata", bash("rm input/blendata/expected_results.csv"), 2),
    ("mv smart_export", bash("mv input/odi_reference/a.xml /tmp/a.xml"), 2),
    ("cp ทับ PROJ_EXPORT.xml", bash("cp other.xml output/odi_export/PROJ_EXPORT.xml"), 2),
    ("tee _guid_map", bash("echo {} | tee output/odi_export/_guid_map.json"), 2),
    ("PowerShell Set-Content", bash("Set-Content -Path output/odi_export/_guid_map.json -Value '{}'"), 2),
    ("git checkout PROJ_EXPORT", bash("git checkout -- output/odi_export/PROJ_EXPORT.xml"), 2),
    ("python -c write_text", bash("python -c \"from pathlib import Path; Path('output/odi_export/_guid_map.json').write_text('{}')\""), 2),
    ("python -c open(w)", bash("python -c \"open('input/a/export_workflow.json','w').write('x')\""), 2),
    ("cat PROJ_EXPORT (อ่าน)", bash("cat output/odi_export/PROJ_EXPORT.xml"), 0),
    ("grep _guid_map (อ่าน)", bash("grep -n guid output/odi_export/_guid_map.json | head"), 0),
    ("cp จาก smart_export ไปที่อื่น (อ่าน)", bash("cp input/odi_reference/a.xml scratch/a.xml"), 0),
    ("validate_odi_xml (อ่าน)", bash("python scripts/pipeline/validate_odi_xml.py output/odi_export/PROJ_EXPORT.xml --source-check"), 0),
    ("validate redirect ไปที่อื่น", bash("python scripts/pipeline/validate_odi_xml.py output/odi_export/PROJ_EXPORT.xml > scratch/v.txt"), 0),
    ("build_odi_export (generator ทำเอง)", bash("python scripts/pipeline/build_odi_export.py"), 0),
    ("git status", bash("git status"), 0),
    ("ไม่เกี่ยวกับไฟล์ล็อก", bash("echo hi > scratch/x.txt"), 0),
    ("Edit tool ผ่าน guard_bash", edit("README.md"), 0),
]


def run_hook(script, event):
    p = subprocess.run([sys.executable, str(HERE / script)], input=json.dumps(event, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, cwd=str(ROOT), timeout=30)
    return p.returncode, p.stderr.decode("utf-8", "replace").strip()


def settings_check():
    """hook ที่ลงทะเบียนใน settings.json ต้องมีไฟล์จริง และ guard_bash ต้องผูกกับ Bash"""
    out = []
    sp = ROOT / ".claude" / "settings.json"
    try:
        st = json.loads(sp.read_text(encoding="utf-8"))
    except Exception as e:
        return [(False, "settings.json อ่านไม่ได้", str(e))]
    pre = st.get("hooks", {}).get("PreToolUse", [])
    bash_guard = any("Bash" in (h.get("matcher") or "") and any("guard_bash.py" in x.get("command", "") for x in h.get("hooks", [])) for h in pre)
    out.append((bash_guard, "settings.json: PreToolUse(Bash) → guard_bash.py", "" if bash_guard else "ไม่พบใน .claude/settings.json"))
    for ev, groups in st.get("hooks", {}).items():
        for g in groups:
            for h in g.get("hooks", []):
                cmd = h.get("command", "")
                for tok in cmd.split():
                    tok = tok.strip('"\'')
                    if tok.endswith(".py"):
                        # K10: path ต้องอ้าง $CLAUDE_PROJECT_DIR ไม่งั้น hook หาไฟล์ไม่เจอเมื่อ cwd ไม่ใช่ root ของโปรเจกต์
                        anchored = tok.startswith(("$CLAUDE_PROJECT_DIR/", "${CLAUDE_PROJECT_DIR}/"))
                        rel = tok.split("/", 1)[1] if anchored else tok
                        ok = (ROOT / rel).exists()
                        out.append((ok, f"settings.json {ev}: {rel} มีไฟล์", "" if ok else "ไม่พบไฟล์"))
                        out.append((anchored, f"settings.json {ev}: {rel} อ้าง $CLAUDE_PROJECT_DIR",
                                    "" if anchored else "ใช้ path สัมพัทธ์ — hook จะล้มเมื่อ cwd ไม่ใช่ root ของโปรเจกต์"))
    return out


def run_all():
    """คืน list ของ (ok, ชื่อ, รายละเอียด)"""
    res = []
    for script, cases in (("guard_owned_files.py", OWNED), ("guard_bash.py", BASH)):
        for name, ev, expect in cases:
            try:
                code, err = run_hook(script, ev)
            except Exception as e:
                res.append((False, f"{script}: {name}", f"รัน hook ไม่ได้: {e}"))
                continue
            ok = code == expect
            res.append((ok, f"{script}: {name}", "" if ok else f"expect exit {expect} ได้ {code} {err[:120]}"))
    res.extend(settings_check())
    return res


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    rs = run_all()
    for ok, name, detail in rs:
        print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    bad = sum(1 for r in rs if not r[0])
    print(f"[selftest] {len(rs) - bad}/{len(rs)} ผ่าน")
    sys.exit(1 if bad else 0)
