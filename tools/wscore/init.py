"""init (ตั้งทีมครั้งเดียว 12 ข้อ) และ init-github"""
from __future__ import annotations

import json
import os
import shutil

from . import common as C
from . import gh
from . import target as T

ANS = C.SHARED / ".init_answers.json"   # คำตอบที่ตอบแล้ว (รันใหม่ทำต่อจากข้อเดิม) · ไม่ commit

FIELD_HELP = {
    "logical_schema": ("ชื่อ Logical Schema ใน ODI",
                       "ชื่อกลางที่ Procedure ใช้ชี้ไปฐานปลายทาง (ทุก step ของงานจะรันผ่านชื่อนี้)",
                       "ดูที่ ODI Studio → Topology → Logical Architecture → Technologies → Oracle → ชื่อที่ต่อกับ schema ปลายทาง",
                       "LS_ORA_TARGET"),
    "context_code": ("รหัส Context ใน ODI",
                     "บอก ODI ว่ารันกับสภาพแวดล้อมไหน (DEV / SIT / PROD) — ODI ใช้ Context จับคู่ Logical Schema กับฐานจริง",
                     "ดูที่ ODI Studio → Topology → Contexts → ดูช่อง Code (ไม่ใช่ Name) ของ context ที่ใช้รันบน DEV",
                     "DEV  หรือ  GLOBAL"),
    "work_user": ("user / schema ของฐานปลายทาง",
                  "schema ใน Oracle ที่ตารางปลายทางของงานอยู่ (ใช้ตอนทำ SQL และ query ตรวจผล)",
                  "ดูที่ ODI Studio → Topology → Physical Architecture → Data Server ของ Oracle → Physical Schema → ช่อง Schema",
                  "DWH_OWNER"),
}

GITIGNORE = """# สร้างโดย workspace.py init — ไฟล์ที่สร้างใหม่ได้เสมอ / ข้อมูลอ่อนไหว ไม่ขึ้น Git
registry/
STATUS.md
shared/db.local.json
shared/.init_answers.json
shared/target/_incoming/*
!shared/target/_incoming/.gitkeep
projects/*/jobs/*/input/run_results/
projects/*/jobs/*/input/odi_reference/_shared_*
projects/*/jobs/*/input/oracle_ddl/_shared_*
projects/*/jobs/*/.claude/settings.local.json
**/.dbx/
/setup_migrate*.ps1
**/__pycache__/
**/_pyc/
*.pyc
*.bak-*
"""

GITATTR = """# ไฟล์ ODI / SQL / ผลรัน ห้ามแปลงบรรทัด (ODI ตรวจ byte ของ XML)
* text=auto
*.xml -text
*.sql -text
*.csv -text
*.txt -text
*.zip binary
*.ps1 text eol=crlf
*.cmd text eol=crlf
"""


def _load():
    return C.read_json(ANS, {})


def _save(a):
    C.write_json(ANS, a)


def _validate_logins(v: str):
    xs = [x.strip().lstrip("@") for x in v.split(",") if x.strip()]
    if not xs:
        return "ใส่อย่างน้อย 1 คน"
    bad = [x for x in xs if not C.re.match(r"^[A-Za-z0-9-]+$", x)]
    return f"ชื่อ GitHub ใช้ได้เฉพาะ a-z 0-9 - : {', '.join(bad)}" if bad else None


def _int(v):
    return None if v.isdigit() else "ใส่ตัวเลข"


