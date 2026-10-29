"""กลไก ② ล็อก import เข้า ODI_DEV (ใบงานปักหมุด) + ตรวจเลขก่อน import · lock-status · jobs-board"""
from __future__ import annotations

import datetime as _dt
import re

from . import common as C
from . import gh
from . import jobs as J
from . import status as S

LOCK_RX = re.compile(r"^LOCK\s+@?(\S+)\s+(\S+)\s+(\S+)", re.M)
LOCAL = C.REGISTRY / "lock_local.json"


def _parse_time(s: str):
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def lock_state(n: int) -> dict | None:
    """{holders, since, job, expired} จากใบงานปักหมุด · None = อ่าน GitHub ไม่ได้ (แบบคนทำเอง / ไม่ได้รับอนุญาต)"""
    v = gh.view_issue(n)
    if not v:
        return None
    holders = [a.get("login") for a in v.get("assignees") or []]
    since, job = None, ""
    for c in reversed(v.get("comments") or []):
        m = LOCK_RX.search(c.get("body", ""))
        if m and m.group(1) in holders:
            since, job = _parse_time(m.group(3)) or _parse_time(c.get("createdAt", "")), m.group(2)
            break
    hrs = C.team()["lock"]["expire_hours"]
    expired = bool(since and (_dt.datetime.now(_dt.timezone.utc) - since.astimezone(_dt.timezone.utc)) > _dt.timedelta(hours=hrs))
    return {"holders": holders, "since": since, "job": job, "expired": expired, "url": v.get("url", "")}


