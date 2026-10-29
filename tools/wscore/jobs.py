"""งาน (job): new-job · confirm-id · import-job · release · new-round · sync-kit · link-shared · slim-job · fix-mtime · kit-promote · set-mode · extract-kit"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import common as C
from . import gh
from . import target as T
from .vendor import extract_workflow as EW

SETUP = C.KIT / "setup_migrate.ps1"
OVERLAY = C.KIT / "job"
PATCHES = C.KIT / "patches"
BASE_MANIFEST = C.KIT / "base_manifest.json"
CREATE_ONLY = {"status/DEPLOY_LOG.md", "status/IMPORT_LOG.md", "config/perf_baseline.json", "status/SQL_REVIEW.md"}
TRACK_DIRS = ("scripts", ".claude/commands", ".claude/agents", ".claude/rules", ".claude/skills", ".claude/workflows", "knowledge/reference")
IMPORT_MARK = "<!-- ws:imports -->"
SLIM_MARK = "<!-- ws:slim -->"


# ---------------------------------------------------------------- helpers
def odi_code(job: str) -> str:
    t = [x for x in job.upper().split("_") if x]
    if len(t) >= 3:
        code = "_".join(t[:2]) + "_" + "".join("2" if x == "TO" else x[0] for x in t[2:])
    else:
        code = "_".join(t)
    return code[:30]


def used_codes() -> dict:
    out = {}
    for j in C.job_dirs():
        cfg = C.read_json(j / "config/config.json")
        o = cfg.get("odi") or {}
        out[j] = (o.get("project_code"), o.get("id_base"))
    return out


def id_base(n: int) -> int:
    t = C.team()
    return int(t["ids"]["base"]) + int(n) * int(t["ids"]["step"])


def run_setup(args: list[str], cwd: Path):
    ps = C.powershell_exe()
    if not ps:
        raise C.Stop("ไม่พบ PowerShell (pwsh / powershell) — ต้องใช้รัน kit/setup_migrate.ps1")
    if not SETUP.exists():
        raise C.Stop("ไม่พบ kit/setup_migrate.ps1 — workspace ไม่ครบ (รัน setup_migrate.ps1 -Mode Workspace ใหม่)")
    cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SETUP), *args]
    env = dict(os.environ, WS_NEW_JOB="1")
    r = subprocess.run(cmd, cwd=str(cwd), text=True, encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0:
        raise C.Stop(f"setup_migrate.ps1 จบด้วย exit {r.returncode} — ดูข้อความด้านบน (งานยังไม่ถูกบันทึกในทะเบียน)")


def tasks_of(export: Path) -> list[dict]:
    try:
        return EW.parse_tasks(json.loads(export.read_text(encoding="utf-8-sig")))
    except Exception:
        return []


KIND_TH = {"aggregate": "เขียนลงตาราง", "export_jdbc": "ส่งข้อมูลออก", "non_sql": "ไม่มี SQL"}


def task_label(x: dict) -> str:
    """ชื่อที่คนอ่านเข้าใจ: ชื่อ task → ตารางปลายทาง (ชนิด) — ไม่แสดงรหัส task แบบ hash"""
    name = x.get("task_name") or x.get("task_id")
    tgt = (x.get("target_table") or "").split(".")[-1]
    kind = KIND_TH.get(x.get("kind", ""), "")
    return name + (f"  → {tgt}" if tgt else "") + (f"  ({kind})" if kind else "")


def print_tasks(tasks: list[dict]):
    print(f"\n   task ของงานนี้ ({len(tasks)} ตัว) · เลขลำดับ · ชื่อ task → ตารางปลายทาง (ชนิด)")
    for i, x in enumerate(tasks, 1):
        print(f"   {i:>3}. {task_label(x)}")


def write_registry():
    """registry/jobs.csv — สร้างใหม่ทุกครั้งจาก job.json (ไม่ commit)"""
    C.REGISTRY.mkdir(parents=True, exist_ok=True)
    rows = ["project,job,owner,issue,issue_unconfirmed,odi_code,id_base,round,branch,status"]
    for j in C.job_dirs():
        m = C.job_meta(j)
        cfg = C.read_json(j / "config/config.json")
        o = cfg.get("odi") or {}
        rows.append(",".join(str(x) for x in (m.get("project", ""), j.name, m.get("owner", ""), m.get("issue", ""), m.get("issue_unconfirmed", False),
                                               o.get("project_code", ""), o.get("id_base", ""), m.get("round", ""), m.get("branch", ""), m.get("state", "active"))))
    C.write_text(C.REGISTRY / "jobs.csv", "\n".join(rows) + "\n")


def check_id_unique(code: str, base: int, me: Path | None = None) -> list[str]:
    probs = []
    for j, (c, b) in used_codes().items():
        if me and j.resolve() == me.resolve():
            continue
        if c and c == code:
            probs.append(f"ODI code {code} ซ้ำกับ {C.rel(j)}")
        if b and int(b) == int(base):
            probs.append(f"id_base {base} ซ้ำกับ {C.rel(j)}")
    return probs


# ---------------------------------------------------------------- new-job
def run_new_job(args):
    C.require_workspace()
    t = C.team()
    if not T.current_smart_export():
        raise C.Stop("ยังไม่มี Smart Export ของกลาง — วางที่ shared/target/_incoming/ แล้วรัน `python tools/workspace.py update-target` ก่อน")
    cur = C.git("rev-parse", "--abbrev-ref", "HEAD", check=False) if (C.ROOT / ".git").exists() else ""
    if cur and cur != "main":
        C.warn(f"ตอนนี้อยู่ branch {cur} — แนะนำเปิดงานจาก main ที่ pull ล่าสุด (git switch main && git pull)")
    C.section("🆕 เปิดงานใหม่ · 3 ข้อ แล้วต่อด้วยวางไฟล์ 5 ข้อ")
    projs = sorted(p.name for p in C.PROJECTS.iterdir() if p.is_dir()) if C.PROJECTS.exists() else []
    opts = [(p, f"{p} (กลุ่มที่มีอยู่แล้ว)") for p in projs] or None
    pa = args.project or C.ask("1/3", "project ไหน", what="กลุ่มงาน (เช่น ระบบต้นทางเดียวกัน) · เลือกกลุ่มที่มี หรือพิมพ์ชื่อใหม่", options=opts, allow_text=True,
                               example="SS_ESIM", validate=lambda v: None if C.NAME_RX.match(v) else "ใช้ A-Z 0-9 _ เท่านั้น", use='จัดกลุ่มโฟลเดอร์ และเป็นส่วนหนึ่งของชื่อ branch / ใบงาน', rec="เลือกกลุ่มเดิมที่ตรง · ถ้าไม่มี เลือก 'พิมพ์ใหม่เอง' แล้วตั้งตามระบบต้นทาง เช่น SS_ESIM", skip='ระบบพักไว้ — ตกลงชื่อกลุ่มกับทีมแล้วรันใหม่', more='project = กลุ่มของงานที่มาจากระบบต้นทางเดียวกัน เช่น งานทั้งหมดของ eSIM อยู่ใน SS_ESIM · ใช้ตัวอักษรอังกฤษ ตัวเลข และ _ เท่านั้น · ชื่อนี้จะเป็นโฟลเดอร์ projects/<ชื่อ>/')
    project = projs[int(pa) - 1] if pa.isdigit() and 0 < int(pa) <= len(projs) else pa.upper()

    def _vjob(v):
        if not C.NAME_RX.match(v) or not C.latin1_ok(v):
            return "ใช้ a-z 0-9 _ เท่านั้น (อักษร ISO-8859-1)"
        if (C.PROJECTS / project / "jobs" / v).exists():
            return f"มีงาน {v} แล้ว — ถ้าจะทำรอบใหม่ใช้ `python tools/workspace.py new-round --job {v}`"
        return None
    job = args.job or C.ask("2/3", "ชื่องาน", what="แนะนำใช้ชื่อ workflow ใน Blendata", example="ss_esim_landing_to_discovery", validate=_vjob, use='เป็นชื่อโฟลเดอร์งาน ชื่อ branch และชื่อใบงานบน GitHub', rec='ใช้ชื่อ workflow ใน Blendata ตรง ๆ (ตัวพิมพ์เล็ก ไม่มีช่องว่าง)', skip='ระบบพักไว้ — ดูชื่อ workflow ในไฟล์ export ของ Blendata แล้วรันใหม่', more='ชื่อ workflow ดูได้จากไฟล์ export_workflow.json (ช่อง name) หรือหน้า Blendata · ใช้ชื่อเดียวกันจะได้หาเจอง่ายว่างานนี้มาจาก workflow ไหน · ใช้ a-z 0-9 _ เท่านั้น')
    if _vjob(job):
        raise C.Stop(_vjob(job))
    jdir = C.PROJECTS / project / "jobs" / job

    # ---- [3/3] ที่มาของเลข
    src = C.MODE_KEY.get(args.id_source or "", "") or C.MODE_KEY[C.ask(
        "3/3", "เลขรหัสงานใน ODI จะเอามาจากไหน",
        what="ทุกงานต้องมี ODI project code และช่วง id_base ที่ไม่ซ้ำ ไม่งั้น import แล้วทับงานคนอื่น · เลขมาจากเลขใบงานบน GitHub ซึ่งไม่มีทางซ้ำ",
        options=[("a", "AI / สคริปต์เปิดใบงานบน GitHub ให้ (แสดงชื่อใบงานก่อน แล้วรอคำว่า ใช่)"),
                 ("b", "คุณเปิดใบงานบนเว็บเองแล้วพิมพ์เลข"),
                 ("c", "คำนวณในเครื่อง ไม่ติดต่อ GitHub (ติดป้าย 'ยังไม่ยืนยัน' · import ไม่ได้จนกว่าจะยืนยัน)")],
        recommend="b" if t["github"]["mode"] == "c" else "a",
        why="ได้เลขจริงทันที และทุกการเขียนยังต้องได้คำว่า ใช่" if t["github"]["mode"] != "c" else "ทีมตั้งแบบคนทำเอง (คนทำ GitHub เอง)", use='เลขนี้กลายเป็นรหัส project ใน ODI และช่วงเลข id ของ object — ถ้าซ้ำกับงานอื่น import แล้วจะทับงานคนอื่น', skip='ใช้ค่าแนะนำ', more='ข้อ 1: ระบบเปิดใบงานบน GitHub ให้ (โชว์ชื่อใบงานก่อนแล้วรอคุณยืนยัน) ได้เลขจริงทันที · ข้อ 2: คุณเปิดใบงานบนเว็บเองแล้วพิมพ์เลข · ข้อ 3: คำนวณเลขในเครื่องไปก่อนโดยไม่ติดต่อ GitHub — ทำงานต่อได้ แต่ import เข้า ODI ไม่ได้จนกว่าจะยืนยันเลขด้วยคำสั่ง confirm-id · เลขใบงานไม่มีทางซ้ำ จึงใช้เป็นที่มาของเลขรหัส')]
    issue, unconfirmed = None, False
    title = f"[job] {project}/{job}"
    if src == "a":
        body = f"งาน migrate Blendata → ODI\n\n- project: {project}\n- job: {job}\n- owner: {C.git_user()}\n- เลขใบงานนี้ = ที่มาของ id_base (90000 + เลข × 1000)"
        issue = gh.create_issue(title, body, gh.JOB_LABEL)
        if not issue:
            C.info("ไม่ได้เปิดใบงาน — เปลี่ยนเป็นแบบเปิดใบงานเอง (เปิดเองแล้วพิมพ์เลข)")
            src = "b"
    if src == "b":
        v = args.issue or C.ask("", f"เลขใบงานที่เปิดไว้ (ชื่อแนะนำ “{title}” · label {gh.JOB_LABEL})", example="12", validate=lambda v: None if v.isdigit() else "ใส่ตัวเลข", use='เลขใบงานคือที่มาของเลขรหัสงานใน ODI (90000 + เลข × 1000)', rec='เปิดใบงานบน github.com ด้วยชื่อตามวงเล็บ แล้วพิมพ์เลขหลัง #', skip="ระบบพักไว้ — เปิดใบงานก่อนแล้วรันใหม่ (หรือรันใหม่แล้วเลือกข้อ 'คำนวณในเครื่อง')", more="github.com → repo ของทีม → Issues → New issue → ตั้งชื่อตามที่แสดง → ใส่ label 'job' → Submit · เลขคือตัวเลขหลัง # ที่หัวใบงาน เช่น #12 → พิมพ์ 12")
        issue = int(v)
        info = gh.view_issue(issue) if gh.mode() == "a" else None
        if info and info.get("title") and job not in info["title"]:
            C.warn(f"ใบงาน #{issue} ชื่อ “{info['title']}” ไม่มีชื่องาน {job} — ตรวจว่าใช่ใบงานของงานนี้")
    if src == "c":
        from .status import remote_jobs
        known = [int(C.job_meta(j).get("issue") or 0) for j in C.job_dirs()]
        known += [int(r["meta"].get("issue") or 0) for r in remote_jobs(fetch=False)]
        known.append(int(t.get("github", {}).get("lock_issue") or 0))
        issue = max(known + [0]) + 1
        unconfirmed = True
        C.warn(f"คำนวณในเครื่องได้ #{issue} — ติดป้าย 'ยังไม่ยืนยัน' · ยืนยันภายหลังด้วย `python tools/workspace.py confirm-id --job {job}`")
    base = id_base(issue)
    code = odi_code(job)
    probs = check_id_unique(code, base)
    if probs:
        if any("ODI code" in p for p in probs):
            code = (code[:26] + f"_{issue}")[:30]
        probs = check_id_unique(code, base)
        if probs:
            raise C.Stop("เลขชนกับงานในเครื่อง: " + " · ".join(probs) + " — ใช้ใบงานใหม่")
    C.ok(f"ใบงาน #{issue}{' (ยังไม่ยืนยัน)' if unconfirmed else ''} → id_base = {base} · ODI code {code}")

    # ---- วางไฟล์ 5 ข้อ (staging ก่อนสร้างโฟลเดอร์งาน)
    stg = C.REGISTRY / "staging" / job
    (stg / "blendata").mkdir(parents=True, exist_ok=True)
    C.section(f"📥 วางไฟล์ของงาน · ที่ {C.rel(stg / 'blendata')}/")
    export = None
    while True:
        cands = sorted(p for p in (stg / "blendata").rglob("*.json"))
        a = "ok" if (cands and not C.INTERACTIVE) else C.ask("1/5", "export ของ Blendata (บังคับ)",
                       what=f"ไฟล์ export_workflow.json ของ workflow นี้จาก Blendata · วางที่ {C.rel(stg / 'blendata')}/",
                       options=[("ok", "วางไฟล์ export แล้ว ตรวจเลย"), ("s", "ยังไม่มีไฟล์ export (หยุดก่อน รันใหม่ได้)")], recommend="ok",
                       example="วาง path ไฟล์ / โฟลเดอร์ เช่น D:\\data\\example_01 (kit ก็อปมาให้ รวมเอกสาร / ข้อมูลเทสในโฟลเดอร์นั้น)", paths=True, use='ระบบอ่านรายการ task และ SQL ทั้งหมดของงานจากไฟล์นี้ — เป็นวัตถุดิบหลัก', skip='ยังไม่สร้างโฟลเดอร์งาน รัน new-job ใหม่ด้วยเลขเดิมเมื่อได้ไฟล์', unknown=False, more='ไฟล์ .json ที่ export จาก Blendata (มีคำว่า airflowExportModels หรือ tasks ข้างใน) · ขอได้จากเจ้าของงานหรือผู้ดูแล Blendata · วางไฟล์ไว้ที่โฟลเดอร์ที่แสดง หรือพิมพ์ path ของไฟล์ / โฟลเดอร์งาน (เช่น D:\\data\\example_01) ระบบก็อปให้รวมเอกสารในโฟลเดอร์นั้นด้วย')
        if a.startswith("path:"):
            C.copy_into(a[5:], stg / "blendata")
            a = "ok"
        if a == "s":
            raise C.Stop(f"รอไฟล์ export — วางที่ {C.rel(stg / 'blendata')}/ แล้วรัน new-job ใหม่ (ใช้เลขเดิม: --issue {issue} --id-source b)")
        cands = sorted(p for p in (stg / "blendata").rglob("*.json"))
        good = [(p, tasks_of(p)) for p in cands]
        good = [(p, ts) for p, ts in good if ts]
        if good:
            export, tasks = good[0]
            C.ok(f"{export.name}: อ่านได้ {len(tasks)} task · SQL {sum(1 for x in tasks if x.get('sql'))}")
            break
        C.fail("ไม่พบ JSON ที่อ่าน task ได้ — ตรวจว่าเป็น export ของ workflow (มี tasks)")
    a = C.ask("2/5", "เอกสาร / ข้อมูลเทส / เฉลย (ไม่บังคับ)", what=f"วางรวมใน {C.rel(stg / 'blendata')}/ ได้เลย (kit สแกนและจัดประเภทเอง)",
              options=[("ok", "วางไฟล์เสริมแล้ว ตรวจเลย"), ("s", "ไม่มีไฟล์เสริม ข้ามไปก่อน")], recommend="ok", why="ข้าม = ต้องถามธุรกิจเพิ่ม และเทียบผลอัตโนมัติไม่ได้", required=False,
              example="วาง path ไฟล์ / โฟลเดอร์ เช่น D:\\data\\example_01\\docs", paths=True, use='เอกสารช่วยให้ AI เข้าใจเงื่อนไขธุรกิจ · ข้อมูลเทสกับเฉลยใช้เทียบผลอัตโนมัติ', skip='ต้องตอบคำถามธุรกิจเพิ่มตอน /intake และเทียบผลอัตโนมัติไม่ได้ (ยังสร้างแพ็กเกจได้)', unknown=False, more='ที่รับ: เอกสาร (.md .txt .docx .pdf) · ข้อมูลเทส (.csv .txt) · เฉลยผลที่ถูก (expected_results.csv) · สคริปต์ seed (.sql — ระบบไม่รัน คนรันเอง) · วางรวมในโฟลเดอร์เดียวได้ ระบบจัดประเภทเอง') or "s"
    if a.startswith("path:"):
        C.copy_into(a[5:], stg / "blendata")
    ids = [x["task_id"] for x in tasks]
    name_of = {x["task_id"]: (x.get("task_name") or x["task_id"]) for x in tasks}
    print_tasks(tasks)
    ex_pick = C.ask("3/5", "task ที่ตัดออกจาก migration", what="task ที่ไม่ต้องย้ายไป ODI (ดูรายการด้านบน)", required=False,
                    options=[("none", "ไม่ตัด ย้ายทุก task"), ("pick", "มี task ที่ต้องตัด (เลือกจากรายการด้านบน)")], recommend="none", use='task ที่ตัดจะไม่ถูกแปลงเป็น ODI และต้องแจ้งพร้อมเหตุผลในรายงานส่งมอบ', skip='ไม่ตัด task ไหนเลย (ตัดทีหลังได้ตอน /intake)', more="ดูรายการ task ด้านบน (ชื่อ task → ตารางปลายทาง) · ถ้ามี task ที่ไม่ต้องย้าย เช่น ทำที่ระบบต้นทางแล้ว หรือเป็น task แจ้งเตือนของ Blendata ให้เลือก 'มี task ที่ต้องตัด' แล้วพิมพ์เลขลำดับในรายการ เช่น 2,5 · ระบบจะถามเหตุผลทีละ task · ถ้าไม่แน่ใจ ไม่ต้องตัด AI จะทวนอีกครั้งตอน /intake")
    ex_idx = C.pick_numbers(len(tasks), " task ที่จะตัด") if ex_pick == "pick" else []
    ex = ",".join(ids[k] for k in ex_idx)
    if ex_idx:
        C.ok("ตัด: " + " · ".join(name_of[ids[k]] for k in ex_idx))
    excluded = [x.strip() for x in ex.split(",") if x.strip()]
    reasons = {}
    for x in excluded:
        reasons[x] = C.ask("", f"   เหตุผลที่ตัด task “{name_of.get(x, x)}”", example="ไม่อยู่ในขอบเขต ODI (ทำที่ระบบต้นทาง)", use='บันทึกในรายงานส่งมอบ (ทุก task ที่ตัดต้องมีเหตุผล)', rec='เขียนสั้น ๆ ว่าทำไมไม่ย้าย task นี้ เช่น ทำที่ระบบต้นทางแล้ว', skip='ระบบพักไว้ — ตัด task ต้องมีเหตุผลเสมอ', more="เหตุผลนี้จะไปอยู่ในรายงานส่งมอบให้ลูกค้า / SA เห็น ควรบอกว่าใครตัดสินถ้ามี เช่น 'SA ยืนยัน 28/10: ทำที่ระบบต้นทาง'")
    guess = ""
    for x in tasks:
        m = re.search(r"\b(?:from|join)\s+([\w.]*landing[\w.]*)", x.get("sql") or "", re.I)
        if m:
            guess = m.group(1).split(".")[-1]
            break
    land = C.ask("4/5", "Landing table และ task ที่แทนด้วย variable",
                 what="ตารางต้นทางที่ข้อมูลเข้ามาก่อน job รัน · Enter = ค่าที่เดาจาก SQL (ยังไม่ยืนยัน) · - = ข้าม (ข้าม = เอกสารแสดง 'ยังไม่ระบุ' แล้วถามตอน /intake)",
                 default=guess or None, example="tb_landing_ss_esim", required=False, use='ระบบใช้ชื่อตารางนี้เป็นจุดเริ่มของ flow และสร้าง query เช็กข้อมูลต้นทาง', skip="เอกสารจะแสดง 'ยังไม่ระบุ' แล้วถามตอน /intake", more='landing table = ตารางที่ข้อมูลดิบถูกโหลดเข้ามารอ ก่อน job นี้รัน (มักมีคำว่า landing ในชื่อ) · ค่าแนะนำเดาจาก SQL ใน export ยังไม่ได้ยืนยัน ให้เทียบกับเอกสารของงาน')
    land = "" if land == "-" else land
    rp = C.ask("", "   task ที่แทนด้วย ODI variable", what="task ที่แค่คำนวณค่า (เช่น วันที่ของรอบ) แล้วส่งต่อให้ task อื่น", required=False,
               options=[("none", "ไม่มี"), ("pick", "มี (เลือกจากรายการ task ด้านบน)")], recommend="none", use='task พวกนี้จะไม่เป็น step แต่เป็นตัวแปร (variable) ใน ODI', skip='ถือว่าไม่มี (AI เสนอให้อีกครั้งตอน /intake)', more="ตัวอย่าง: task ที่ SELECT วันที่ล่าสุดจากตารางควบคุมแล้วส่งเป็น parameter ให้ task ถัดไป → ใน ODI ทำเป็น variable ที่ refresh ด้วย SQL เดิม · ถ้ามี ให้เลือก 'มี' แล้วพิมพ์เลขลำดับในรายการ task ด้านบน · ถ้าไม่แน่ใจ เลือก 'ไม่มี'")
    rp_idx = C.pick_numbers(len(tasks), " task ที่แทนด้วย variable") if rp == "pick" else []
    repl = ",".join(ids[k] for k in rp_idx if ids[k] not in excluded)
    if rp_idx:
        C.ok("แทนด้วย variable: " + " · ".join(name_of[ids[k]] for k in rp_idx))
    tgt = sorted({(x.get("target_table") or "").split(".")[-1].upper() for x in tasks if x.get("target_table")})
    known = {k[1] for k in T.check_columns(T.COL_FILE)[0].get("tables", {})} if T.COL_FILE.exists() else set()
    newt = [x for x in tgt if known and x not in known]
    if newt:
        C.info("ตารางที่ไม่มีในไฟล์คอลัมน์ของกลาง (= ตารางใหม่): " + ", ".join(newt))
    ready = C.ask("5/5", "ตารางปลายทางของงานนี้พร้อมแล้วไหม", what="ตารางมีอยู่ใน Oracle DEV แล้ว (ไม่ต้องสร้างใหม่)",
                  options=[("y", "ตารางปลายทางมีครบแล้ว"), ("n", "ยังไม่ครบ / มีตารางใหม่ต้องสร้าง (บอกตอน /intake)")], recommend="n" if newt else "y", use='ถ้ายังไม่พร้อม ระบบเตรียมสคริปต์สร้างตาราง (DDL) ให้คนรัน — ระบบไม่สร้างตารางเอง', skip='ใช้ค่าแนะนำ (เดาจากไฟล์คอลัมน์ของทีม)', more="พร้อม = ตารางปลายทางทุกตัวมีอยู่ใน Oracle DEV แล้ว · ยัง = มีตารางใหม่ ต้องให้ DBA / คนรัน DDL ก่อนทดสอบ · ระบบดูจากไฟล์คอลัมน์ของทีม ถ้าตารางไม่อยู่ในไฟล์จะแนะนำ 'ยัง'")

    # ---- สร้างงานด้วย kit
    C.section("🧩 สร้างโฟลเดอร์งานด้วย kit (setup_migrate.ps1 -Mode New)")
    jdir.parent.mkdir(parents=True, exist_ok=True)
    pj = C.PROJECTS / project / "_project"
    if not pj.exists():
        C.write_text(pj / "glossary.md", f"# glossary — project {project}\n\nศัพท์ธุรกิจที่ใช้ร่วมกันทุกงานใน project นี้\n\n| คำ | ความหมาย | แหล่งที่มา |\n|---|---|---|\n")
        C.write_text(pj / "DECISIONS.md", f"# DECISIONS — project {project}\n\nการตัดสินที่ตัดสินครั้งเดียวใช้ทุกงานใน project นี้ (อ้างจาก OPEN_DECISIONS ของแต่ละงาน)\n\n| # | เรื่อง | ตัดสิน | ผู้อนุมัติ / วันที่ | ใช้กับ |\n|---|---|---|---|---|\n")
    tv = t.get("target", {})
    sargs = ["-Mode", "New", "-ProjectDir", str(jdir), "-ProjectName", code, "-NonInteractive", "-ExportJson", str(export)]
    for k, v in (("-LandingTable", land), ("-LogicalSchema", tv.get("logical_schema")), ("-ContextCode", tv.get("context_code")), ("-WorkUser", tv.get("work_user"))):
        if v:
            sargs += [k, v]
    jdir.mkdir(parents=True, exist_ok=True)
    link_shared(jdir)            # วางของกลางก่อน kit สร้างงาน → kit อ่านค่า ODI จาก Smart Export เอง
    run_setup(sargs, C.ROOT)
    if not (jdir / "config/config.json").exists():
        raise C.Stop("kit ไม่ได้สร้าง config/config.json — หยุด")
    # เอกสารเสริม → input/blendata/
    for f in (stg / "blendata").rglob("*"):
        if f.is_file() and f != export:
            C.copy_file(f, jdir / "input/blendata" / f.relative_to(stg / "blendata"))
    # config ของงาน
    cfgp = jdir / "config/config.json"
    cfg = C.read_json(cfgp)
    o = cfg.setdefault("odi", {})
    o.update({"project_code": code, "project_name": code, "folder_name": code, "package_name": f"PKG_{code}"[:30], "id_base": base})
    cfg["ai_mode"] = t.get("ai_mode", cfg.get("ai_mode"))
    cfg["error_handling"] = t.get("error_handling", cfg.get("error_handling"))
    if tv.get("target_prefix") and not cfg.get("target_table_prefix"):
        cfg["target_table_prefix"] = tv["target_prefix"]
    cfg.setdefault("scope", {})["excluded_tasks"] = excluded
    cfg["scope"]["excluded_reason"] = {k: f"{C.git_user()} {C.today()}: {v}" for k, v in reasons.items()}
    C.write_json(cfgp, cfg)
    meta = {
        "project": project, "job": job, "owner": C.git_user(), "created_at": C.today(), "round": "R01",
        "branch": f"job/{project}/{job}/R01", "issue": issue, "issue_unconfirmed": unconfirmed, "id_source": src,
        "odi_code": code, "id_base": base, "files_answered": True, "extras": a == "ok", "landing": land,
        "replaces_pending": [x.strip() for x in repl.split(",") if x.strip()], "target_tables_ready": ready == "y",
        "tables": tgt, "new_tables": newt, "state": "active", "github_mode": None, "db_mode": None,
        "rounds": [{"round": "R01", "reason": "เริ่มงาน", "kind": "initial", "date": C.today()}],
        "target_lock": C.job_meta(jdir).get("target_lock") or {},
    }
    C.save_job_meta(jdir, meta)
    sync_one(jdir, first=True)
    r = C.run([C.python_exe(), "scripts/pipeline/read_smart_export.py", "--apply"], cwd=jdir, check=False)
    if r.returncode == 0:
        C.ok("เติมค่า ODI (repository / version) จาก Smart Export ของกลาง")
    else:
        C.warn("อ่าน Smart Export ของกลางเข้า config ไม่ได้: " + (r.stdout or r.stderr).strip()[-200:])
    shutil.rmtree(stg, ignore_errors=True)
    write_registry()
    C.section("✅ เปิดงานเสร็จ")
    C.info(f"งาน: {C.rel(jdir)} · ODI code {code} · id_base {base}")
    if repl:
        C.info("task ที่แทนด้วย variable (" + ", ".join(name_of.get(x, x) for x in repl.split(",") if x) + ") — AI จะยืนยันกับคุณตอน /intake")
    # ---- branch + push
    if (C.ROOT / ".git").exists():
        br = meta["branch"]
        if C.ask("", f"เปิด branch {br} ให้เลยไหม (git ในเครื่อง ไม่แตะ GitHub)", options=[("y", "เปิด branch ให้เลย + commit โฟลเดอร์งาน"), ("n", "ไม่ต้อง ฉันเปิด branch เอง")], recommend="y", use='branch = สำเนาแยกของงานนี้ ทำงานได้โดยไม่กระทบคนอื่น (ทำในเครื่อง ยังไม่ส่งขึ้น GitHub)', skip='ใช้ค่าแนะนำ (เปิดให้)', unknown=False, more='เปิด = ระบบสร้าง branch ชื่อตามที่แสดงแล้ว commit โฟลเดอร์งานให้ · ทำเอง = คุณต้องรัน git switch -c <ชื่อ branch> ก่อนเริ่มงาน · ทั้งสองแบบยังไม่ส่งอะไรขึ้น GitHub') == "y":
            exists = C.git("rev-parse", "--verify", "-q", f"refs/heads/{br}", check=False)
            C.git("switch", br) if exists else C.git("switch", "-c", br)
            extra = [str(p) for p in (C.KIT / "CLAUDE.job.md", BASE_MANIFEST) if p.exists()]
            C.git("add", "--", str(jdir), str(C.PROJECTS / project / "_project"), *extra)
            C.git("commit", "-m", f"{project}/{job}: new-job (issue #{issue}, id_base {base})", check=False)
            push_branch(br)
    C.info("ต่อไป: เปิด Claude Code ที่โฟลเดอร์งาน แล้วพิมพ์ /next-step")


def push_branch(br: str):
    """push branch งาน (ไม่ใช่ main) — เป็นการเขียน GitHub จึงถามก่อนทุกครั้ง · แบบคนทำเอง บอกคำสั่งให้ทำเอง"""
    if br in ("main", "master"):
        raise C.Stop("ห้าม push เข้า main — ใช้ PR")
    if not C.git("remote", check=False):
        C.info("ยังไม่มี remote — ตั้ง `git remote add origin <url>` แล้ว push ทีหลัง")
        return
    cmd = ["git", "push", "-u", "origin", br]
    if gh.mode() == "c" or not C.confirm(f"push branch {br} ขึ้น origin", " ".join(cmd), why='ส่งงานขึ้น GitHub ให้ทีมเห็นสถานะ (ส่งเฉพาะ branch ของงานนี้ ไม่แตะ main)', if_no='งานอยู่แค่ในเครื่อง — push เองทีหลังได้'):
        C.info("ทำเองด้วยคำสั่ง: " + " ".join(cmd))
        return
    C.run(cmd)
    gh.log_action(f"push {br}", ["(git)", *cmd])
    C.ok(f"push {br} แล้ว")


def run_confirm_id(args):
    C.require_workspace()
    j = C.job_by_name(args.job)
    m = C.job_meta(j)
    if not m.get("issue_unconfirmed"):
        C.ok(f"ใบงาน #{m.get('issue')} ยืนยันแล้ว")
        return
    v = args.issue or C.ask("", "เลขใบงานจริงบน GitHub ของงานนี้", example="15", validate=lambda v: None if v.isdigit() else "ใส่ตัวเลข", use='ยืนยันเลขที่ใช้คำนวณรหัสงาน ODI — ต้องยืนยันก่อน import', rec='เปิดใบงานบน github.com แล้วพิมพ์เลขหลัง #', skip='ระบบพักไว้ — เปิดใบงานก่อนแล้วรันใหม่', more='ถ้าเลขจริงไม่ตรงกับที่คำนวณไว้ ระบบจะเปลี่ยนรหัสงาน ODI ให้ตรง (ยังไม่เคย import จึงเปลี่ยนได้ปลอดภัย)')
    n = int(v)
    base = id_base(n)
    probs = check_id_unique(m.get("odi_code") or odi_code(j.name), base, me=j)
    if probs:
        raise C.Stop(" · ".join(probs))
    cfgp = j / "config/config.json"
    cfg = C.read_json(cfgp)
    if (j / "output/odi_export/PROJ_EXPORT.xml").exists() and cfg.get("odi", {}).get("id_base") != base:
        C.warn("มีแพ็กเกจที่ build ด้วยเลขเดิมแล้ว — ต้อง build ใหม่ (/gen-export) หลังเปลี่ยน id_base")
    cfg["odi"]["id_base"] = base
    C.write_json(cfgp, cfg)
    m.update({"issue": n, "issue_unconfirmed": False, "id_base": base})
    C.save_job_meta(j, m)
    write_registry()
    C.ok(f"ยืนยันใบงาน #{n} → id_base {base}")


# ---------------------------------------------------------------- sync-kit / link-shared / slim
def _tracked(job: Path, raw: bool = False) -> dict:
    """sha ของไฟล์ kit ในงาน (ไม่สนบรรทัด CRLF/LF) · raw=False ตัดไฟล์ที่ kit เติมค่าของงาน (templated) ออก"""
    skip = set() if raw else set(C.read_json(BASE_MANIFEST).get("templated", []))
    out = {}
    for d in TRACK_DIRS:
        p = job / d
        if p.exists():
            for f in p.rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts and ".bak-" not in f.name and f.relative_to(job).as_posix() not in skip:
                    out[f.relative_to(job).as_posix()] = C.sha_text(f)
    return out


def expected_files() -> dict:
    """rel -> source Path ที่งานควรมี (overlay ของ workspace + patches ที่ promote แล้ว ตามลำดับ)"""
    out = {}
    for f in OVERLAY.rglob("*"):
        if f.is_file() and "__pycache__" not in f.parts:
            out[f.relative_to(OVERLAY).as_posix()] = f
    if PATCHES.exists():
        for pdir in sorted(d for d in PATCHES.iterdir() if d.is_dir()):
            for f in (pdir / "files").rglob("*") if (pdir / "files").exists() else []:
                if f.is_file():
                    out[f.relative_to(pdir / "files").as_posix()] = f
    return out


def local_edits(job: Path) -> list[str]:
    """ไฟล์ของ kit ในงานที่ถูกแก้ในงาน (ยังไม่ promote) — เทียบ sha กับครั้งที่ sync ล่าสุด"""
    man = C.read_json(job / ".ws_kit.json").get("files", {})
    base = C.read_json(BASE_MANIFEST).get("files", {})
    exp = {k: C.sha_text(v) for k, v in expected_files().items()}
    out = []
    for rel_, sha in man.items():
        f = job / rel_
        if not f.exists() or rel_ in CREATE_ONLY:
            continue
        cur = C.sha_text(f)
        if cur not in (sha, exp.get(rel_), base.get(rel_)):
            out.append(rel_)
    return out


def probe_kit(quiet: bool = False):
    """สร้างงานทดลอง 2 งาน (ชื่อ / ค่า ODI ต่างกัน) จาก kit/setup_migrate.ps1 ใน registry/_probe (ไม่ commit) เพื่อได้
    kit/base_manifest.json (sha ของไฟล์ kit ต้นฉบับ · ไฟล์ที่เติมค่าของงาน = templated ไม่นับ) และ kit/CLAUDE.job.md"""
    sample = C.KIT / "sample" / "export_workflow.sample.json"
    root = C.REGISTRY / "_probe"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    ps = C.powershell_exe()
    if not ps or not SETUP.exists() or not sample.exists():
        raise C.Stop("สร้าง base ของ kit ไม่ได้ (ต้องมี PowerShell + kit/setup_migrate.ps1 + kit/sample/)")
    env = dict(os.environ, WS_NEW_JOB="1")
    se = T.current_smart_export()
    probes = []
    for name, with_se in (("PROBE_A", True), ("PROBE_B", False)):
        d = root / name
        if with_se and se:
            (d / "input/odi_reference").mkdir(parents=True, exist_ok=True)
            shutil.copy2(se, d / "input/odi_reference" / f"_shared_{se.name}")
        r = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SETUP), "-Mode", "New", "-ProjectDir", str(d),
                            "-ProjectName", name, "-NonInteractive", "-ExportJson", str(sample), "-SkipChecks"],
                           cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        if not (d / "CLAUDE.md").exists():
            raise C.Stop("สร้างงานทดลองจาก kit ไม่สำเร็จ:\n" + (r.stdout + r.stderr)[-1500:])
        probes.append(d)
    fa, fb = _tracked(probes[0], raw=True), _tracked(probes[1], raw=True)
    templated = sorted(k for k in fa if fb.get(k) != fa[k])
    files = {k: v for k, v in fa.items() if k not in templated}
    C.write_json(BASE_MANIFEST, {"setup_sha": C.sha256(SETUP), "date": C.today(), "templated": templated, "files": files})
    head, secs = _split_sections(C.read_text(probes[0] / "CLAUDE.md"))
    generic = "".join(x for x in secs if not x.startswith("## 1."))
    C.write_text(C.KIT / "CLAUDE.job.md", "<!-- ส่วนที่เหมือนกันทุกงาน (ย้ายมาจาก CLAUDE.md ของงานโดย slim-job) · แก้ผ่าน PR ของ kit เท่านั้น -->\n\n" + generic)
    shutil.rmtree(root, ignore_errors=True)
    if not quiet:
        C.ok(f"สร้าง kit/base_manifest.json ({len(files)} ไฟล์ · เติมค่าต่องาน {len(templated)}) + kit/CLAUDE.job.md")


def sync_one(job: Path, first: bool = False, force: bool = False):
    edits = [] if first else local_edits(job)
    if edits and not force:
        raise C.Stop(f"{C.rel(job)} มีการแก้ไฟล์ kit ค้างในงาน: {', '.join(edits[:6])} — ส่งเข้า kit ก่อนด้วย "
                     f"`python tools/workspace.py kit-promote --job {job.name}` (หรือ --force เพื่อเขียนทับ โดย backup *.bak ให้)")
    if not BASE_MANIFEST.exists() or not (C.KIT / "CLAUDE.job.md").exists():
        probe_kit()
    stamp = _dt.datetime.now().strftime("%Y%m%d%H%M%S")
    for rel_, src in expected_files().items():
        dst = job / rel_
        if rel_ in CREATE_ONLY and dst.exists():
            continue
        if dst.exists() and force and rel_ in edits:
            shutil.copy2(dst, dst.with_name(dst.name + f".bak-{stamp}"))
        C.copy_file(src, dst)
    patch_settings(job)
    patch_claude_md(job)
    link_shared(job)
    man = _tracked(job)
    for rel_ in CREATE_ONLY:
        man.pop(rel_, None)
    C.write_json(job / ".ws_kit.json", {"workspace_version": C.WS_VERSION, "synced_at": C.now_iso(), "files": man})
    C.ok(f"sync-kit {C.rel(job)}")


def link_shared(job: Path):
    """ก๊อปของกลางเข้า input/ ของงาน (ชื่อขึ้นต้น _shared_ · ไม่ขึ้น Git) + ล็อก sha256 · หลัง G3 ไม่เปลี่ยนรุ่นให้"""
    m = C.job_meta(job)
    lock = m.get("target_lock") or {}
    se = T.current_smart_export()
    items = [("smart_export", se, job / "input/odi_reference"), ("columns", T.COL_FILE if T.COL_FILE.exists() else None, job / "input/oracle_ddl")]
    for kind, src, ddir in items:
        if not src:
            continue
        sha = C.sha256(src)
        if lock.get("locked_at_g3") and lock.get(kind) and lock[kind] != sha:
            C.warn(f"{C.rel(job)}: ของกลาง ({kind}) เปลี่ยนแล้ว แต่งานนี้ผ่าน G3 → ใช้รุ่นเดิมต่อ (เปลี่ยนรุ่น = new-round)")
            continue
        ddir.mkdir(parents=True, exist_ok=True)
        for old in ddir.glob("_shared_*"):
            old.unlink()
        dst = ddir / f"_shared_{src.name}"
        shutil.copy2(src, dst)
        lock[kind] = sha
    lock["linked_at"] = C.now_iso()
    m["target_lock"] = lock
    C.save_job_meta(job, m)


def job_modes(job: Path) -> tuple[str, str]:
    t, m = C.team(), C.job_meta(job)
    ghm = m.get("github_mode") or t["github"]["mode"]
    db = t["db"]
    sel = db.get("select_mode") or ("auto" if db.get("default_mode") == "auto" else "ask")
    dbm = "human" if db.get("ai_access") != "ai" else (m.get("db_mode") or sel)
    return ghm, dbm


def patch_settings(job: Path):
    p = job / ".claude/settings.json"
    s = C.read_json(p, {"permissions": {"allow": [], "ask": [], "deny": []}, "hooks": {}})
    perm = s.setdefault("permissions", {})
    for k in ("allow", "ask", "deny"):
        perm.setdefault(k, [])
    ours = lambda x: x.startswith(("Bash(git push", "Bash(git fetch", "Bash(git pull", "Bash(gh ", "Bash(python scripts/runpack/run_",
                                   "Bash(python3 scripts/runpack/run_", "Bash(py scripts/runpack/run_", "Bash(python scripts/ws/", "Bash(python3 scripts/ws/",
                                   "Bash(sqlplus", "Bash(sqlcl", "Bash(sql "))
    for k in ("allow", "ask", "deny"):
        perm[k] = [x for x in perm[k] if not ours(x)]
    ghm, dbm = job_modes(job)
    perm["allow"] += ["Bash(python scripts/ws/*)", "Bash(python3 scripts/ws/*)"]
    perm["deny"] += ["Bash(git push*main*)", "Bash(git push*master*)", "Bash(git push*--force*)", "Bash(git push*--delete*)",
                     "Bash(git push* +*)", "Bash(gh repo edit*)", "Bash(gh repo delete*)", "Bash(gh issue delete*)", "Bash(gh issue transfer*)",
                     "Bash(gh label delete*)", "Bash(gh api*-X DELETE*)", "Bash(gh api*--method DELETE*)", "Bash(gh api*protection*)"]
    if ghm == "c":
        perm["deny"] += ["Bash(gh *)", "Bash(git push*)", "Bash(git fetch*)", "Bash(git pull*)"]
    else:
        perm["ask"] += ["Bash(git push*)", "Bash(gh issue create*)", "Bash(gh issue edit*)", "Bash(gh issue comment*)", "Bash(gh pr create*)", "Bash(gh pr ready*)", "Bash(gh pr comment*)"]
        (perm["allow"] if ghm == "a" else perm["ask"]).extend(["Bash(git fetch*)", "Bash(gh issue list*)", "Bash(gh issue view*)", "Bash(gh pr view*)", "Bash(gh pr list*)", "Bash(gh api user*)"])
        perm["ask"] += ["Bash(git pull*)"]
    # ฐานข้อมูล (2.10.0): แสดงแผนได้เสมอ · --execute (ได้รับอนุญาตแล้ว) ถามบนจอ Claude Code ทุกครั้ง ·
    # --run-read (SELECT ล้วน) ไม่ต้องถามเมื่อ select_mode = auto · ทีม / งานตั้งคนรัน = ห้าม AI รัน · ห้ามเรียก sqlplus / sqlcl ตรง
    pys = ("python", "python3", "py")
    tools = ("run_sql.py", "run_pack.py")
    perm["allow"] += [f"Bash({p} scripts/runpack/{t}*)" for p in pys for t in tools]
    perm["deny"] += ["Bash(sqlplus*)", "Bash(sqlcl*)", "Bash(sql *)"]
    exe = [f"Bash({p} scripts/runpack/{t}*--execute*)" for p in pys for t in tools]
    rr = [f"Bash({p} scripts/runpack/{t}*--run-read*)" for p in pys for t in tools]
    if dbm == "human":
        perm["deny"] += exe + rr
    else:
        perm["ask"] += exe
        (perm["allow"] if dbm == "auto" else perm["ask"]).extend(rr)
    hooks = s.setdefault("hooks", {}).setdefault("PreToolUse", [])
    cmd = 'python "$CLAUDE_PROJECT_DIR/scripts/hooks/guard_github.py"'
    if not any(cmd in json.dumps(h) for h in hooks):
        hooks.append({"matcher": "Bash|PowerShell", "hooks": [{"type": "command", "command": cmd, "timeout": 20}]})
    C.write_json(p, s)


def patch_claude_md(job: Path):
    """เพิ่ม @import กฎทีม (kit/CLAUDE.kit.md) · slim-job: ส่วนที่เหมือนกันทุกงานย้ายไป kit/CLAUDE.job.md"""
    p = job / "CLAUDE.md"
    t = C.read_text(p)
    if not t:
        return
    up = "../../../../kit"
    if SLIM_MARK not in t:
        t = slim_text(job, t, up)
    if IMPORT_MARK not in t:
        t = t.rstrip("\n") + f"\n\n{IMPORT_MARK}\n## กฎของทีม (workspace)\n\n@{up}/CLAUDE.kit.md\n"
    C.write_text(p, t)


def _split_sections(t: str):
    parts = re.split(r"(?m)^(?=## )", t)
    return parts[0], parts[1:]


def slim_text(job: Path, t: str, up: str) -> str:
    head, secs = _split_sections(t)
    keep = [s for s in secs if s.startswith("## 1.")]
    generic = [s for s in secs if not s.startswith("## 1.")]
    if not keep or not generic:
        return t
    gtext = "".join(generic)
    kp = C.KIT / "CLAUDE.job.md"
    banner = "<!-- ส่วนที่เหมือนกันทุกงาน (ย้ายมาจาก CLAUDE.md ของงานโดย slim-job) · แก้ผ่าน PR ของ kit เท่านั้น -->\n\n"
    if not kp.exists():
        C.write_text(kp, banner + gtext)
    elif C.read_text(kp).replace(banner, "").strip() != gtext.strip():
        C.warn(f"{C.rel(job)}: CLAUDE.md ส่วนกลางต่างจาก kit/CLAUDE.job.md (kit รุ่นต่าง หรือแก้ในงาน) — ไม่ย่อ เก็บฉบับเต็มไว้")
        return t
    return head.rstrip("\n") + f"\n\n{SLIM_MARK}\n> กฎส่วนที่เหมือนกันทุกงานอยู่ใน kit กลาง (โหลดอัตโนมัติด้านล่าง) · ถ้า Claude Code ถามเรื่อง external import ให้อนุญาต\n\n" + \
        "".join(keep).rstrip("\n") + f"\n\n## กฎส่วนกลางของ kit\n\n@{up}/CLAUDE.job.md\n"


def run_unslim(args):
    j = C.job_by_name(args.job)
    p = j / "CLAUDE.md"
    t = C.read_text(p)
    if SLIM_MARK not in t:
        C.ok("CLAUDE.md เป็นฉบับเต็มอยู่แล้ว")
        return
    body = C.read_text(C.KIT / "CLAUDE.job.md").split("-->", 1)[-1].lstrip("\n")
    t = re.sub(r"\n## กฎส่วนกลางของ kit\n\n@[^\n]*CLAUDE\.job\.md\n", "\n" + body, t).replace(SLIM_MARK + "\n", "")
    C.write_text(p, t)
    C.ok(f"คืน CLAUDE.md ฉบับเต็มให้ {C.rel(j)}")


def run_sync_kit(args):
    C.require_workspace()
    jobs = C.job_dirs() if args.all or not args.job else [C.job_by_name(args.job)]
    if not jobs:
        C.info("ไม่มีงานใน branch นี้ (งานอยู่บน branch ของงาน — git switch ไป branch นั้นก่อน หรือ merge แล้ว)")
    bad = []
    for j in jobs:
        try:
            sync_one(j, force=args.force)
        except C.Stop as e:
            bad.append(str(e))
            C.fail(str(e))
    write_registry()
    if bad:
        raise C.Stop(f"sync ไม่ครบ {len(bad)} งาน — งานที่เหลือ sync แล้ว")


def run_link_shared(args):
    for j in (C.job_dirs() if args.all or not args.job else [C.job_by_name(args.job)]):
        link_shared(j)
        C.ok(f"link-shared {C.rel(j)}")


def run_slim(args):
    for j in (C.job_dirs() if args.all or not args.job else [C.job_by_name(args.job)]):
        patch_claude_md(j)
        C.ok(f"slim-job {C.rel(j)} ({len(C.read_text(j / 'CLAUDE.md').splitlines())} บรรทัด)")


def run_set_mode(args):
    j = C.job_by_name(args.job)
    m = C.job_meta(j)
    if args.github:
        m["github_mode"] = C.MODE_KEY.get(args.github) or None
    if args.db:
        if args.db not in ("auto", "ask", "human"):
            raise C.Stop("--db ต้องเป็น auto / ask / human")
        if args.db != "human" and C.team()["db"].get("ai_access") != "ai":
            raise C.Stop("ทีมยังไม่อนุญาตให้ AI เข้าฐาน (team.json db.ai_access) — ต้องให้ทีมตัดสินก่อน")
        C.info({"auto": "งานนี้: SELECT รันต่อเนื่อง · คำสั่งที่เขียนถามก่อนเสมอ", "ask": "งานนี้: ถามก่อนทุกครั้ง รวม SELECT",
                "human": "งานนี้: คนรันทั้งหมด"}[args.db])
        m["db_mode"] = args.db
    C.save_job_meta(j, m)
    patch_settings(j)
    g, d = job_modes(j)
    C.ok(f"{C.rel(j)}: GitHub โหมด {g} · ฐานข้อมูล {d} (อัปเดต .claude/settings.json แล้ว)")


# ---------------------------------------------------------------- fix-mtime
def run_fix_mtime(args):
    """git clone ไม่เก็บเวลาไฟล์ → ตั้งเวลาไฟล์ตาม commit ล่าสุดของไฟล์นั้น (kit บางตัวเทียบเวลาไฟล์)"""
    if not (C.ROOT / ".git").exists():
        raise C.Stop("ไม่ใช่ git repo")
    out = C.git("log", "--name-only", "--format=@%ct", "--no-renames")
    seen, ts, n = set(), 0, 0
    for l in out.splitlines():
        if l.startswith("@"):
            ts = int(l[1:])
            continue
        if not l or l in seen:
            continue
        seen.add(l)
        f = C.ROOT / l
        if f.exists():
            os.utime(f, (ts, ts))
            n += 1
    C.ok(f"ตั้งเวลา {n} ไฟล์ตาม commit")


# ---------------------------------------------------------------- import-job
def run_import_job(args):
    C.require_workspace()
    src = Path(args.path).resolve()
    if not (src / "config/config.json").exists() or not (src / "CLAUDE.md").exists():
        raise C.Stop("ไม่ใช่โฟลเดอร์งานของ kit (ต้องมี config/config.json และ CLAUDE.md)")
    project, job = args.project.upper(), args.job or src.name
    dst = C.PROJECTS / project / "jobs" / job
    if dst.exists():
        raise C.Stop(f"มี {C.rel(dst)} แล้ว")
    ign = shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "*.bak-*")
    shutil.copytree(src, dst, ignore=ign)
    cfg = C.read_json(dst / "config/config.json")
    o = cfg.get("odi") or {}
    v = args.issue or C.ask("", f"เลขใบงานย้อนหลังของงานนี้ (เปิดใบงาน “[job] {project}/{job}” แล้วพิมพ์เลข)", example="7",
                            validate=lambda v: None if v.isdigit() else "ใส่ตัวเลข", use='งานเก่าที่ทำก่อนมี workspace ต้องมีใบงานด้วย เพื่อจองเลขไม่ให้คนอื่นใช้ซ้ำ', rec='เปิดใบงานตามชื่อในวงเล็บ แล้วพิมพ์เลข', skip='ระบบพักไว้ — เปิดใบงานก่อนแล้วรันใหม่', more='หลังได้เลข ระบบจะถามต่อว่าจะใช้รหัสงานตามเลขใหม่ หรือคงรหัสเดิม (ถ้าเคย import เข้า ODI แล้ว ควรคงรหัสเดิม)')
    n = int(v)
    base = id_base(n)
    if o.get("id_base") and int(o["id_base"]) != base:
        C.warn(f"id_base เดิม {o['id_base']} ≠ {base} จากใบงาน — แพ็กเกจที่ import ไปแล้วใช้เลขเดิม: ถ้าเปลี่ยน ต้อง build ใหม่และ import ทับ")
        if C.ask("", "   ใช้เลขไหน", options=[("new", f"ใช้เลขใหม่ {base} (ตามใบงาน · กันชนกับงานอื่น)"), ("old", f"คงเลขเดิม {o['id_base']} (เคย import แล้ว)")], recommend="new", use='เลขใหม่ = กันชนแน่นอน · เลขเดิม = ไม่ต้องแก้ของที่ import ไปแล้วใน ODI', skip='ใช้ค่าแนะนำ', more='ถ้างานนี้เคย import เข้า ODI แล้ว เลือกคงเดิม เพราะเปลี่ยนรหัสจะทำให้ import ครั้งหน้ากลายเป็น project ใหม่ · ถ้ายังไม่เคย import เลือกตามใบงาน') == "old":
            base = int(o["id_base"])
    probs = check_id_unique(o.get("project_code") or odi_code(job), base, me=dst)
    if probs:
        raise C.Stop(" · ".join(probs))
    o["id_base"] = base
    C.write_json(dst / "config/config.json", cfg)
    C.save_job_meta(dst, {"project": project, "job": job, "owner": C.git_user(), "created_at": C.today(), "round": "R01",
                          "branch": f"job/{project}/{job}/R01", "issue": n, "issue_unconfirmed": False, "id_source": "import",
                          "odi_code": o.get("project_code"), "id_base": base, "files_answered": True, "state": "active",
                          "imported_from": src.name, "rounds": [{"round": "R01", "reason": "import-job", "kind": "import", "date": C.today()}]})
    sync_one(dst, first=True)
    write_registry()
    C.ok(f"ย้ายงานเข้า {C.rel(dst)} · id_base {base}")


# ---------------------------------------------------------------- release / new-round
def run_release(args):
    C.require_workspace()
    j = C.job_by_name(args.job)
    m = C.job_meta(j)
    reason = args.reason or C.ask("", "เหตุผลที่ยกเลิกงาน (บันทึกในใบงาน)", example="ธุรกิจยกเลิก workflow นี้", use='บันทึกในใบงานและทะเบียน ให้ทีมรู้ว่าทำไมงานนี้ปิด', rec='ระบุว่าใครตัดสินและเพราะอะไร', skip='ระบบพักไว้ — ยกเลิกงานต้องมีเหตุผล', more="ตัวอย่าง: 'ธุรกิจยกเลิก workflow นี้ (แจ้งโดย คุณ X 28/10)' · เลขรหัสของงานที่ยกเลิกจะไม่ถูกนำกลับมาใช้")
    if m.get("issue") and not m.get("issue_unconfirmed"):
        gh.close_issue(int(m["issue"]), f"ยกเลิกงาน {m.get('project')}/{j.name}: {reason} · เลขนี้ไม่ถูกนำกลับมาใช้")
    m.update({"state": "released", "released_at": C.today(), "release_reason": reason})
    C.save_job_meta(j, m)
    write_registry()
    C.ok(f"ยกเลิกงาน {C.rel(j)} — โฟลเดอร์ยังอยู่ (ประวัติ) · เลข #{m.get('issue')} ไม่ถูกใช้ซ้ำ")


def run_new_round(args):
    C.require_workspace()
    j = C.job_by_name(args.job)
    m = C.job_meta(j)
    rounds = m.setdefault("rounds", [])
    n = len(rounds) + 1
    rn = f"R{n:02d}"
    reason = args.reason or C.ask("", "เหตุผลของรอบใหม่", example="workflow v2 · เพิ่ม task 070000", use='บันทึกว่าทำไมต้องทำงานนี้ซ้ำ (รอบ R02, R03 …)', rec='ระบุสิ่งที่เปลี่ยน เช่น workflow เวอร์ชันใหม่ เพิ่ม task อะไร', skip='ระบบพักไว้ — รอบใหม่ต้องมีเหตุผล', more='รอบใหม่ใช้เลขรหัสงานเดิม แต่เปิด branch ใหม่ · เหตุผลนี้ไปอยู่ในใบงานและ CHANGELOG ของงาน')
    kind = args.kind or C.ask("", "ชนิดของรอบ", options=[("remigrate", "workflow เปลี่ยน (วาง export ใหม่)"), ("fix", "แก้ข้อผิดพลาดของงานเดิม"), ("target", "ของกลางเปลี่ยน (Smart Export / คอลัมน์)")], recommend="remigrate", use='ระบบเลือกว่าต้องกลับไปเริ่มที่ขั้นไหนตามชนิดนี้', skip='ใช้ค่าแนะนำ', more='workflow เปลี่ยน = วาง export ใหม่ เริ่มขั้น 01 · แก้ข้อผิดพลาด = กลับไปขั้นที่เจอปัญหา · ของกลางเปลี่ยน = Smart Export / คอลัมน์ของทีมเปลี่ยน ต้อง build ใหม่')
    rounds.append({"round": rn, "reason": reason, "kind": kind, "date": C.today()})
    m["round"] = rn
    m["branch"] = f"job/{m.get('project')}/{j.name}/{rn}"
    if kind == "target":
        (m.get("target_lock") or {}).pop("locked_at_g3", None)
    C.save_job_meta(j, m)
    rp = j / "ROUNDS.md"
    head = "# ROUNDS — รอบของงานนี้ (GlobalId เดิมทุกรอบ · import ทับของเดิม)\n\n| รอบ | วันที่ | ชนิด | เหตุผล |\n|---|---|---|---|\n"
    C.write_text(rp, (C.read_text(rp) or head).rstrip("\n") + f"\n| {rn} | {C.today()} | {kind} | {reason} |\n")
    if kind == "target":
        link_shared(j)
    write_registry()
    C.ok(f"รอบ {rn} · branch {m['branch']}")
    if (C.ROOT / ".git").exists() and C.ask("", f"เปิด branch {m['branch']} ให้เลยไหม", options=[("y", "เปิด branch ให้เลย"), ("n", "ไม่ต้อง ฉันเปิด branch เอง")], recommend="y", use='แยกรอบใหม่ไว้ใน branch ของตัวเอง (ในเครื่อง)', skip='ใช้ค่าแนะนำ (เปิดให้)', unknown=False, more='ทำเอง = รัน git switch -c <ชื่อ branch> เองก่อนเริ่มแก้') == "y":
        exists = C.git("rev-parse", "--verify", "-q", f"refs/heads/{m['branch']}", check=False)
        C.git("switch", m["branch"]) if exists else C.git("switch", "-c", m["branch"])
        C.git("add", "--", str(j))
        C.git("commit", "-m", f"{m.get('project')}/{j.name}: {rn} ({kind}) {reason}", check=False)
        push_branch(m["branch"])
    C.info("ต่อไป: " + ("วาง export ใหม่ที่ input/blendata/ แล้ว /next-step — AI ถามเฉพาะข้อที่เปลี่ยน" if kind == "remigrate" else "/next-step"))


# ---------------------------------------------------------------- kit-promote / extract-kit
def run_kit_promote(args):
    C.require_workspace()
    j = C.job_by_name(args.job)
    base = C.read_json(BASE_MANIFEST).get("files", {})
    exp = {k: C.sha_text(v) for k, v in expected_files().items()}
    cur = _tracked(j)
    changed = []
    for rel_, sha in cur.items():
        if rel_ in CREATE_ONLY:
            continue
        if sha not in (exp.get(rel_), base.get(rel_)):
            changed.append(rel_)   # ไม่ตรงทั้งต้นฉบับของ setup และของที่ kit วางให้ = แก้ในงาน (หรือไฟล์ใหม่)
    if not changed:
        C.ok("ไม่มีไฟล์ kit ที่แก้ในงานนี้")
        return
    print("   ไฟล์ kit ที่แก้ในงานนี้:")
    for c in changed:
        print(f"     - {c}")
    k = args.k or C.ask("", "รหัสการแก้ (K#) และหัวข้อ", example="K8-check-sql-paren", validate=lambda v: None if re.match(r"^K\d+[\w-]*$", v) else "รูปแบบ K<เลข>-<หัวข้อ>", use='ตั้งชื่อการแก้ kit ให้ทีมอ้างถึงได้', rec='K ตามด้วยเลขถัดไปใน kit/CHANGES-ws.md และหัวข้อสั้น ๆ', skip='ระบบพักไว้', more='ดูเลขล่าสุดใน kit/CHANGES-ws.md แล้วบวก 1 เช่น ล่าสุด K7 → K8-check-sql-paren')
    why = args.reason or C.ask("", "แก้เพราะอะไร (หลักฐาน / บทเรียน)", example="convert_sql ไม่ qualify ตารางหลัง FROM ( — ผล D-R2 FAIL ใน payment", use='ให้ผู้ตรวจรู้ว่าแก้เพราะเจอปัญหาอะไรจริง', rec='อ้างผลตรวจหรืองานที่เจอปัญหา เพื่อให้ตรวจย้อนได้', skip='ระบบพักไว้', more="ตัวอย่าง: 'convert_sql ไม่ใส่ schema หน้าตารางหลัง FROM ( — เจอในงาน payment ตอนตรวจ D-R2'")
    pdir = PATCHES / f"{_dt.date.today():%Y%m%d}_{k}"
    for c in changed:
        C.copy_file(j / c, pdir / "files" / c)
    C.write_text(pdir / "NOTE.md", f"# {k}\n\n- จากงาน: {C.rel(j)}\n- วันที่: {C.today()}\n- โดย: {C.git_user()}\n- เหตุผล: {why}\n- ไฟล์: " + ", ".join(changed) + "\n")
    ch = C.KIT / "CHANGES-ws.md"
    head = "# CHANGES-ws — การแก้ kit ที่ยังไม่ได้ backport เข้า setup_migrate.ps1\n\n| K# | วันที่ | จากงาน | ไฟล์ | เหตุผล | backport แล้ว |\n|---|---|---|---|---|---|\n"
    C.write_text(ch, (C.read_text(ch) or head).rstrip("\n") + f"\n| {k} | {C.today()} | {C.rel(j)} | {len(changed)} ไฟล์ | {why} | ⬜ |\n")
    C.ok(f"เก็บที่ {C.rel(pdir)} · บันทึกใน kit/CHANGES-ws.md")
    if (C.ROOT / ".git").exists():
        br = f"kit/{k}"
        C.info(f"เปิด PR แยก: git switch -c {br} · git add kit/ · git commit · push (ถามก่อน) · ผู้อนุมัติ review")
        if C.ask("", f"สร้าง branch {br} + commit ให้เลยไหม", options=[("y", "สร้าง branch + commit ให้เลย"), ("n", "ไม่ต้อง ฉันทำเอง")], recommend="y", use='ส่งการแก้ kit เข้า PR ให้ผู้ดูแล kit ตรวจ', skip='ใช้ค่าแนะนำ', unknown=False, more='ระบบสร้าง branch ในเครื่องและ commit ไฟล์ที่แก้ ยังไม่ push · ทำเอง = คุณ commit เอง') == "y":
            C.git("switch", "-c", br)
            C.git("add", "--", str(PATCHES), str(ch))
            C.git("commit", "-m", f"kit: {k} — {why}", check=False)
            push_branch(br)
    C.info("หลัง merge: ทุกคน `git pull` แล้ว `python tools/workspace.py sync-kit --all` จะได้การแก้นี้")


def run_extract_kit(args):
    C.require_workspace()
    new = Path(args.setup).resolve()
    if not new.exists():
        raise C.Stop(f"ไม่พบ {new}")
    pend = [l for l in C.read_text(C.KIT / "CHANGES-ws.md").splitlines() if l.startswith("| K") and "⬜" in l]
    if pend and not args.force:
        raise C.Stop(f"ยังมีการแก้ kit ที่ไม่ได้ backport {len(pend)} รายการ (kit/CHANGES-ws.md) — backport เข้า setup ตัวใหม่ก่อน "
                     "แล้วติ๊ก ✅ ในคอลัมน์ 'backport แล้ว' · ไม่งั้นการแก้จะหายเมื่อ sync")
    if SETUP.exists():
        shutil.copy2(SETUP, SETUP.with_name(f"setup_migrate.ps1.bak-{_dt.datetime.now():%Y%m%d%H%M%S}"))
    shutil.copy2(new, SETUP)
    if PATCHES.exists() and not pend:
        arc = C.KIT / "_patches_backported" / f"{_dt.date.today():%Y%m%d}"
        arc.mkdir(parents=True, exist_ok=True)
        for d in PATCHES.iterdir():
            shutil.move(str(d), arc / d.name)
    probe_kit()
    C.ok("เปลี่ยน kit/setup_migrate.ps1 แล้ว — งานใหม่ใช้ตัวนี้ · งานเดิมยังใช้ไฟล์ kit ที่ติดตั้งไว้ (เปลี่ยนด้วย setup -Mode InPlace -RefreshKit ทีละงาน)")