def run_init(args):
    C.ROOT.mkdir(parents=True, exist_ok=True)
    if C.WS_MARK.exists() and not args.reconfigure:
        raise C.Stop("โฟลเดอร์นี้ตั้ง workspace แล้ว — ใส่ --reconfigure ถ้าจะตอบคำถามใหม่ (ไฟล์เดิม backup ก่อนเสมอ)")
    T.ensure_dirs()
    a = _load()
    N = 12
    C.section("🧭 ตั้งทีม (ครั้งเดียว) · ถามทีละข้อ · Enter = ค่าตั้งต้น · ? = อธิบาย · q = ออก")
    print(f"\n[1/{N}] สร้าง workspace ที่ไหน\n   > โฟลเดอร์นี้: {C.ROOT.name}  (เลือกตอนรัน setup แล้ว)")

    if "git" not in a:
        a["git"] = C.ask(f"2/{N}", "สร้าง git repo ให้เลยไหม", options=[("y", "สร้าง (.gitignore + .gitattributes + commit แรก)"), ("n", "ไม่สร้าง (มี repo อยู่แล้ว / ทำเอง)")],
                         recommend="n" if (C.ROOT / ".git").exists() else "y",
                         why="ต้องมี git ถึงจะทำงานหลายคนได้ · ถ้ามี .git อยู่แล้วไม่ต้องสร้างซ้ำ", use='git เก็บประวัติไฟล์ ทำให้หลายคนทำงานในโฟลเดอร์เดียวกันได้ (แต่ละงานแยก branch แล้วรวมผ่าน GitHub)', skip='ใช้ค่าแนะนำ', more="ถ้าโฟลเดอร์นี้ได้มาจาก git clone (มีโฟลเดอร์ .git อยู่แล้ว) ให้เลือก 'ไม่สร้าง' เพราะมี repo แล้ว · ถ้าเป็นโฟลเดอร์ว่างธรรมดา ให้เลือก 'สร้าง' ระบบจะทำ git init + ไฟล์ .gitignore (กันไฟล์ที่ไม่ควรขึ้น GitHub เช่น ค่าเชื่อมต่อฐาน) + commit แรกให้ · ยังไม่ส่งอะไรขึ้น GitHub ในข้อนี้"); _save(a)
    if "ai_mode" not in a:
        a["ai_mode"] = C.ask(f"3/{N}", "AI Mode ของทีม", what="วิธีแก้ SQL ที่ตัวแปลงติดธงไว้",
                             options=[("manual", "แก้ในแชท Claude Code (คนเห็นทุกจุด)"), ("auto", "เรียก Anthropic API แก้ให้ (ต้องมี ANTHROPIC_API_KEY · ส่ง SQL ออกไปประมวลผล)")],
                             recommend="manual", why="ไม่ต้องตั้ง API key และไม่ส่ง SQL ออกนอกแชท", use='ตอนตัวแปลง SQL เจอจุดที่แปลงอัตโนมัติไม่ได้ จะให้แก้ที่ไหน', skip='ใช้ค่าแนะนำ แก้ทีหลังได้ที่ shared/team.json', more='manual = จุดที่ติดธงจะถูกแก้ในหน้าแชท Claude Code คุณเห็นทุกบรรทัดก่อนบันทึก · auto = สคริปต์เรียก Anthropic API แก้ให้ทั้งชุด ต้องตั้ง ANTHROPIC_API_KEY และ SQL จะถูกส่งออกไปประมวลผลนอกเครื่อง (เช็กนโยบายข้อมูลของบริษัทก่อน) · ทีมที่เพิ่งเริ่มควรใช้ manual'); _save(a)
    if "approvers" not in a:
        a["approvers"] = C.ask(f"4/{N}", "รายชื่อผู้อนุมัติ (ชื่อบัญชี GitHub)", what="คนที่ตัดสินคำถามและอนุมัติ gate — ระบบรับ ✅ จากคนกลุ่มนี้เท่านั้น",
                               example="mint-g,bank-g", validate=_validate_logins, use='ระบบรับเครื่องหมายอนุมัติ (✅) จากรายชื่อนี้เท่านั้น — เจ้าของงานอนุมัติงานตัวเองไม่ได้', rec='ชื่อบัญชี GitHub ของ Tech Lead และ SA อย่างน้อย 2 คน คั่นด้วย ,', skip='ถ้ายังไม่ทราบ ระบบพักไว้ก่อน — ไปขอชื่อบัญชี GitHub ของ Tech Lead / SA มาแล้วรันใหม่', more='ชื่อบัญชี GitHub คือชื่อที่อยู่หลัง github.com/ ในหน้าโปรไฟล์ (ไม่ใช่ชื่อจริง ไม่ใช่อีเมล) เช่น github.com/mint-g → mint-g · คนในรายชื่อนี้เป็นคนตอบคำถามธุรกิจและกดผ่านด่านตรวจ (gate) · ใส่อย่างน้อย 2 คนเพื่อให้มีคนอนุมัติแทนกันได้ · แก้ภายหลังได้ที่ shared/approvers.txt'); _save(a)
    if "perf" not in a:
        print(f"\n[5/{N}] เกณฑ์ความเร็วของทีม (2 ค่า)")
        bw = C.ask("", "   กรอบเวลา batch (นาที) · Enter = ยังไม่กำหนด", example="60", required=False, validate=_int, use='ใช้ตัดสินว่า job ที่ย้ายมา ODI รันเสร็จทันเวลาไหม', rec="ใส่ตัวเลขตามข้อตกลงเวลารันของทีม (SLA) ถ้ายังไม่มีให้เลือก 'ยังไม่ทราบ'", skip='รายงานความเร็วจะแสดงแค่ตัวเลข ไม่ตัดสินผ่าน / ไม่ผ่าน (ใส่ทีหลังได้ใน shared/team.json)', more="ตัวอย่าง: ถ้า job ต้องรันจบภายใน 1 ชั่วโมงในรอบกลางคืน ให้ใส่ 60 · ระบบจะเทียบเวลาที่ ODI รันจริงกับตัวเลขนี้ ถ้าเกินจะขึ้น 'ไม่ผ่าน' ในรายงานขั้น 05 · หน่วยเป็นนาที")
        sp = C.ask("", "   % ที่ยอมให้ช้ากว่า Blendata · Enter = ยังไม่กำหนด", example="20", required=False, validate=_int, use='ยอมให้ ODI ช้ากว่า Blendata เดิมได้กี่ % ก่อนจะเตือน', rec='20 ถ้ายังไม่มีเกณฑ์ของทีม', skip='ไม่เทียบความเร็วกับ Blendata (ใส่ทีหลังได้ใน shared/team.json)', more="ตัวอย่าง: Blendata เดิมรัน 10 นาที ใส่ 20 → ODI รันได้ถึง 12 นาทีโดยไม่ถูกเตือน ถ้าเกินจะขึ้น 'ต้องดู' ในรายงาน (เตือนเฉย ๆ ไม่บล็อกงาน)")
        a["perf"] = {"batch_window_min": int(bw) if bw else None, "slower_pct": int(sp) if sp else None}; _save(a)
    if "github_mode" not in a:
        a["github_mode"] = C.MODE_KEY[C.ask(f"6/{N}", "ค่าตั้งต้น: ให้ AI ติดต่อ GitHub แบบไหน",
                                            what="ระหว่างทำงาน AI ต้อง pull / push / ขอเลขใบงาน / ใส่ชื่อล็อก โดยใช้สิทธิ์บัญชีของคนที่ใช้เครื่องนั้น",
                                            options=[("a", "อ่านได้เอง · เขียนต้องถามทุกครั้ง"), ("b", "ถามทุกครั้งทั้งอ่านและเขียน"), ("c", "คนทำเองทั้งหมด AI บอกคำสั่งให้")],
                                            recommend="a", why="เร็วพอ และทุกการเขียนยังต้องได้คำว่า ใช่ · ถ้านโยบายบริษัทห้าม AI ใช้ GitHub ให้เลือกข้อ 3 (คนทำเองทั้งหมด)", use='กำหนดว่า AI ทำอะไรบน GitHub ได้เองบ้าง ใช้กับทุกงานที่เปิดใหม่', skip='ใช้ค่าแนะนำ', more='ข้อ 1: AI อ่าน GitHub ได้เอง (ดึงสถานะงานของทีม) แต่ทุกครั้งที่จะเขียน (push / เปิดใบงาน / ใส่ชื่อล็อก) ต้องถามคุณก่อน · ข้อ 2: ถามก่อนทุกครั้งทั้งอ่านและเขียน · ข้อ 3: AI ไม่แตะ GitHub เลย แค่บอกคำสั่งให้คุณรันเอง · ทุกข้อ AI ห้าม push เข้า main / force-push / ลบ branch / แก้ตั้งค่า repo เสมอ · แต่ละงานเปลี่ยนเองได้ด้วยคำสั่ง set-mode')]; _save(a)
    # ---- 7 Smart Export
    if "smart_export" not in a:
        while True:
            have = T.current_smart_export()
            if have:
                a["smart_export"] = have.name; _save(a); break
            ans = C.ask(f"7/{N}", "Smart Export ตั้งต้น — วางที่ shared/target/_incoming/",
                        what="ไฟล์ export จาก ODI Studio ที่ต่อ repository DEV: คลิกขวา Project → Export → Smart Export · ไม่ใส่ export key · ติ๊ก Topology",
                        options=[("ok", "วางแล้ว ตรวจเลย"), ("h", "ขอวิธีทำใน Studio ทีละขั้น"), ("s", "วางทีหลัง (new-job จะยังทำไม่ได้)")],
                        recommend="ok", example="วาง path ไฟล์ เช่น D:\\odi\\ODI_REFERENCE_DEV_20261027.xml (kit ก็อปมาให้)", paths=True, use='ระบบอ่านชื่อ Logical Schema, Context, schema และเวอร์ชัน ODI ปลายทางจากไฟล์นี้ — ทั้งทีมใช้ไฟล์เดียว', skip='ยังเปิดงานใหม่ (new-job) ไม่ได้จนกว่าจะวางไฟล์แล้วรัน update-target', unknown=False, more='วิธีทำ: เปิด ODI Studio ที่ต่อ repository DEV → Designer → คลิกขวาโปรเจกต์ใดก็ได้ → Export → Smart Export → ลาก Logical Schema / Context / Data Server ที่งานใช้เข้ามาด้วย → Export Key เว้นว่าง → บันทึกเป็น .xml หรือ .zip · ถ้าไม่มีสิทธิ์ใช้ ODI Studio ให้ขอไฟล์จากผู้ดูแล ODI · ระบบไม่อ่านรหัสผ่านในไฟล์')
            if ans.startswith("path:"):
                C.copy_into(ans[5:], C.TARGET / "_incoming", (".xml", ".zip"))
                ans = "ok"
            if ans == "h":
                print("   1) ODI Studio → Designer → Projects  2) คลิกขวาโปรเจกต์ใดก็ได้ใน repository DEV → Export → Smart Export\n"
                      "   3) ลาก Topology (Logical Schema / Context / Data Server ที่งานใช้) เข้ามาด้วย  4) Export Key: เว้นว่าง\n"
                      "   5) บันทึกเป็น .xml หรือ .zip แล้ววางที่ shared/target/_incoming/")
                continue
            if ans == "s":
                a["smart_export"] = ""; _save(a); break
            if "smart_export" in T.intake_incoming("ตั้งค่าครั้งแรก", interactive_reason=False):
                a["smart_export"] = T.current_smart_export().name; _save(a); break
            C.warn("ยังไม่มี Smart Export ที่ใช้ได้ — แก้ตามข้อความด้านบนแล้วเลือก 'วางแล้ว ตรวจเลย' อีกครั้ง")
    # ---- 8 ค่าที่อ่านได้
    if "target" not in a:
        vals, info = {}, None
        se = T.current_smart_export()
        if se:
            info, _ = T.check_smart_export(se)
            vals = info["values"] if info else {}
        cands = {"logical_schema": (info or {}).get("logical_schemas", []), "context_code": (info or {}).get("contexts", []),
                 "work_user": sorted({x.get("user") for x in (info or {}).get("physical_schemas", []) if x.get("user")})}
        print(f"\n[8/{N}] ค่าของ ODI ปลายทางที่อ่านได้จาก Smart Export ถูกต้องไหม")
        for k in ("logical_schema", "context_code", "work_user", "repository_version", "odi_version"):
            v = vals.get(k)
            if not v and cands.get(k):
                v = f"(เจอหลายค่า: {', '.join(cands[k])} — จะให้เลือก)"
            print(f"   {k:20}: {v or '(ไม่เจอในไฟล์ — ต้องใส่เอง)'}")
        need_edit = not all(vals.get(k) for k in ("logical_schema", "context_code", "work_user"))
        if not need_edit:
            need_edit = C.ask("", "   ถูกต้องไหม", options=[("y", "ถูกต้องทุกค่า ใช้ตามนี้"), ("n", "มีค่าที่ไม่ถูก ขอแก้ทีละค่า")], recommend="y", use='ค่าพวกนี้จะใส่ในทุกงาน ถ้าผิด แพ็กเกจจะ import แล้วรันไม่ได้', skip='ใช้ค่าแนะนำ (ถือว่าถูก) แก้ทีหลังได้ด้วย update-target', more='เทียบกับ ODI Studio → Topology: logical_schema ดูที่ Logical Architecture · context_code ดูที่ Contexts (ช่อง Code) · work_user ดูที่ Physical Schema ของ data server ปลายทาง · ถ้าไม่แน่ใจให้ถามผู้ดูแล ODI') == "n"
        if need_edit:
            for k in ("logical_schema", "context_code", "work_user"):
                title, what, where, ex = FIELD_HELP[k]
                cs = cands.get(k) or []
                if not vals.get(k) and len(cs) > 1:
                    opts = [(str(i + 1), c) for i, c in enumerate(cs)]
                    rec = next((str(i + 1) for i, c in enumerate(cs) if c.upper() in ("DEV", "DEVELOPMENT", "GLOBAL")), "1") if k == "context_code" else "1"
                    pick = C.ask("", f"   {k} = {title}", what=f"{what} · Smart Export มี {len(cs)} ค่า เลือกตัวที่ใช้กับงานนี้",
                                 options=opts + [("x", "ไม่ใช่ทั้งหมด พิมพ์เอง")], recommend=rec,
                                 why="ตัวที่ตรงกับ repository DEV ที่จะ import (ถ้าไม่แน่ใจ ถาม DBA / ผู้ดูแล ODI)", explain=where, use='ใส่ลงในทุกงานของทีม ทุก step ใน ODI จะใช้ค่านี้', skip='ค่านี้ต้องมี — ถ้าไม่แน่ใจ พิมพ์ ? ดูว่าหาได้ที่ไหน หรือถาม DBA / ผู้ดูแล ODI', more='ดูวิธีหาค่าในบรรทัดถัดไป · ค่าที่ใส่ต้องตรงกับ repository ที่จะ import จริง (ตัวพิมพ์ใหญ่-เล็กไม่สำคัญ) · ใส่ผิดจะ import ผ่านแต่รันไม่ได้ · แก้ทีหลังได้ด้วย update-target')
                    if pick != "x":
                        vals[k] = cs[int(pick) - 1]
                        continue
                vals[k] = C.ask("", f"   {k} = {title}", what=what, default=vals.get(k) or None, example=ex, why="อ่านได้จาก Smart Export ของทีม" if vals.get(k) else "",
                                explain=where + " · ถ้าไม่แน่ใจ ถาม DBA / ผู้ดูแล ODI ของทีม", use='ใส่ลงในทุกงานของทีม ทุก step ใน ODI จะใช้ค่านี้', skip='ค่านี้ต้องมี — ถ้าไม่แน่ใจ พิมพ์ ? ดูว่าหาได้ที่ไหน หรือถาม DBA / ผู้ดูแล ODI', more='ดูวิธีหาค่าในบรรทัดถัดไป · ค่าที่ใส่ต้องตรงกับ repository ที่จะ import จริง (ตัวพิมพ์ใหญ่-เล็กไม่สำคัญ) · ใส่ผิดจะ import ผ่านแต่รันไม่ได้ · แก้ทีหลังได้ด้วย update-target')
        vals["target_prefix"] = C.ask("", "   prefix ชื่อตาราง (schema นำหน้า) · Enter = ไม่มี", default=(vals.get("schema_name") or "").lower() + "." if vals.get("schema_name") else "",
                                      example="myschema.", required=False, what='ชื่อ schema ที่เติมหน้าชื่อตาราง เช่น dssdev.orders', use='ให้ SQL ชี้ตารางใน schema ที่ถูก', skip='ไม่เติม schema หน้าชื่อตาราง', more='ถ้า user ที่ ODI ใช้รันเป็นเจ้าของตารางเอง ไม่ต้องมี prefix ก็ได้ · ถ้าตารางอยู่คนละ schema กับ user ที่รัน ต้องมี prefix ไม่งั้นจะเจอ ORA-00942 (หาตารางไม่เจอ) · ค่าแนะนำมาจาก Physical Schema ใน Smart Export')
        a["target"] = {k: vals.get(k, "") for k in ("logical_schema", "context_code", "work_user", "target_prefix", "repository_version", "odi_version",
                                                       "origin_master_repository_id", "origin_work_repository_id", "schema_name")}
        _save(a)
    # ---- 9 AI ต่อฐาน
    if "db" not in a:
        d = C.ask(f"9/{N}", "ให้ AI เข้าฐานข้อมูลและรันคำสั่งเองได้ไหม",
                  what="ระหว่างทำงานต้องรัน SQL บ่อย: ดึงข้อมูลมาตรวจ (SELECT) · ใส่ / ลบ mock data · สร้างตาราง (DDL) · เทียบผลหลังรัน",
                  options=[("ai", "ให้ AI รันได้ทุกคำสั่ง — แต่ต้องขออนุญาตก่อนทุกครั้ง (เลือกได้ว่าให้ AI รันหรือคนรันเอง)"),
                           ("human", "คนรันทั้งหมด (AI เตรียมไฟล์ + บอกขั้นตอนทีละไฟล์)"),
                           ("undecided", "ยังไม่ตัดสิน (ใช้แบบคนรันไปก่อน เปลี่ยนทีหลังได้)")],
                  recommend="ai", why="งานเดินต่อเนื่องได้ และทุกคำสั่งยังต้องได้รับอนุญาตจากคนก่อนรัน", use='ตัดสินว่าใครรัน SQL ระหว่างทำงาน — AI รันเองหลังได้รับอนุญาต หรือคนรันทั้งหมด', skip='ใช้ค่าแนะนำ · เปลี่ยนทีหลังได้ที่ shared/team.json (ผ่าน PR ของทีม)', more='ข้อ 1: AI รันได้ทุกคำสั่ง (SELECT · INSERT · DELETE · TRUNCATE · CREATE · DROP ฯลฯ) ทุกฐานที่ตั้งไว้ แต่ก่อนรันทุกครั้งจะโชว์ SQL ที่จะรันจริงกับชื่อฐาน แล้วถามว่า 1 ให้ AI รัน / 2 ฉันรันเอง · คำสั่งที่ลบแล้วกู้คืนไม่ได้ต้องพิมพ์ชื่อตารางยืนยันอีกชั้น · ทุกครั้งที่รันถูกบันทึก · ข้อ 2: AI ไม่ต่อฐานเลย เตรียมไฟล์แล้วบอกคนทีละไฟล์ · ข้อ 3: ใช้แบบคนรันไปก่อน · ไม่ว่าแบบไหน งานใน ODI Studio และบน Blendata เป็นของคนเสมอ')
        db = {"ai_access": "ai" if d == "ai" else "human", "select_mode": "ask", "users": "split", "read_odi_log": False}
        if d == "ai":
            from . import db as DB
            db["select_mode"] = C.ask("", "   ตอนตรวจสอบ (SELECT อ่านอย่างเดียว) ต้องถามก่อนทุกครั้งไหม",
                                      options=[("ask", "ถามก่อนทุกครั้ง รวม SELECT"), ("auto", "SELECT รันต่อเนื่อง ถามเฉพาะคำสั่งที่เขียน / แก้โครงสร้าง")],
                                      recommend="ask", why="คุมได้ทุกขั้น · เปลี่ยนรายงานได้ด้วย set-mode", use='กำหนดว่าคำสั่งอ่านอย่างเดียว (SELECT) ต้องขออนุญาตทุกครั้งหรือรันต่อเนื่องได้ — คำสั่งที่เขียน / แก้โครงสร้างถามเสมอไม่ว่าเลือกแบบไหน', skip='ใช้ค่าแนะนำ (ถามทุกครั้ง)', more='ในงานหนึ่ง SELECT มีหลายสิบครั้ง (เช็กข้อมูลก่อนรัน นับแถว เทียบผลกับเฉลย) · ถามทุกครั้ง = คุมได้ทุกขั้นแต่ต้องตอบบ่อย · รันต่อเนื่อง = เร็ว SELECT แก้ข้อมูลไม่ได้อยู่แล้ว · แต่ละงานเปลี่ยนเองได้: python tools/workspace.py set-mode --job <งาน> --db auto|ask|human')
            db["users"] = C.ask("", "   ใช้ user ฐานข้อมูลแบบไหน",
                                options=[("split", "2 user: SELECT ใช้ user อ่านอย่างเดียว · คำสั่งเขียนใช้ user ที่เขียนได้"),
                                         ("single", "user เดียวที่เขียนได้ ใช้กับทุกคำสั่ง")],
                                recommend="split", why="query ตรวจสอบทั่วไปแก้ข้อมูลไม่ได้แม้พลาด และ log แยกชัดว่าครั้งไหนเขียน", use='กำหนดว่า AI ใช้ user ไหนต่อฐาน', skip='ใช้ค่าแนะนำ (2 user)', more='2 user: SELECT ใช้ user อ่านอย่างเดียว (รหัสในตัวแปร ORA_RO_PASSWORD) · คำสั่งที่เขียนใช้ user ที่เขียนได้ (ORA_RW_PASSWORD) — query ตรวจสอบแก้ข้อมูลไม่ได้แม้พลาด · user เดียว: ตั้งง่ายกว่า แต่ทุก query วิ่งด้วยสิทธิ์เขียน (ORA_RW_PASSWORD) · ขอ user จาก DBA · เปลี่ยนทีหลังได้ใน shared/team.json')
            env, conn = DB.configure_connection(None, db["users"])
            db["default_env"] = env
            C.write_json(C.DB_LOCAL, {"default": env, "connections": {env: conn}})
            C.info("เก็บใน shared/db.local.json (ไม่ขึ้น Git · ไม่มีรหัสผ่าน) · เพิ่มฐานอื่น (SIT / PROD) ทีหลัง: python tools/workspace.py db-connect --env SIT")
            db["read_odi_log"] = C.ask("", "   อ่าน log ของ ODI (work repository) ได้ไหม", options=[("y", "อนุญาตให้ AI อ่าน log ของ ODI"), ("n", "ไม่อนุญาต (คนดู log ใน ODI Studio เอง)")], recommend="n",
                                       why="ชื่อตาราง SNP_* ยังต้องยืนยันกับ ODI 14c ก่อน", use='ให้ AI อ่านผลการรันจาก repository ของ ODI เองไหม (ใช้ตอนหาสาเหตุงานล้ม)', skip='ใช้ค่าแนะนำ (ไม่อ่าน) — คนดู log ใน ODI Studio แล้วส่งให้ AI', more="log อยู่ในตาราง SNP_* ของ work repository · ชื่อตารางยังไม่ได้ยืนยันกับ ODI 14c ของทีม จึงแนะนำ 'ไม่ได้' ไปก่อน") == "y"
            a["db"] = db; _save(a)
            C.write_json(C.TEAM_JSON, {**C.read_json(C.TEAM_JSON, {}), "db": db})   # ชั่วคราวระหว่าง init (ตัวรันอ่านกติกาจากไฟล์นี้) · เขียนเต็มตอนจบ
            DB.password_notice(env, db["users"])
            DB.offer_test(env)
        a["db"] = db; _save(a)
    # ---- 10 คอลัมน์
    if "columns" not in a:
        owner = a["target"].get("schema_name") or a["target"].get("work_user")
        sqlp = T.columns_sql(owner)
        ai_db = (a.get("db") or {}).get("ai_access") == "ai"
        while True:
            if T.COL_FILE.exists():
                a["columns"] = True; _save(a); break
            if ai_db:
                from . import db as DB
                print(f"\n[10/{N}] คอลัมน์ของ schema ปลายทาง ({owner})")
                ok_, why_not = DB.ready()
                drv = DB.need_driver() and C.DB_LOCAL.exists()
                if not ok_:
                    C.warn(why_not)
                how = C.ask("", "   ดึงรายชื่อคอลัมน์ของ schema ปลายทางอย่างไร",
                            options=([("install", "ติดตั้งตัวต่อ Oracle ให้ (pip install oracledb) แล้วดึงจากฐานเลย")] if drv else []) + [
                                     ("ai", "ให้ระบบดึงจากฐานเอง (SELECT อย่างเดียว · ถามก่อนรันตามกติกาทีม)"),
                                     ("manual", "ฉันรัน query เองใน DBeaver แล้ววางไฟล์"),
                                     ("s", "ยังไม่ดึง ข้ามไปก่อน (new-job ยังทำได้ แต่ /inputs จะขาดข้อนี้)")],
                            recommend="install" if drv else ("ai" if ok_ else "manual"),
                            why="ทีมอนุญาตให้ AI เข้าฐานแล้ว (ข้อ 9)" if (ok_ or drv) else "เครื่องนี้ยังต่อฐานเองไม่ได้ (ดูข้อความด้านบน)", use='ไฟล์คอลัมน์ทำให้ AI รู้ชนิดข้อมูลจริงของตารางปลายทาง ไม่ต้องเดา', skip='ใช้ค่าแนะนำ', unknown=False, more='ติดตั้งตัวต่อ Oracle ให้: ระบบรัน pip install oracledb (ครั้งเดียวต่อเครื่อง ต้องต่ออินเทอร์เน็ตได้) แล้วดึงต่อทันที · ให้ระบบดึงเอง: ระบบรัน SELECT จาก all_tab_columns ด้วย user อ่านอย่างเดียวที่ตั้งในข้อ 9 (session READ ONLY · บันทึกใน registry/db_queries.log) แล้วตรวจไฟล์ให้ทันที · ต้องมี python-oracledb (pip install oracledb) และรหัสผ่าน (ตัวแปร ORA_RO_PASSWORD หรือพิมพ์ตอนรัน — ไม่แสดงบนจอ ไม่เก็บลงไฟล์) · รันเองใน DBeaver: ใช้เมื่อเครื่องนี้ต่อฐานไม่ได้ · ข้าม: เปิดงานได้ แต่ AI จะถามเรื่องคอลัมน์ตอน /inputs')
                if how == "s":
                    a["columns"] = False; _save(a); break
                if how == "install":
                    if not DB.install_driver():
                        continue
                    how = "ai"
                if how == "ai":
                    if DB.fetch_columns(owner, "ตั้งค่าครั้งแรก (ระบบดึงจากฐาน)"):
                        a["columns"] = True; _save(a); break
                    continue
            print(f"\n[10/{N}] คอลัมน์ของ schema ปลายทาง")
            print(f"   1) เปิดไฟล์ {C.rel(sqlp)} ใน DBeaver ที่ต่อ Oracle DEV")
            print("   2) เพื่อให้ AI รู้คอลัมน์จริงตอนเขียน INSERT (ไม่ต้องเดาชนิดข้อมูล)")
            print("   3) Export ผลเป็น CSV มีหัว 10 ช่อง (OWNER … DATA_DEFAULT)")
            print("   4) วางที่ shared/target/_incoming/")
            ans = C.ask("", "   วางแล้วหรือยัง", options=[("ok", "วางไฟล์คอลัมน์แล้ว ตรวจเลย"), ("s", "ยังไม่ได้วาง ข้ามไปก่อน (new-job ยังทำได้ แต่ /inputs จะขาดข้อนี้)")], recommend="ok", use='ไฟล์คอลัมน์ทำให้ AI รู้ชนิดข้อมูลจริงของตารางปลายทาง ไม่ต้องเดา', skip='เปิดงานได้ แต่ AI จะถามเรื่องคอลัมน์เพิ่มตอน /inputs', unknown=False, more="เปิดไฟล์ SQL ที่ระบบสร้างให้ (บอกในบรรทัดด้านบน) ใน DBeaver ที่ต่อ Oracle DEV → รัน → Export ผลเป็น CSV (UTF-8 มีหัวคอลัมน์) → วางที่ shared/target/_incoming/ แล้วเลือก 'วางแล้ว' · query เป็น SELECT อย่างเดียว")
            if ans == "s":
                a["columns"] = False; _save(a); break
            if "columns" in T.intake_incoming("ตั้งค่าครั้งแรก", interactive_reason=False):
                a["columns"] = True; _save(a); break
    if "error_handling" not in a:
        a["error_handling"] = C.ask(f"11/{N}", "Error Handling ตั้งต้น", what="เมื่อเจอ error ระหว่างรัน package",
                                    options=[("fail-fast", "หยุดที่ error แรก"), ("errlog", "รันต่อ เก็บแถวที่พังด้วย DBMS_ERRLOG (ต้องเตรียม error table)")],
                                    recommend="fail-fast", why="ตรวจง่าย ไม่มีข้อมูลค้างครึ่งเดียว · แต่ละงานเปลี่ยนได้ในขั้น 02", use='ถ้าแถวไหนพังตอน INSERT จะหยุดทั้ง job หรือข้ามแถวนั้นแล้วเก็บไว้ดู', skip='ใช้ค่าแนะนำ', more='fail-fast: หยุดที่ error แรก ข้อมูลไม่ครึ่ง ๆ กลาง ๆ ตรวจง่าย · errlog: รันต่อแล้วเก็บแถวที่พังไว้ในตาราง error (DBMS_ERRLOG) ต้องให้ DBA สร้างตาราง error ก่อน · แต่ละงานเปลี่ยนเองได้'); _save(a)
    if "dev_ready" not in a:
        print(f"\n[12/{N}] ความพร้อมของ DEV (2 ข้อ)")
        t1 = C.ask("", "   ข้อย่อย 1: ตั้ง JDBC URL + user/password ใน Topology ของ ODI Studio แล้ว?", options=[("y", "ตั้งค่าเชื่อมต่อใน Topology แล้ว"), ("n", "ยังไม่ได้ตั้ง")], recommend="y", use='ถ้ายังไม่ตั้ง import ได้แต่รันไม่ได้ — ระบบแค่จดไว้เตือน ไม่หยุดงาน', skip='ใช้ค่าแนะนำ (ระบบเตือนอีกครั้งก่อน import)', more='ODI Studio → Topology → Physical Architecture → Data Server ของ Oracle ปลายทาง → ใส่ JDBC URL / user / password แล้วกด Test Connection · รหัสผ่านตั้งใน Studio เท่านั้น ไม่อยู่ในไฟล์ของระบบ')
        t2 = C.ask("", "   ข้อย่อย 2: ได้สิทธิ์ Smart Import (+ DBMS_ERRLOG ถ้าใช้) แล้ว?", options=[("y", "ได้สิทธิ์ Smart Import แล้ว"), ("n", "ยังไม่ได้สิทธิ์ / ยังไม่ได้ขอ")], recommend="y", use='ต้องมีสิทธิ์นี้ถึงจะ import แพ็กเกจเข้า ODI ได้ — ระบบแค่จดไว้เตือน', skip='ใช้ค่าแนะนำ (ระบบเตือนอีกครั้งก่อน import)', more='ลองเปิด ODI Studio → Designer → เมนู Import → Smart Import ถ้าเข้าไม่ได้ให้ขอสิทธิ์จากผู้ดูแล ODI · ถ้าใช้ errlog ต้องมีสิทธิ์ DBMS_ERRLOG ด้วย')
        a["dev_ready"] = {"topology": t1 == "y", "smart_import_rights": t2 == "y"}; _save(a)

    # ---- summary
    C.section("📋 สรุปก่อนสร้าง")
    se = T.current_smart_export()
    rows = [("Smart Export", f"✓ {se.name} · sha256 {C.sha256(se)[:8]}…" if se else "⬜ ยังไม่มี"),
            ("คอลัมน์", f"✓ {T.check_columns(T.COL_FILE)[0].get('rows', 0):,} แถว" if T.COL_FILE.exists() else "⬜ ยังไม่มี"),
            ("ค่า ODI", f"{a['target'].get('logical_schema')} · CTX {a['target'].get('context_code')} · {a['target'].get('work_user')}"),
            ("ผู้อนุมัติ", a["approvers"]),
            ("เกณฑ์ความเร็ว", f"{a['perf'].get('batch_window_min') or '-'} นาที · ช้าได้ {a['perf'].get('slower_pct') or '-'}%"),
            ("AI กับ GitHub", {"a": "อ่านได้เอง · เขียนต้องถามทุกครั้ง", "b": "ถามทุกครั้ง", "c": "คนทำเองทั้งหมด"}[a["github_mode"]]),
            ("AI ต่อฐาน", ("ได้ทุกคำสั่ง (ขออนุญาตก่อน) · SELECT " + ("ถามทุกครั้ง" if a["db"].get("select_mode") == "ask" else "รันต่อเนื่อง") + " · " + ("2 user" if a["db"].get("users") == "split" else "user เดียว") + " · ฐาน " + a["db"].get("default_env", "DEV")) if a["db"]["ai_access"] == "ai" else "ไม่ (คนรันทั้งหมด)"),
            ("AI Mode / Error", f"{a['ai_mode']} / {a['error_handling']}"),
            ("DEV พร้อม", f"Topology {'✓' if a['dev_ready']['topology'] else '⬜'} · สิทธิ์ import {'✓' if a['dev_ready']['smart_import_rights'] else '⬜'}")]
    for k, v in rows:
        print(f"   {k:16}: {v}")
    if C.INTERACTIVE:
        c = C.ask("", "ยืนยันสร้างไฟล์ของทีมตามคำตอบด้านบน", options=[("y", "สร้างเลย"), ("e", "กลับไปแก้คำตอบ (ตอบใหม่ทั้งหมด)"), ("q", "ออก ยังไม่สร้าง (คำตอบเก็บไว้)")], recommend="y", use='ยืนยันคำตอบทั้งหมดด้านบน แล้วสร้างไฟล์ของทีม', skip='ใช้ค่าแนะนำ (สร้าง)', unknown=False, more='สร้าง = เขียน shared/team.json, approvers.txt, workspace.json และไฟล์ของ kit · แก้ = กลับไปตอบใหม่ทุกข้อ · ออก = ยังไม่สร้างอะไร คำตอบเก็บไว้')
        if c == "e":
            C.write_json(ANS, {})
            return run_init(args)
        if c == "q":
            raise C.Stop("ยังไม่ได้เขียนไฟล์ — คำตอบเก็บไว้แล้ว รันใหม่จะทำต่อ")
    _write_all(a)


