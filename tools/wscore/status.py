"""กลไก ④ สถานะ: status (บนจอ · เลือกงาน) และ report (STATUS.md + registry) อ่าน main + ทุก origin/job/* โดยไม่ checkout"""
from __future__ import annotations

import datetime as _dt
import io
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

from . import common as C
from . import gh

JOB_STATUS = C.KIT / "job" / "scripts" / "ws" / "job_status.py"
_TMP = None


def _tmp() -> Path:
    global _TMP
    if _TMP is None:
        _TMP = Path(tempfile.mkdtemp(prefix="ws-status-"))
    return _TMP


def has_remote() -> bool:
    return (C.ROOT / ".git").exists() and bool(C.git("remote", check=False))


def last_fetch() -> str:
    p = C.ROOT / ".git" / "FETCH_HEAD"
    return _dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if p.exists() else "ไม่เคย"


def do_fetch(fetch: bool) -> str:
    """fetch ตามโหมด GitHub (อ่าน) · คืนข้อความบอกความสด"""
    if not has_remote() or not fetch:
        return f"ข้อมูล ณ fetch ล่าสุด {last_fetch()}"
    m = gh.mode()
    if m == "c":
        return f"(แบบคนทำเอง ไม่ fetch เอง — รัน git fetch origin --prune เอง) ข้อมูล ณ fetch ล่าสุด {last_fetch()}"
    if m == "b" and not C.confirm("อ่าน GitHub: git fetch origin --prune (ดึงสถานะ branch ของทุกคน)", "origin", why='ดึงสถานะล่าสุดของงานทุกคนมาแสดง (อ่านอย่างเดียว)', if_no='แสดงสถานะจากข้อมูลเก่าในเครื่อง'):
        return f"ไม่ fetch — ข้อมูล ณ fetch ล่าสุด {last_fetch()}"
    r = C.run(["git", "fetch", "origin", "--prune", "--quiet"], check=False)
    return f"fetch แล้ว {_dt.datetime.now():%Y-%m-%d %H:%M}" if r.returncode == 0 else f"fetch ไม่สำเร็จ ({(r.stderr or '').strip()[:80]}) — ข้อมูล ณ {last_fetch()}"


def _refs() -> list[dict]:
    if not (C.ROOT / ".git").exists():
        return []
    out = C.git("for-each-ref", "--format=%(refname)\t%(committerdate:unix)\t%(authorname)", "refs/remotes/origin", check=False)
    refs = []
    for l in out.splitlines():
        name, ts, who = (l.split("\t") + ["", "", ""])[:3]
        short = name.replace("refs/remotes/", "")
        if short.endswith("/HEAD"):
            continue
        if short in ("origin/main", "origin/master") or short.startswith("origin/job/"):
            refs.append({"ref": short, "time": int(ts or 0), "author": who})
    return refs


def _show(ref: str, path: str):
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=str(C.ROOT), capture_output=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.decode("utf-8-sig"))
    except Exception:
        return None


def remote_jobs(fetch: bool = False) -> list[dict]:
    """job ที่เห็นบน origin/main และ origin/job/* (ใช้ตรวจเลขชน + สถานะทีม)"""
    if fetch:
        do_fetch(True)
    out = []
    for r in _refs():
        m = re.match(r"origin/job/([^/]+)/([^/]+)/", r["ref"] + "/")
        if m:
            paths = [f"projects/{m.group(1)}/jobs/{m.group(2)}"]
        else:
            ls = C.git("ls-tree", "-r", "--name-only", r["ref"], "--", "projects", check=False)
            paths = sorted({l[: -len("/job.json")] for l in ls.splitlines() if re.match(r"^projects/[^/]+/jobs/[^/]+/job\.json$", l)})
        for p in paths:
            meta = _show(r["ref"], f"{p}/job.json")
            if meta is None:
                continue
            cfg = _show(r["ref"], f"{p}/config/config.json") or {}
            out.append({**r, "path": p, "meta": meta, "odi": cfg.get("odi") or {}})
    return out


def _snapshot(ref: str, path: str) -> Path | None:
    dst = _tmp() / re.sub(r"[^\w]+", "_", ref)
    r = subprocess.run(["git", "archive", ref, path], cwd=str(C.ROOT), capture_output=True)
    if r.returncode != 0:
        return None
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
        tf.extractall(dst)
    return dst / path


def job_result(job_dir: Path, pushed: bool = False, table: bool = False):
    script = job_dir / "scripts/ws/job_status.py"
    if not script.exists():
        script = JOB_STATUS
    args = [C.python_exe(), str(script), "--root", str(job_dir)] + (["--pushed"] if pushed else []) + ([] if table else ["--json"])
    r = subprocess.run(args, cwd=str(job_dir), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if table:
        return r.stdout
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"job": job_dir.name, "error": (r.stderr or r.stdout)[-300:]}


