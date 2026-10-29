"""ของกลาง: ระบบปลายทาง DEV ชุดเดียว (shared/target/)

shared/target/
  _incoming/              วางไฟล์ใหม่ที่นี่ แล้วสั่ง update-target (หรือตอน init)
  smart_export/           Smart Export ของ repository DEV (ไม่เข้ารหัส · มี Topology) — ไฟล์เดียว
  columns/                all_tab_columns.csv (หัว 10 ช่อง) + T0_schema_columns.sql
  _archive/<วันเวลา>_<ชนิด>/   ของเดิมก่อนเปลี่ยน + NOTE.md
  SOURCE.md               ไฟล์ไหน มาจากไหน sha256 อะไร
  environment-facts.md    version · NLS · timezone (เติมจาก preflight)
  CHANGELOG.md            อะไรเปลี่ยนเมื่อไหร่เพราะอะไร
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import shutil
from pathlib import Path

from . import common as C
from .vendor import read_smart_export as RSE

SE_DIR = C.TARGET / "smart_export"
COL_DIR = C.TARGET / "columns"
INCOMING = C.TARGET / "_incoming"
ARCHIVE = C.TARGET / "_archive"
COL_FILE = COL_DIR / "all_tab_columns.csv"
COL_HEADER = ["OWNER", "TABLE_NAME", "COLUMN_ID", "COLUMN_NAME", "DATA_TYPE", "DATA_LENGTH",
              "DATA_PRECISION", "DATA_SCALE", "NULLABLE", "DATA_DEFAULT"]


def ensure_dirs():
    for d in (SE_DIR, COL_DIR, INCOMING, ARCHIVE):
        d.mkdir(parents=True, exist_ok=True)
    keep = INCOMING / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")


def current_smart_export() -> Path | None:
    c = [p for p in SE_DIR.glob("*") if p.suffix.lower() in (".xml", ".zip")] if SE_DIR.exists() else []
    return max(c, key=lambda p: p.stat().st_mtime) if c else None


# ---------------------------------------------------------------- validate
def check_smart_export(p: Path) -> tuple[dict | None, list[str]]:
    """ตรวจเชิงโครงสร้าง: ไม่เข้ารหัส · มี <Admin> · มี Topology · ไม่อ่าน field รหัสผ่าน"""
    try:
        r = RSE.parse(p)
    except Exception as e:  # zip เสีย / อ่านไม่ได้
        return None, [f"อ่าน {p.name} ไม่ได้: {e}"]
    probs = list(r.get("problems", []))
    r["values"] = RSE.odi_values(r)
    return r, probs


def check_columns(p: Path) -> tuple[dict, list[str]]:
    probs = []
    raw = p.read_bytes()
    text = None
    for enc in ("utf-8-sig", "cp874", "iso-8859-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        return {}, ["ไฟล์ว่าง"]
    head = [h.strip().upper() for h in rows[0]]
    if head[:10] != COL_HEADER:
        probs.append("หัวคอลัมน์ต้องเป็น 10 ช่องตามลำดับ: " + ", ".join(COL_HEADER) + f" (ไฟล์นี้: {', '.join(head[:10]) or '-'})")
        return {}, probs
    body = [r for r in rows[1:] if any(c.strip() for c in r)]
    if not body:
        probs.append("มีแต่หัวคอลัมน์ ไม่มีข้อมูล — query อาจได้ 0 แถว (ไม่นับว่าผ่าน) ตรวจ owner ใน WHERE")
    tables = {}
    for r in body:
        if len(r) < 10:
            probs.append(f"แถวไม่ครบ 10 ช่อง: {r[:3]}")
            break
        tables.setdefault((r[0].strip().upper(), r[1].strip().upper()), {})[r[3].strip().upper()] = \
            (r[4].strip(), r[5].strip(), r[6].strip(), r[7].strip(), r[8].strip())
    return {"rows": len(body), "tables": tables, "owners": sorted({k[0] for k in tables})}, probs


def columns_sql(owner: str) -> Path:
    COL_DIR.mkdir(parents=True, exist_ok=True)
    owner = (owner or "<SCHEMA_OWNER>").upper()
    sql = (
        "-- คอลัมน์ทั้ง schema ปลายทาง (ใช้ร่วมกันทุกงาน) · SELECT อย่างเดียว\n"
        "-- 1) เปิดไฟล์นี้ใน DBeaver ที่ต่อ Oracle DEV  2) Ctrl+Enter\n"
        "-- 3) Export ผลเป็น CSV มีหัวคอลัมน์ (UTF-8)  4) วางที่ shared/target/_incoming/ แล้วเลือก 'วางแล้ว ตรวจเลย'\n"
        "SELECT owner, table_name, column_id, column_name, data_type, data_length,\n"
        "       data_precision, data_scale, nullable, data_default\n"
        "FROM   all_tab_columns\n"
        f"WHERE  owner = '{owner}'\n"
        "ORDER  BY table_name, column_id\n")
    p = COL_DIR / "T0_schema_columns.sql"
    C.write_text(p, sql)
    return p


# ---------------------------------------------------------------- place / archive
def _archive(kind: str, files: list[Path], reason: str):
    if not files:
        return None
    d = ARCHIVE / f"{_dt.datetime.now():%Y%m%d_%H%M%S}_{kind}"
    d.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.move(str(f), d / f.name)
    C.write_text(d / "NOTE.md", f"# เก็บของเดิม ({kind})\n\n- วันที่: {C.now_iso()}\n- โดย: {C.git_user()}\n- เหตุผลที่เปลี่ยน: {reason}\n")
    return d


def place_smart_export(src: Path, reason: str) -> Path:
    SE_DIR.mkdir(parents=True, exist_ok=True)
    old = [p for p in SE_DIR.glob("*") if p.is_file() and p.name != ".gitkeep"]
    _archive("smart_export", old, reason)
    name = src.name if src.name.lower().startswith("smart_export") else f"smart_export_DEV_{_dt.date.today():%Y%m%d}{src.suffix.lower()}"
    dst = SE_DIR / name
    shutil.move(str(src), dst)
    return dst


def place_columns(src: Path, reason: str) -> Path:
    COL_DIR.mkdir(parents=True, exist_ok=True)
    _archive("columns", [COL_FILE] if COL_FILE.exists() else [], reason)
    shutil.move(str(src), COL_FILE)
    return COL_FILE


def write_source_md():
    se = current_smart_export()
    lines = ["# SOURCE — ของกลางของระบบปลายทาง DEV", "",
             "ไฟล์ในโฟลเดอร์นี้ใช้ร่วมกันทุกงาน · เปลี่ยนได้ทาง `python tools/workspace.py update-target` เท่านั้น", "",
             "| ไฟล์ | sha256 | ขนาด | วันที่วาง |", "|---|---|---|---|"]
    for p in [se, COL_FILE]:
        if p and p.exists():
            st = p.stat()
            lines.append(f"| `{C.rel(p)}` | `{C.sha256(p)[:16]}…` | {st.st_size:,} | {_dt.datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M} |")
    if se:
        info, _ = check_smart_export(se)
        if info:
            v = info["values"]
            lines += ["", "## ค่าที่อ่านจาก Smart Export", "",
                      "| ค่า | ค่า |", "|---|---|"]
            for k in ("logical_schema", "context_code", "work_user", "schema_name", "repository_version", "odi_version"):
                lines.append(f"| {k} | `{v.get(k) or '(ไม่มีค่าเดียว)'}` |")
    C.write_text(C.TARGET / "SOURCE.md", "\n".join(lines) + "\n")


def changelog(kind: str, summary: str, reason: str):
    p = C.TARGET / "CHANGELOG.md"
    head = "# CHANGELOG — ของกลาง (shared/target)\n\n| วันที่ | ชนิด | สิ่งที่เปลี่ยน | เหตุผล | โดย |\n|---|---|---|---|---|\n"
    t = C.read_text(p) or head
    C.write_text(p, t.rstrip("\n") + f"\n| {C.today()} | {kind} | {summary} | {reason} | {C.git_user()} |\n")


def diff_values(old: dict, new: dict) -> list[str]:
    out = []
    for k in sorted(set(old) | set(new)):
        if str(old.get(k, "")) != str(new.get(k, "")):
            out.append(f"{k}: `{old.get(k, '')}` → `{new.get(k, '')}`")
    return out


def diff_columns(old: dict, new: dict) -> list[str]:
    ot, nt = old.get("tables", {}), new.get("tables", {})
    out = []
    for t in sorted(set(nt) - set(ot)):
        out.append(f"+ ตาราง {t[0]}.{t[1]}")
    for t in sorted(set(ot) - set(nt)):
        out.append(f"- ตาราง {t[0]}.{t[1]}")
    for t in sorted(set(ot) & set(nt)):
        oc, nc = ot[t], nt[t]
        for c in sorted(set(nc) - set(oc)):
            out.append(f"+ {t[1]}.{c} {nc[c][0]}")
        for c in sorted(set(oc) - set(nc)):
            out.append(f"- {t[1]}.{c}")
        for c in sorted(set(oc) & set(nc)):
            if oc[c] != nc[c]:
                out.append(f"~ {t[1]}.{c}: {'/'.join(oc[c])} → {'/'.join(nc[c])}")
    return out


def affected_jobs(kind: str, changed_tables: set[str] | None = None) -> list[tuple[Path, str]]:
    """งานที่ต้องรู้: ใช้ของกลางรุ่นเก่าอยู่ · ถ้าผ่าน G3 แล้ว = ต้องเปิดรอบใหม่ (รุ่นถูกล็อกหลัง G3)"""
    out = []
    for j in C.job_dirs():
        m = C.job_meta(j)
        locked = (m.get("target_lock") or {}).get("locked_at_g3")
        uses = set(t.upper() for t in (m.get("tables") or []))
        if kind == "columns" and changed_tables is not None and uses and not (uses & changed_tables):
            continue
        out.append((j, "ผ่าน G3 แล้ว → ต้อง new-round ถ้าจะใช้ของใหม่" if locked else "sync-kit เพื่อรับของใหม่"))
    return out


def intake_incoming(reason: str = "", interactive_reason: bool = True) -> list[str]:
    """ตรวจไฟล์ใน _incoming ทีละไฟล์ · ไม่ผ่าน = ของเดิมยังอยู่ ไม่ย้ายอะไร"""
    ensure_dirs()
    files = sorted(p for p in INCOMING.iterdir() if p.is_file() and p.name != ".gitkeep")
    if not files:
        C.info("ไม่มีไฟล์ใน shared/target/_incoming/")
        return []
    done = []
    for f in files:
        kind = "smart_export" if f.suffix.lower() in (".xml", ".zip") else ("columns" if f.suffix.lower() == ".csv" else "")
        if not kind:
            C.warn(f"{f.name}: ไม่รู้จักชนิด (รับ .xml/.zip = Smart Export · .csv = คอลัมน์) — ไม่ย้าย")
            continue
        if kind == "smart_export":
            info, probs = check_smart_export(f)
            if probs:
                C.fail(f"{f.name}: " + " · ".join(probs) + " — ของเดิมยังอยู่ ไม่เปลี่ยน")
                continue
            cur = current_smart_export()
            changes = diff_values(check_smart_export(cur)[0]["values"], info["values"]) if cur else ["ไฟล์แรก"]
        else:
            info, probs = check_columns(f)
            if probs:
                C.fail(f"{f.name}: " + " · ".join(probs) + " — ของเดิมยังอยู่ ไม่เปลี่ยน")
                continue
            changes = diff_columns(check_columns(COL_FILE)[0], info) if COL_FILE.exists() else [f"ไฟล์แรก ({info['rows']:,} แถว · {len(info['tables'])} ตาราง)"]
        C.ok(f"{f.name}: ตรวจผ่าน ({'Smart Export' if kind == 'smart_export' else 'คอลัมน์'})")
        for c in changes[:30]:
            C.info(f"   {c}")
        if len(changes) > 30:
            C.info(f"   … อีก {len(changes) - 30} รายการ")
        why = reason
        if not why and interactive_reason and changes != ["ไฟล์แรก"] and not changes[0].startswith("ไฟล์แรก"):
            why = C.ask("", "เหตุผลที่เปลี่ยนของกลาง (บันทึกใน CHANGELOG)", example="DBA เพิ่มคอลัมน์ CHANNEL_CD ใน ORDER_FACT", required=True, use='บันทึกใน CHANGELOG ให้ทุกงานที่ได้รับผลกระทบรู้ว่าเปลี่ยนอะไร', rec='ระบุว่าใครเปลี่ยนอะไร เช่น DBA เพิ่มคอลัมน์ X ในตาราง Y', skip='ระบบพักไว้ — การเปลี่ยนของกลางต้องมีเหตุผล', more='ของกลาง (Smart Export / ไฟล์คอลัมน์) ใช้ร่วมกันทุกงาน · เหตุผลนี้ไปอยู่ใน shared/target/CHANGELOG.md และงานที่ได้รับผลกระทบจะถูกเตือนให้ sync')
        why = why or "ตั้งค่าครั้งแรก"
        dst = place_smart_export(f, why) if kind == "smart_export" else place_columns(f, why)
        changelog(kind, "; ".join(changes[:5]) + (" …" if len(changes) > 5 else ""), why)
        done.append(kind)
        C.ok(f"ย้ายเข้า {C.rel(dst)} · ของเดิม (ถ้ามี) อยู่ใน shared/target/_archive/")
        if not changes[0].startswith("ไฟล์แรก"):
            changed_tables = None
            if kind == "columns":
                changed_tables = set()
                for c in changes:
                    tk = c.split()
                    if len(tk) < 2 or c[:1] not in "+-~":
                        continue
                    changed_tables.add(tk[2].split(".")[-1] if tk[1] == "ตาราง" and len(tk) > 2 else tk[1].split(".")[0])
            for j, what in affected_jobs(kind, changed_tables):
                C.hint(f"งานที่กระทบ: {C.rel(j)} — {what}")
    if done:
        write_source_md()
    return done


def run_update_target(args):
    """update-target: รับไฟล์จาก _incoming · --fetch-columns = ดึงคอลัมน์จากฐานเอง (เมื่อทีมอนุญาต AI ต่อฐาน)"""
    if getattr(args, "fetch_columns", False):
        t = C.team()
        if (t.get("db") or {}).get("ai_access") != "ai":
            raise C.Stop("ทีมยังไม่อนุญาตให้ระบบต่อฐาน (init ข้อ 9 = คนรัน) — เปิดไฟล์ shared/target/columns/T0_schema_columns.sql ใน DBeaver แล้ววางผลที่ shared/target/_incoming/")
        owner = (t.get("target") or {}).get("schema_name") or (t.get("target") or {}).get("work_user")
        from . import db as DB
        if not DB.fetch_columns(owner, args.reason or ""):
            raise C.Stop("ดึงคอลัมน์ไม่สำเร็จ — ดูข้อความด้านบน")
        return
    return intake_incoming(args.reason or "")