def _write_all(a):
    t = C.team()
    t.update({
        "workspace_version": C.WS_VERSION,
        "ai_mode": a["ai_mode"],
        "error_handling": a["error_handling"],
        "perf": a["perf"],
        "github": {**t.get("github", {}), "mode": a["github_mode"]},
        "db": a["db"],
        "target": a["target"],
        "dev_ready": a["dev_ready"],
        "lock": {"expire_hours": 2},
        "ids": {"base": 90000, "step": 1000},
    })
    C.save_team(t)
    logins = [x.strip().lstrip("@") for x in a["approvers"].split(",") if x.strip()]
    C.write_text(C.SHARED / "approvers.txt", "# ผู้อนุมัติ: บรรทัดละคน `login [email]` · CI ใช้ตรวจว่า ✅ มาจากคนกลุ่มนี้\n" + "\n".join(logins) + "\n")
    C.write_json(C.WS_MARK, {"workspace_version": C.WS_VERSION, "created_at": C.today(), "created_by": C.git_user()})
    if not (C.TARGET / "environment-facts.md").exists():
        C.write_text(C.TARGET / "environment-facts.md", "# environment-facts — Oracle / ODI DEV (ใช้ร่วมทุกงาน)\n\n"
                     "เติมจากผล preflight (P1 NLS / timezone · version) พร้อมแหล่งที่มา · แก้ผ่าน PR แยก\n\n| ข้อเท็จจริง | ค่า | แหล่งที่มา | วันที่ |\n|---|---|---|---|\n")
    if not (C.TARGET / "CHANGELOG.md").exists():
        T.changelog("init", "ตั้งของกลางครั้งแรก", "init")
    T.write_source_md()
    for d in (C.PROJECTS, C.REGISTRY):
        d.mkdir(parents=True, exist_ok=True)
    keep = C.PROJECTS / ".gitkeep"
    keep.exists() or keep.write_text("", encoding="utf-8")
    if not (C.ROOT / ".gitignore").exists():
        C.write_text(C.ROOT / ".gitignore", GITIGNORE)
    if not (C.ROOT / ".gitattributes").exists():
        C.write_text(C.ROOT / ".gitattributes", GITATTR)
    from .jobs import probe_kit
    try:
        probe_kit()
    except C.Stop as e:
        C.warn(f"{e} — จะสร้างให้ตอน new-job ครั้งแรก")
    if a["git"] == "y" and not (C.ROOT / ".git").exists():
        C.git("init", "-b", "main")
        C.git("add", "-A")
        C.git("commit", "-m", "workspace init (setup_migrate 2.9.0)", check=False)
        C.ok("git repo + commit แรก")
    if ANS.exists():
        ANS.unlink()
    C.section("✅ ตั้งทีมเสร็จ")
    C.info("ขั้นต่อไป (ทำทีละข้อ):")
    C.info("1) python tools/workspace.py init-github   — CODEOWNERS · PR template · CI · ใบงานปักหมุด · labels")
    C.info("2) สร้าง repo private บน GitHub แล้ว: git remote add origin <url> · git push -u origin main  (คนทำเอง — AI ไม่ push เข้า main)")
    C.info("3) ทุกคน git clone แล้วเปิดงานด้วย: python tools/workspace.py new-job")