def collect(fetch: bool, include_all: bool, mine_only: bool) -> tuple[list[dict], str]:
    fresh = do_fetch(fetch)
    head = C.git("rev-parse", "--abbrev-ref", "HEAD", check=False) if (C.ROOT / ".git").exists() else ""
    me = C.git_user()
    # ลำดับความน่าเชื่อ: ในเครื่องบน branch ของงาน (4) > branch งานบน origin (3, ใหม่สุด) > ในเครื่อง (2) > main (1)
    cands = {}
    for j in C.job_dirs():
        m = C.job_meta(j)
        own = head == m.get("branch")
        cands.setdefault(C.rel(j), []).append((4 if own else 2, 0, {"path": C.rel(j), "meta": m, "dir": j, "pushed": False, "time": None,
                                                                    "source": "ในเครื่อง" + (" (branch ของงาน)" if own else "")}))
    for r in remote_jobs(False):
        is_branch = r["ref"].startswith("origin/job/")
        cands.setdefault(r["path"], []).append((3 if is_branch else 1, r["time"], {"path": r["path"], "meta": r["meta"], "ref": r["ref"], "pushed": True,
                                                                                    "time": r["time"], "source": f"branch {r['ref'][7:]} · ยังไม่ merge" if is_branch else "main"}))
    rows = {}
    for p, cs in cands.items():
        cs.sort(key=lambda x: (x[0], x[1]), reverse=True)
        best = cs[0][2]
        if "ref" in best:
            snap = _snapshot(best["ref"], p)
            if not snap:
                continue
            best["dir"] = snap
        rows[p] = best
    out = []
    for k, v in sorted(rows.items()):
        if v["meta"].get("state") == "released" and not include_all:
            continue
        if mine_only and v["meta"].get("owner") not in (me, "") and not include_all:
            continue
        res = job_result(v["dir"], pushed=v["pushed"])
        v["res"] = res
        if v.get("time"):
            age = (_dt.datetime.now() - _dt.datetime.fromtimestamp(v["time"])).days
            v["stale"] = age > 3 or (age > 2 and _dt.date.today().weekday() not in (0, 1))
        out.append(v)
    return out, fresh


def _line(i: int, v: dict) -> list[str]:
    r = v["res"]
    if "error" in r:
        return [str(i), v["path"].split("/")[-1], "?", "?", "อ่านสถานะไม่ได้: " + r["error"][:40], v["source"]]
    cur = r.get("current")
    blocked = r.get("blocked") or []
    if blocked:
        wait = "⛔ " + blocked[0]["label"] + ": " + blocked[0]["note"][:40]
    elif cur:
        wait = f"{cur['state']} {cur.get('who') or '-'} · {cur['note'][:45]}"
    else:
        wait = "✓ ครบ"
    src = v["source"] + (" · ⚠️ ไม่อัปเดต" if v.get("stale") else "")
    return [str(i), v["path"].split("/")[-1], cur["key"] if cur else "จบ", f"{r['done']}/{r['total']}", wait, src]


def print_rows(rows: list[dict]):
    heads = ["#", "งาน", "ขั้น", "คืบหน้า", "รอใคร / ติด", "ที่มา"]
    data = [_line(i + 1, v) for i, v in enumerate(rows)]
    w = [max(len(str(x)) for x in col) for col in zip(heads, *data)] if data else [len(h) for h in heads]
    w = [min(x, 60) for x in w]
    print("   " + "  ".join(h.ljust(w[k]) for k, h in enumerate(heads)))
    for d in data:
        print("   " + "  ".join(str(x)[:60].ljust(w[k]) for k, x in enumerate(d)))


def run_status(args):
    C.require_workspace()
    if args.job:
        j = C.job_by_name(args.job)
        print(job_result(j, table=True))
        return
    rows, fresh = collect(fetch=not args.no_fetch, include_all=args.all, mine_only=not args.all)
    if not rows:
        C.info("ยังไม่มีงาน" + ("" if args.all else "ของคุณ (ใส่ --all ดูทั้งทีม)") + " — เปิดงานด้วย python tools/workspace.py new-job")
        return
    C.section(f"📊 สถานะ{'ทั้งทีม' if args.all else 'งานของคุณ'} · {len(rows)} งาน · {fresh}")
    print_rows(rows)
    pick = args.pick
    if pick is None and C.INTERACTIVE and len(rows) > 0:
        pick = C.ask("", "ดูงานไหนแบบเต็ม", required=False,
                     options=[(str(i), v_path.split('/')[-1] if (v_path := r['path']) else str(i)) for i, r in enumerate(rows, 1)] + [("", "จบ ไม่ดูเพิ่ม")], recommend="", use='ดูรายละเอียดของงานที่เลือก', skip='จบการแสดงผล', unknown=False, more='เลขอยู่หน้าชื่องานในตารางด้านบน · ดูได้ทุกงาน รวมงานของคนอื่น (อ่านอย่างเดียว)')
    if pick:
        v = rows[int(pick) - 1]
        print()
        print(job_result(v["dir"], pushed=v["pushed"], table=True))
        if v.get("pushed"):
            C.info(f"(สถานะจาก {v['source']} — ดูได้อย่างเดียว · จะทำงานนี้ต้องเปิดแชทที่โฟลเดอร์งานนั้น)")


