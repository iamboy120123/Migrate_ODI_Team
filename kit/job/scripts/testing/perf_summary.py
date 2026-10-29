"""
perf_summary.py — ใบรายงานความเร็ว (ขั้น 05.3) → status/SUMMARY_05_PERFORMANCE.md

ข้อมูลเข้า:
  input/run_results/rp05_perf/*.csv  เวลาต่อ step จาก log ของ ODI · คอลัมน์ที่อ่าน (ชื่อไม่สนตัวพิมพ์):
      STEP_NAME · STEP_BEG / START_TIME · STEP_END / END_TIME · STEP_DUR / DURATION_SEC (วินาที) · NB_ROW / ROWS
  config/perf_baseline.json          {"blendata_minutes": 42, "test_rows": 1200000, "prod_rows": 40000000, "per_step": {"<step>": นาที}}
  เกณฑ์ของทีม shared/team.json       perf.batch_window_min · perf.slower_pct
ระดับ: ดี · ต้องดู · ไม่ผ่าน (กรณีเดียวที่บล็อก = เกินกรอบเวลา batch) · ไม่มีเกณฑ์ = รายงานตัวเลขดิบให้คนตัดสิน
ข้อมูล DEV มักน้อยกว่า PROD มาก — รายงานบอกขนาดข้อมูลที่ใช้ทดสอบเสมอ

Usage:
    python scripts/testing/perf_summary.py --make-pack --session 48213   # สร้าง run_packs/rp05_perf/ (query log ของ ODI · ต้องยืนยันชื่อตาราง)
    python scripts/testing/perf_summary.py                               # อ่านผลแล้วเขียนใบรายงาน
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]


def ws_team():
    for p in [ROOT, *ROOT.parents]:
        if (p / "workspace.json").exists():
            try:
                return json.loads((p / "shared/team.json").read_text(encoding="utf-8"))
            except Exception:
                return {}
    return {}


def make_pack(sess: str):
    cfg = json.loads((ROOT / "config/config.json").read_text(encoding="utf-8"))
    wr = (cfg.get("odi") or {}).get("work_repo_schema") or "<WORK_REPO_SCHEMA>"
    d = ROOT / "run_packs/rp05_perf"
    d.mkdir(parents=True, exist_ok=True)
    (d / "P1_step_times.sql").write_text(
        f"-- เวลาต่อ step ของ session {sess} จาก log ของ ODI (work repository) · SELECT อย่างเดียว\n"
        "-- ⚠️ ชื่อตาราง/คอลัมน์ SNP_SESS_STEP / SNP_STEP_LOG ยังไม่ยืนยันกับ ODI 14c ของทีม — error = บอก AI พร้อมข้อความ ไม่ต้องเดา\n"
        "-- ทางเลือก: ODI Operator → session → ดูเวลาต่อ step แล้ว export / พิมพ์เป็น CSV คอลัมน์เดียวกัน\n"
        "SELECT ss.step_name, sl.step_beg, sl.step_end, sl.step_dur, sl.nb_row\n"
        f"FROM   {wr}.snp_sess_step ss\n"
        f"JOIN   {wr}.snp_step_log sl ON sl.sess_no = ss.sess_no AND sl.nno = ss.nno\n"
        f"WHERE  ss.sess_no = {int(sess)}\n"
        "ORDER  BY sl.step_beg\n", encoding="utf-8")
    print("✅ run_packs/rp05_perf/P1_step_times.sql — รันด้วย run_pack.py rp05_perf (ตามโหมด) หรือ DBeaver แล้ววาง CSV ที่ input/run_results/rp05_perf/")


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def ts(v):
    for f in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(str(v).strip()[:26], f)
        except ValueError:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-pack", action="store_true")
    ap.add_argument("--session")
    a = ap.parse_args()
    if a.make_pack:
        if not a.session:
            raise SystemExit("[ERROR] ใส่ --session <เลข session ของ ODI ที่รันทดสอบ> (ดูใน Operator)")
        return make_pack(a.session)
    files = sorted((ROOT / "input/run_results/rp05_perf").glob("*.csv"))
    if not files:
        raise SystemExit("[ERROR] ยังไม่มี input/run_results/rp05_perf/*.csv — สร้าง pack ด้วย --make-pack --session <เลข>")
    steps = []
    for f in files:
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                r = {k.strip().upper(): v for k, v in r.items() if k}
                name = r.get("STEP_NAME") or r.get("STEP") or "?"
                dur = num(r.get("STEP_DUR") or r.get("DURATION_SEC") or "")
                if dur is None:
                    b, e = ts(r.get("STEP_BEG") or r.get("START_TIME") or ""), ts(r.get("STEP_END") or r.get("END_TIME") or "")
                    dur = (e - b).total_seconds() if b and e else None
                rows = num(r.get("NB_ROW") or r.get("ROWS") or "")
                steps.append((name, dur, rows))
    if not steps:
        raise SystemExit("[ERROR] CSV ไม่มีแถว (0 แถว ไม่นับว่าผ่าน) — ตรวจ session / เงื่อนไข")
    total_min = sum(d or 0 for _, d, _ in steps) / 60
    base = json.loads((ROOT / "config/perf_baseline.json").read_text(encoding="utf-8")) if (ROOT / "config/perf_baseline.json").exists() else {}
    perf = (ws_team().get("perf") or {})
    bw, pct, bl = perf.get("batch_window_min"), perf.get("slower_pct"), base.get("blendata_minutes")
    notes = []
    if bw and total_min > bw:
        level = "ไม่ผ่าน"
        notes.append(f"รวม {total_min:.1f} นาที เกินกรอบเวลา batch {bw} นาที — บล็อกการส่ง")
    elif bl and pct is not None and total_min > bl * (1 + pct / 100):
        level = "ต้องดู"
        notes.append(f"ช้ากว่า Blendata ({bl} นาที) เกิน {pct}% แต่ยังอยู่ในกรอบ batch")
    elif "🟡 ความเร็ว" in (ROOT / "status/SQL_REVIEW.md").read_text(encoding="utf-8") if (ROOT / "status/SQL_REVIEW.md").exists() else False:
        level = "ต้องดู"
        notes.append("มีคำเตือนรูปแบบ SQL ที่ช้าใน status/SQL_REVIEW.md")
    elif not bw and not (bl and pct is not None):
        level = "ไม่มีเกณฑ์ (ตัวเลขดิบ ให้คนตัดสิน)"
    else:
        level = "ดี"
    tr, pr = base.get("test_rows"), base.get("prod_rows")
    L = [f"# สรุปขั้น 05 · ความเร็ว — {ROOT.name}", "",
         f"รัน {dt.datetime.now():%Y-%m-%d %H:%M} · ไฟล์ {', '.join(f.name for f in files)}" +
         (f" · ข้อมูลทดสอบ {tr:,.0f} แถว" if tr else " · ข้อมูลทดสอบ: ไม่ระบุ (ใส่ test_rows ใน config/perf_baseline.json)") + (f" (PROD ประมาณ {pr:,.0f})" if pr else ""), "",
         f"ระดับ: **{level}**", "",
         f"- เวลารวม: {total_min:.1f} นาที · Blendata เดิม: {bl if bl else 'ไม่มีข้อมูล'} นาที · กรอบ batch: {bw if bw else 'ไม่กำหนด'} นาที · ช้าได้: {pct if pct is not None else 'ไม่กำหนด'}%",
         *[f"- {n}" for n in notes], "",
         "| step ที่ช้าสุด | เวลา (วินาที) | แถว | ข้อสังเกต |", "|---|---|---|---|"]
    for name, d, rows in sorted(steps, key=lambda x: -(x[1] or 0))[:8]:
        per = (base.get("per_step") or {}).get(name)
        d_s = f"{d:.0f}" if d is not None else "-"
        r_s = f"{rows:,.0f}" if rows is not None else "-"
        L.append(f"| {name} | {d_s} | {r_s} | {('Blendata ' + str(per) + ' นาที') if per else ''} |")
    L += ["", "> ผลบน DEV ใช้ดูแนวโน้ม · ข้อมูลน้อยกว่า PROD มาก — ตัดสินบล็อกเฉพาะเกินกรอบเวลา batch"]
    (ROOT / "status/SUMMARY_05_PERFORMANCE.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"ระดับ: {level} · รวม {total_min:.1f} นาที → status/SUMMARY_05_PERFORMANCE.md")
    sys.exit(1 if level == "ไม่ผ่าน" else 0)


if __name__ == "__main__":
    main()