# ---------------------------------------------------------------- init-github
def _codeowners(logins):
    own = " ".join("@" + l for l in logins)
    return ("# ไฟล์ตัดสินใจและ gate ต้องได้ review จากผู้อนุมัติ (สร้างโดย workspace.py init-github)\n"
            f"projects/*/jobs/*/status/OPEN_DECISIONS.md {own}\n"
            f"projects/*/jobs/*/status/GATES.md {own}\n"
            f"projects/*/jobs/*/status/PREFLIGHT_CHECKLIST.md {own}\n"
            f"/kit/ {own}\n/shared/ {own}\n/.github/ {own}\n/tools/ {own}\n")


def run_init_github(args):
    C.require_workspace()
    t = C.team()
    logins = [x["login"] for x in C.approvers()]
    gt = C.KIT / "github"
    if not gt.exists():
        raise C.Stop("ไม่พบ kit/github/ (แม่แบบ CI) — workspace อาจไม่ครบ ให้รัน setup_migrate.ps1 -Mode Workspace ใหม่")
    dst = C.ROOT / ".github"
    for f in gt.rglob("*"):
        if f.is_file():
            out = dst / f.relative_to(gt)
            if not out.exists() or args.force:
                C.copy_file(f, out)
    C.write_text(dst / "CODEOWNERS", _codeowners(logins))
    C.ok("เขียน .github/ (CODEOWNERS · PR template · CI 4 ตัว)")
    # GitHub (ถามก่อนทุกครั้งตามกลไก ⑤)
    C.section("GitHub: labels และใบงานปักหมุด")
    gh.ensure_labels()
    n = gh.lock_issue_number()
    if n:
        C.ok(f"มีใบงานปักหมุด #{n} แล้ว")
    else:
        body = ("ใบงานนี้คือล็อกของ ODI_DEV — คนที่ถูก assign = คนที่กำลัง Smart Import\n\n"
                "- ใส่ / เอาชื่อออก: `python tools/workspace.py import-lock` / `import-unlock`\n"
                f"- หมดอายุ {t['lock']['expire_hours']} ชั่วโมง · ปลดแทนต้องมีเหตุผล (`import-unlock --force --reason`)\n"
                "- comment ในใบงานนี้ = ประวัติการ import")
        n = gh.create_issue(gh.LOCK_TITLE, body, gh.LOCK_LABEL)
        if n:
            gh.write(f"ปักหมุดใบงาน #{n}", ["issue", "pin", str(n)], f"เปิดใบงาน #{n} → Pin issue")
        else:
            v = C.ask("", "ถ้าเปิดใบงานปักหมุดเองแล้ว พิมพ์เลขใบงาน · Enter = ทำทีหลัง", example="1", required=False, validate=_int, use="ใบงานปักหมุดคือ 'ป้ายจอง' ODI_DEV กันสองคน import พร้อมกัน", rec="เปิดใบงานชื่อ 'ODI_DEV กำลังใช้งาน' บน GitHub แล้ว Pin ไว้ จากนั้นพิมพ์เลข", skip='ทำทีหลังได้ — แต่ import-lock จะใช้ไม่ได้จนกว่าจะมีใบงานนี้', more="บน github.com → repo ของทีม → Issues → New issue → ชื่อ 'ODI_DEV กำลังใช้งาน' → Submit → เมนูขวา Pin issue · เลขใบงานคือเลขหลัง # ในหัวใบงาน")
            n = int(v) if v else None
    if n:
        t["github"]["lock_issue"] = n
        C.save_team(t)
    C.section("ต่อไป (คนทำเองบนเว็บ GitHub — การตั้งค่า repo เป็นคำสั่งต้องห้ามของ AI)")
    C.info("1) Settings → Branches → Add rule สำหรับ main:")
    C.info("   ✓ Require a pull request · ✓ Require review from Code Owners")
    C.info("   ✓ Require status checks: workspace-check · verify-approvals · secret-scan")
    C.info("2) Settings → Actions → General → Workflow permissions: Read and write (ให้ approve-command commit ✅ ได้)")
    C.info("3) token ของแต่ละคน: fine-grained เฉพาะ repo นี้ (Contents · Issues · Pull requests) ไม่ให้สิทธิ์ Administration")
    C.info("4) commit .github/ แล้ว push ผ่าน PR")