# ---------------------------------------------------------------- report
def run_report(args):
    C.require_workspace()
    rows, fresh = collect(fetch=not args.no_fetch, include_all=True, mine_only=False)
    L = [f"# STATUS — ทั้งทีม (สร้างโดย workspace.py report · {C.now_iso()} · {fresh})", "",
         "> ไฟล์นี้คำนวณใหม่ทุกครั้งจาก main + ทุก origin/job/* · ห้ามแก้มือ · ไม่ commit", "",
         "| งาน | branch / ที่มา | ขั้น | คืบหน้า | รอใคร | ติดอะไร | SQL ✅/🟡/⛔ | เกรด | Q เปิด |", "|---|---|---|---|---|---|---|---|---|"]
    qwait, lessons, imports = [], [], []
    for v in rows:
        r = v["res"]
        if "error" in r:
            L.append(f"| {v['path']} | {v['source']} | ? | ? | ? | อ่านไม่ได้ | - | - | - |")
            continue
        cur = r.get("current")
        sql = "/".join(str(x) for x in r["sql"]) if r.get("sql") else "–"
        L.append(f"| {v['path'].split('/')[-1]} | {v['source']}{' · ⚠️ ไม่อัปเดต' if v.get('stale') else ''} | {cur['key'] if cur else 'จบ'} | {r['done']}/{r['total']} | "
                 f"{(cur or {}).get('who') or '-'} | {('⛔ ' + r['blocked'][0]['note'][:50]) if r.get('blocked') else ((cur or {}).get('note') or '')[:50]} | {sql} | {r.get('grade') or '–'} | {len(r.get('open_q') or [])} |")
        for q, t in r.get("open_q") or []:
            qwait.append(f"| {v['path'].split('/')[-1]} | {q} | {t[:70]} |")
        lt = C.read_text(Path(v["dir"]) / "knowledge/lessons-learned.md")
        for m in re.finditer(r"^#+\s*(L\d+)[.:\s]+(.*)$", lt, re.M):
            lessons.append((v["path"].split("/")[-1], m.group(1), m.group(2).strip()[:80]))
        for l in C.read_text(Path(v["dir"]) / "status/IMPORT_LOG.md").splitlines():
            if l.startswith("| IMPORT"):
                imports.append(f"{v['path'].split('/')[-1]}," + ",".join(c.strip() for c in l.strip().strip('|').split('|')[1:]))
    L += ["", "## คำถามที่รอผู้อนุมัติ", "", "| งาน | Q | เรื่อง |", "|---|---|---|"] + (qwait or ["| - | - | - |"])
    L += ["", "## บทเรียนล่าสุด (3 ข้อท้ายต่องาน)", ""] + [f"- {j} {k}: {t}" for j, k, t in _last3(lessons)] + ["", "## หมายเหตุ", "",
          "- ⚠️ ไม่อัปเดต = branch ไม่ได้ push เกิน 2 วันทำการ", "- ข้อมูลของ branch อื่นอ่านจาก origin โดยไม่ checkout · ทำงานนั้นต้องเปิดแชทที่โฟลเดอร์งาน"]
    C.write_text(C.ROOT / "STATUS.md", "\n".join(L) + "\n")
    from .jobs import write_registry
    write_registry()
    C.write_text(C.REGISTRY / "import_log.csv", "job,date,by,package,result,after_export,lock\n" + "\n".join(imports) + "\n")
    C.write_text(C.REGISTRY / "lessons.csv", "job,id,title\n" + "\n".join(f"{j},{k},\"{t}\"" for j, k, t in lessons) + "\n")
    C.ok(f"เขียน STATUS.md ({len(rows)} งาน) + registry/ · {fresh}")


def _last3(lessons):
    by = {}
    for j, k, t in lessons:
        by.setdefault(j, []).append((j, k, t))
    out = []
    for j, xs in by.items():
        out += xs[-3:]
    return out