def _ago(t) -> str:
    if not t:
        return "?"
    m = int((_dt.datetime.now(_dt.timezone.utc) - t.astimezone(_dt.timezone.utc)).total_seconds() // 60)
    return f"{m // 60} ชม. {m % 60} นาที" if m >= 60 else f"{m} นาที"


def verify_ids(job) -> list[str]:
    """ตรวจเลขของงานกับใบงาน + งานอื่นทั้งในเครื่องและทุก branch ที่ fetch มา"""
    m = C.job_meta(job)
    cfg = C.read_json(job / "config/config.json")
    o = cfg.get("odi") or {}
    probs = []
    if m.get("issue_unconfirmed"):
        probs.append(f"เลข #{m.get('issue')} ยังไม่ยืนยัน (คำนวณในเครื่อง) — `python tools/workspace.py confirm-id --job {job.name}` ก่อน")
    want = J.id_base(int(m.get("issue") or 0)) if m.get("issue") else None
    if want and int(o.get("id_base") or 0) != want and m.get("id_source") != "import":
        probs.append(f"id_base ใน config ({o.get('id_base')}) ≠ เลขจากใบงาน #{m.get('issue')} ({want})")
    probs += J.check_id_unique(o.get("project_code", ""), int(o.get("id_base") or 0), me=job)
    for r in S.remote_jobs(fetch=False):
        if r["path"] == C.rel(job):
            continue
        ro = r.get("odi") or {}
        if ro.get("project_code") == o.get("project_code"):
            probs.append(f"ODI code {o.get('project_code')} ซ้ำกับ {r['path']} บน {r['ref']}")
        if ro.get("id_base") and int(ro["id_base"]) == int(o.get("id_base") or 0):
            probs.append(f"id_base {o.get('id_base')} ซ้ำกับ {r['path']} บน {r['ref']}")
    return probs


def odi_repo_check(job) -> str:
    """ตรวจกับ ODI repository จริงว่าไม่มี project อื่นใช้ code นี้ — ต้องอ่านฐานได้ · ชื่อตาราง SNP_* ยังต้องยืนยันกับ ODI 14c"""
    cfg = C.read_json(job / "config/config.json")
    code = (cfg.get("odi") or {}).get("project_code", "")
    wr = (cfg.get("odi") or {}).get("work_repo_schema") or "<WORK_REPO_SCHEMA>"
    pack = job / "run_packs" / "rp_import_check"
    sql = (f"-- ก่อน import: มี project code {code} ใน ODI repository อยู่แล้วไหม (ถ้ามี ต้องเป็นงานนี้เท่านั้น = Overwrite)\n"
           "-- ⚠️ ชื่อตาราง/คอลัมน์ SNP_PROJECT ยังไม่ยืนยันกับ ODI 14c ของทีม — ถ้า error ให้บอก AI พร้อมข้อความ error ไม่ต้องเดา\n"
           f"SELECT project_code, project_name FROM {wr}.SNP_PROJECT WHERE project_code = '{code}'\n")
    C.write_text(pack / "C1_project_code.sql", sql)
    t = C.team()
    if t["db"].get("ai_access") == "ai" and t["db"].get("read_odi_log"):
        from . import db as DB
        C.info("ทีมอนุญาตให้ AI อ่าน work repository")
        st = DB.run(pack / "C1_project_code.sql", f"ตรวจว่ามี project code {code} ใน ODI แล้วหรือยัง (SELECT)", root=job)
        res = job / "input/run_results/rp_import_check/C1_project_code.csv"
        if st == "ran" and res.exists():
            n = max(len(res.read_text(encoding="utf-8-sig").splitlines()) - 1, 0)
            if n == 0:
                C.ok(f"ยังไม่มี project {code} ใน ODI — import ได้")
                return "0"
            print(res.read_text(encoding="utf-8-sig"))
        elif st == "error":
            C.warn("ตรวจไม่สำเร็จ — ดูข้อความด้านบน (ชื่อตาราง SNP_* อาจไม่ตรงกับ ODI ของทีม) · ตรวจเองแทนได้ตามขั้นตอนด้านล่าง")
    if t["db"].get("ai_access") == "ai" and t["db"].get("read_odi_log") and (job / "input/run_results/rp_import_check/C1_project_code.csv").exists():
        a = C.ask("", "   ผลเป็นอย่างไร (ดูแถวด้านบน)", options=[("same", "เป็นงานนี้เอง (import ครั้งก่อน)"), ("other", "ไม่ใช่งานนี้")], recommend="same", use='กันไม่ให้ import ทับ project ของคนอื่นที่ใช้รหัสเดียวกันใน ODI', skip='ใช้ค่าแนะนำ', unknown=False, more='แถวด้านบนคือ project ใน ODI ที่ใช้รหัสนี้อยู่ · ถ้าชื่อ project ตรงกับงานนี้ (เคย import) = ปลอดภัย · ถ้าเป็นงานอื่น = ห้าม import ต้องคุยกับทีม')
        if a == "other":
            raise C.Stop(f"ODI code {code} ถูกใช้โดย project อื่นใน repository — หยุด ห้าม import · ปรึกษาทีมเรื่องเปลี่ยนรหัส")
        return a
    print(f"\n   ตรวจกับ ODI repository (ไม่บังคับแต่แนะนำ):")
    print(f"   1) เปิดไฟล์ {C.rel(pack / 'C1_project_code.sql')} ใน DBeaver ที่ต่อ work repository")
    print("   2) เพื่อดูว่ามี project อื่นใช้รหัสนี้อยู่หรือไม่ (กัน import ทับงานคนอื่น)")
    print("   3) ดูจำนวนแถวที่ได้ (ไม่ต้อง export)")
    a = C.ask("", "   ผลเป็นอย่างไร", options=[("0", "0 แถว = ยังไม่มี project นี้"), ("same", "มี 1 แถวและเป็นงานนี้เอง (import ครั้งก่อน)"),
                                           ("other", "มีและไม่ใช่งานนี้"), ("s", "ข้าม (ไม่ได้ตรวจ)")], recommend="0", use='กันไม่ให้ import ทับ project ของคนอื่นที่ใช้รหัสเดียวกันใน ODI', skip='ระบบบันทึกว่าไม่ได้ตรวจ', unknown=False, more='query ที่ให้รันนับว่ามี project ใน ODI ใช้รหัสนี้อยู่กี่ตัว · 0 แถว = ปลอดภัย · มี 1 แถวที่เป็นงานนี้ (เคย import) = ปลอดภัย · มีแถวที่ไม่ใช่งานนี้ = ห้าม import ต้องคุยกับทีม')
    if a == "other":
        raise C.Stop(f"ODI code {code} ถูกใช้โดย project อื่นใน repository — หยุด ห้าม import · ปรึกษาทีมเรื่องเปลี่ยนรหัส")
    return a


def run_import_lock(args):
    C.require_workspace()
    job = C.job_by_name(args.job)
    C.section(f"🔒 import-lock · {C.rel(job)}")
    probs = verify_ids(job)
    if probs:
        raise C.Stop("ตรวจเลขก่อน import ไม่ผ่าน:\n   - " + "\n   - ".join(probs))
    C.ok("เลขตรงกับใบงาน และไม่ชนกับงานอื่นที่เห็น")
    chk = "skip" if args.skip_odi_check else odi_repo_check(job)
    n = gh.lock_issue_number()
    me = gh.me() if gh.mode() != "c" else None
    if n and gh.mode() != "c":
        st = lock_state(n)
        if st is None:
            raise C.Stop("อ่านใบงานล็อกไม่ได้ (ไม่ได้รับอนุญาต) — ห้าม import โดยไม่ผ่าน import-lock")
        others = [h for h in st["holders"] if h != me]
        if others:
            msg = f"ODI_DEV มีคนใช้อยู่: {', '.join(others)} ตั้งแต่ {_ago(st['since'])} ที่แล้ว (งาน {st['job'] or '?'}) · {st['url']}"
            if st["expired"]:
                msg += f"\n   เกินเวลา {C.team()['lock']['expire_hours']} ชม. แล้ว — ถ้าแน่ใจว่าเขาลืมปลด: import-unlock --force --reason \"…\" (ระบบบันทึกว่าใครปลดแทนเพราะอะไร)"
            raise C.Stop(msg)
        if me not in st["holders"]:
            if not gh.assign_me(n):
                raise C.Stop("ยังไม่ได้ใส่ชื่อในใบงานล็อก — ห้าม import")
            gh.comment(n, f"LOCK @{me} {C.rel(job)} {C.now_iso()}\nตรวจกับ ODI repo: {chk}", "บันทึกการล็อกในใบงาน")
            st2 = lock_state(n)
            if st2 and len(st2["holders"]) > 1:
                gh.unassign(n, "")
                raise C.Stop(f"มีคนใส่ชื่อพร้อมกัน ({', '.join(st2['holders'])}) — ถอยให้ก่อน รอแล้วลองใหม่")
    else:
        print(f"\n   (แบบคนทำเอง / ไม่มีใบงานล็อก) ทำเองบนเว็บ GitHub:")
        print(f"   1) เปิดใบงานปักหมุด “{gh.LOCK_TITLE}”{f' #{n}' if n else ''} ดูว่าไม่มีชื่อคนอื่นใน Assignees")
        print(f"   2) assign ตัวเอง แล้ว comment: LOCK @<ชื่อคุณ> {C.rel(job)} {C.now_iso()}")
        if C.ask("", "   ทำแล้วหรือยัง", options=[("y", "ใส่ชื่อจองแล้ว ไม่มีคนอื่นจองอยู่"), ("n", "ยังไม่ได้จอง / มีคนอื่นจองอยู่")], recommend="y", use='ป้ายจองกันสองคน import เข้า ODI_DEV พร้อมกัน', skip='ใช้ค่าแนะนำ', unknown=False, more='ทำแล้ว = คุณใส่ชื่อตัวเองในใบงานปักหมุดแล้ว และไม่มีชื่อคนอื่นอยู่ · ยัง = ระบบหยุด ห้าม import จนกว่าจะล็อกได้') != "y":
            raise C.Stop("ยังไม่ได้ล็อก — ห้าม import")
        me = me or C.git_user()
    C.write_json(LOCAL, {"job": C.rel(job), "by": me, "since": C.now_iso(), "issue": n, "odi_check": chk})
    C.section("✅ ได้ล็อกแล้ว — ทำต่อใน ODI Studio")
    zips = sorted((job / "output/odi_export").glob("*.zip")) or sorted((job / "output/odi_export").glob("*.xml"))
    C.info(f"1) Designer → Import → Smart Import (ไม่ใช่ Import Project) → {zips[-1].name if zips else 'ไฟล์ใน output/odi_export/'}")
    C.info("2) procedure / package ชื่อตรงของเดิม = Overwrite · ไม่มี error / Create Copy")
    C.info("3) Topology: ตรวจ Logical Schema / Context / login · Generate Scenario (ทำใน Studio — kit ไม่สร้าง Scenario)")
    C.info("4) Export Smart Export หลัง import วางที่ input/odi_reference/ (หลักฐาน G4)")
    C.info(f"5) python tools/workspace.py import-unlock --job {job.name}")


def run_import_unlock(args):
    C.require_workspace()
    job = C.job_by_name(args.job) if args.job else None
    loc = C.read_json(LOCAL)
    if not job and loc.get("job"):
        job = C.ROOT / loc["job"]
    n = gh.lock_issue_number()
    me = gh.me() if gh.mode() != "c" else C.git_user()
    if args.force:
        if not args.reason:
            raise C.Stop("ปลดล็อกแทนคนอื่นต้องมีเหตุผล: --reason \"…\"")
        if n and gh.mode() != "c":
            st = lock_state(n) or {"holders": []}
            for h in st["holders"]:
                if h != me:
                    gh.unassign(n, h)
            gh.comment(n, f"FORCE-UNLOCK โดย @{me} {C.now_iso()} เหตุผล: {args.reason} (ถือเดิม: {', '.join(st['holders']) or '-'})", "บันทึกการปลดแทน")
        else:
            C.info(f"(แบบคนทำเอง) เอาชื่อออกจากใบงานปักหมุดเอง แล้ว comment: FORCE-UNLOCK โดย {me} เหตุผล: {args.reason}")
        C.ok("ปลดล็อกแทนแล้ว (บันทึกเหตุผลในใบงาน)")
        return
    if not job:
        raise C.Stop("ระบุ --job ของงานที่ import")
    res = args.result or C.ask("", "ผลการ Smart Import", options=[("ok", "import สำเร็จ ไม่มี error"), ("fail", "import ล้ม / มี error (บอก AI ด้วย /diagnose)")], recommend="ok", use='บันทึกลง status/IMPORT_LOG.md และปลดล็อกให้คนถัดไป', skip='ใช้ค่าแนะนำ', unknown=False, more='สำเร็จ = Smart Import จบโดยไม่มี error · ล้ม = มี error ระบบยังบันทึกและปลดล็อก แล้วให้ใช้ /diagnose หาสาเหตุ')
    pk = sorted((job / "output/odi_export").glob("*.zip")) or sorted((job / "output/odi_export").glob("*.xml"))
    pkg = pk[-1].name if pk else "?"
    after = sorted((job / "input/odi_reference").glob("*"), key=lambda p: p.stat().st_mtime)
    after = [p for p in after if not p.name.startswith("_shared_") and p.suffix.lower() in (".xml", ".zip")]
    if res == "ok" and not after:
        C.warn("ยังไม่มี Smart Export หลัง import ใน input/odi_reference/ — G4 ต้องใช้ (วางแล้วค่อย /gate G4)")
    if n and gh.mode() != "c":
        gh.comment(n, f"UNLOCK @{me} {C.rel(job)} {C.now_iso()} · import {pkg} · ผล {res}", "บันทึกผล import ในใบงาน")
        gh.unassign(n, "")
    else:
        C.info(f"(แบบคนทำเอง) เอาชื่อออกจากใบงานปักหมุด แล้ว comment: UNLOCK {me} {C.rel(job)} import {pkg} ผล {res}")
    p = job / "status/IMPORT_LOG.md"
    t = C.read_text(p) or "# IMPORT_LOG — การ Smart Import เข้า ODI_DEV\n\n| รายการ | วันที่ | โดย | แพ็กเกจ | ผล | Smart Export หลัง import | ล็อก |\n|---|---|---|---|---|---|---|\n"
    C.write_text(p, t.rstrip("\n") + f"\n| IMPORT | {C.now_iso()} | {me} | {pkg} | {res} | {after[-1].name if after else '-'} | #{n or '-'} |\n")
    if LOCAL.exists():
        LOCAL.unlink()
    m = C.job_meta(job)
    if res == "ok":
        m.setdefault("target_lock", {})["locked_at_g3"] = m.get("target_lock", {}).get("locked_at_g3") or C.today()
        C.save_job_meta(job, m)
    C.ok(f"ปลดล็อก + บันทึก status/IMPORT_LOG.md · ต่อไป: /gate G4 ในแชทของงาน")


def run_lock_status(args):
    C.require_workspace()
    n = gh.lock_issue_number()
    loc = C.read_json(LOCAL)
    if loc:
        C.info(f"ในเครื่องนี้: {loc['by']} ถือล็อกสำหรับ {loc['job']} ตั้งแต่ {loc['since']}")
    if not n:
        C.info("ยังไม่รู้เลขใบงานปักหมุด — รัน init-github หรือใส่ github.lock_issue ใน shared/team.json")
        return
    st = lock_state(n)
    if st is None:
        C.info(f"ดูเองที่ใบงาน #{n} บน GitHub (Assignees = คนที่กำลัง import)")
        return
    if not st["holders"]:
        C.ok(f"ODI_DEV ว่าง (ใบงาน #{n})")
    else:
        C.info(f"ODI_DEV มีคนใช้: {', '.join(st['holders'])} · งาน {st['job'] or '?'} · {_ago(st['since'])} ที่แล้ว" + (" · ⚠️ เกินเวลาแล้ว" if st["expired"] else ""))


def run_jobs_board(args):
    C.require_workspace()
    iss = gh.list_issues(gh.JOB_LABEL)
    local = {str(C.job_meta(j).get("issue")): j for j in C.job_dirs()}
    if iss is None:
        C.info("อ่าน GitHub ไม่ได้ในโหมดนี้ — แสดงจากในเครื่อง:")
        for k, j in local.items():
            m = C.job_meta(j)
            print(f"   #{k:<5} {C.rel(j):55} id_base {m.get('id_base')}{' (ยังไม่ยืนยัน)' if m.get('issue_unconfirmed') else ''}")
        return
    print(f"   {'ใบงาน':<7} {'สถานะ':<7} {'ชื่อ':<45} {'คนถือ':<15} ในเครื่อง")
    for i in sorted(iss, key=lambda x: x["number"]):
        j = local.get(str(i["number"]))
        ass = ",".join(a["login"] for a in i.get("assignees") or []) or "-"
        print(f"   #{i['number']:<6} {i['state'].lower():<7} {i['title'][:45]:<45} {ass:<15} {C.rel(j) if j else '-'}")
