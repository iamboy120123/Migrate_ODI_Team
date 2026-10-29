"""
compare_results.py  (D2/D3, 2026-09-30) — เทียบผล valid/reject ของ Blendata (Spark) กับ ODI (Oracle) ระดับแถว

ใช้เมื่อ: ตัดสินปิด gate G5.M2 (ขั้น 4 ของ test-method) — ต้องมี spec และ Q ที่ปิดแล้วรองรับส่วนต่างที่ยอมรับ

Input : CSV 2 ไฟล์ที่มีคอลัมน์ TBL (VALID/REJECT) + คอลัมน์ของตาราง transaction (ชื่อคอลัมน์ตัวเล็ก/ใหญ่ได้)
        - Blendata : ผลของ B2/B4 (Spark SQL)       - Oracle : ผลของ O1/O3 (DBeaver)
Output: <out>/D2_REPORT.md, <out>/D2_DIFF.csv · exit 0 = ไม่มี diff ที่ยังไม่อธิบาย, 1 = มี

Usage:
    python compare_results.py --blendata B.csv --oracle O.csv --out out_dir [--label "D2 seed"] [--spec spec.json]

Spec (kit 2.3.0): คอลัมน์ key / compare / ignore / ts / num และกฎส่วนต่างที่ยอมรับ อ่านจาก --spec
หรือ `config/compare_spec.json` (ถ้ามี) — ตัวอย่าง: `compare_spec.example.json`
ถ้าไม่มี spec: compare = คอลัมน์ที่มีทั้งสองไฟล์ และต้องระบุ --key

หลักการ
- key ของแถว = invoice_no | cdr_filepath | process_date (วินาที)  — T1/T5 (invoice+file ซ้ำ) แยกกันด้วย process_date
- normalize: trim, NULL/''/' '(DBeaver) = ∅, timestamp → YYYY-MM-DD HH:MM:SS, ตัวเลข → float
- ไม่เทียบคอลัมน์ non-deterministic / ที่ยอมรับว่าต่าง: cdr_id, create_by (Q7), workflow_process_date, cdr_filedate (= วันที่รัน)
- ส่วนต่างที่ยอมรับแล้ว (ACCEPTED) — ต้องมี Q ที่ปิดแล้วรองรับ:
    Q6 : Blendata ผ่าน (COM หรือ status อื่นที่ไม่ใช่ MAN) แต่ Oracle = MAN และทุกฟิลด์ใน filter_error ของ Oracle
         เป็น ∅ ในแถวของ Blendata (ค่า '' ใน landing → Oracle ถือเป็น NULL)
- ส่วนต่างที่อธิบายได้จากวิธีทดสอบ (EXPLAINED) — เฉพาะ D3 backtest:
    HIST_DUP : Blendata = DUP แต่ Oracle = COM และ chk_duplicate อยู่ในไฟล์ --history-dup
               (valid ของ Blendata ก่อนช่วงที่ backtest — Oracle Dev ไม่มีประวัตินี้)
"""
import argparse
import csv
import os
import re
from collections import Counter, defaultdict
from datetime import datetime

IGNORE = {"tbl"}
COMPARE = []          # ว่าง = คอลัมน์ที่มีทั้งสองไฟล์
KEY = []
TS_COLS = set()
NUM_COLS = set()
# กฎ Q6 (ค่า '' ใน landing → Oracle ถือเป็น NULL → MAN): field ที่ filter_error อ้าง → คอลัมน์ในผลลัพธ์
Q6_FIELD = None       # None = ปิดกฎ
STATUS_MAN, STATUS_DUP, STATUS_OK = "MAN", "DUP", "COM"


def load_spec(path, key_arg):
    global IGNORE, COMPARE, KEY, TS_COLS, NUM_COLS, Q6_FIELD, STATUS_MAN, STATUS_DUP, STATUS_OK
    import json
    if not path:
        dflt = os.path.join(os.getcwd(), "input", "compare_spec.json")   # คัดลอกจาก references/example/compare_spec.example.json
        path = dflt if os.path.exists(dflt) else None
    sp = json.load(open(path, encoding="utf-8")) if path else {}
    IGNORE = {c.lower() for c in sp.get("ignore", [])} | {"tbl"}
    COMPARE = [c.lower() for c in sp.get("compare", [])]
    KEY = [c.lower() for c in (key_arg.split(",") if key_arg else sp.get("key", []))]
    TS_COLS = {c.lower() for c in sp.get("ts_cols", [])}
    NUM_COLS = {c.lower() for c in sp.get("num_cols", [])}
    acc = sp.get("accept", {})
    Q6_FIELD = acc.get("q6_empty_string_man", {}).get("field_map") if acc.get("q6_empty_string_man", {}).get("enabled") else None
    st = sp.get("status_values", {})
    STATUS_MAN, STATUS_DUP, STATUS_OK = st.get("man", "MAN"), st.get("dup", "DUP"), st.get("ok", "COM")
    if not KEY:
        raise SystemExit("ต้องระบุ key (--key col1,col2 หรือ spec.key)")
    return path


NULL = "∅"


def norm(col, v):
    if v is None:
        return NULL
    v = str(v).strip()
    if v == "" or v.upper() in ("NULL", "[NULL]", "NONE"):
        return NULL
    if col in TS_COLS:
        v2 = re.sub(r"[T]", " ", v)
        v2 = re.sub(r"(\.\d*)?(\s*[+-]\d{2}:?\d{2}|Z)?$", "", v2)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d-%b-%y %I.%M.%S %p", "%d/%m/%Y %H:%M:%S"):
            try:
                return datetime.strptime(v2, fmt).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        return v
    if col in NUM_COLS:
        try:
            f = float(v)
            return str(int(f)) if f == int(f) else repr(f)
        except ValueError:
            return v
    return v


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        d = {k.strip().strip('"').lower(): v for k, v in r.items() if k}
        if "tbl" not in d:
            raise SystemExit(f"{path}: ไม่มีคอลัมน์ TBL (VALID/REJECT)")
        out.append({c: norm(c, d.get(c)) for c in set(COMPARE) | set(d.keys())})
    return out


def key(r):
    return "|".join(str(r.get(c)) for c in KEY)


def q6_accepted(b, o):
    if Q6_FIELD is None:
        return False
    if o.get("status") != STATUS_MAN or b.get("status") == STATUS_MAN:
        return False
    fields = [x.strip() for x in (o.get("filter_error") or "").split("|") if x.strip() and x.strip() != NULL]
    fields = [f.replace(" is NULL", "").strip() for f in fields]
    if not fields:
        return False
    return all(b.get(Q6_FIELD.get(f, f), NULL) == NULL for f in fields)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blendata", required=True)
    ap.add_argument("--oracle", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="D2")
    ap.add_argument("--history-dup", help="CSV ที่มีคอลัมน์ chk_duplicate ของ valid ก่อนช่วง backtest (D3)")
    ap.add_argument("--spec", help="JSON ของคอลัมน์/กฎ (default: config/compare_spec.json)")
    ap.add_argument("--key", help="คอลัมน์ key คั่นด้วย , (ทับ spec)")
    a = ap.parse_args()
    global COMPARE
    spec_path = load_spec(a.spec, a.key)
    os.makedirs(a.out, exist_ok=True)
    B, O = load(a.blendata), load(a.oracle)
    if not COMPARE:
        common = set(B[0].keys()) & set(O[0].keys()) if B and O else set()
        COMPARE = ["tbl", "status"] + sorted(common - {"tbl", "status"})
    bk, ok_ = defaultdict(list), defaultdict(list)
    for r in B:
        bk[key(r)].append(r)
    for r in O:
        ok_[key(r)].append(r)
    hist = set()
    if a.history_dup:
        with open(a.history_dup, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                d = {k.strip().strip('"').lower(): (v or "").strip() for k, v in r.items() if k}
                if d.get("chk_duplicate"):
                    hist.add(d["chk_duplicate"])
    diffs, accepted, matched = [], [], 0
    col_counter = Counter()
    for k in sorted(set(bk) | set(ok_)):
        bs, os_ = bk.get(k, []), ok_.get(k, [])
        if len(bs) != len(os_):
            if len(bs) == 1 and len(os_) == 1:
                pass
            else:
                diffs.append({"key": k, "type": f"COUNT blendata={len(bs)} oracle={len(os_)}", "column": "", "blendata": "", "oracle": ""})
                col_counter["(row count)"] += 1
                continue
        for b, o in zip(bs, os_):
            if q6_accepted(b, o):
                accepted.append({"key": k, "rule": "Q6", "blendata": f"{b['tbl']}/{b['status']}", "oracle": f"{o['tbl']}/{o['status']}",
                                 "note": o.get("filter_error")})
                continue
            if b.get("status") == STATUS_DUP and o.get("status") == STATUS_OK and b.get("chk_duplicate") in hist:
                accepted.append({"key": k, "rule": "HIST_DUP", "blendata": f"{b['tbl']}/{b['status']}", "oracle": f"{o['tbl']}/{o['status']}",
                                 "note": "duplicate กับ valid ก่อนช่วง backtest"})
                continue
            row_diff = False
            for c in COMPARE:
                if c in IGNORE and c != "tbl":
                    continue
                if b.get(c, NULL) != o.get(c, NULL):
                    row_diff = True
                    col_counter[c] += 1
                    diffs.append({"key": k, "type": "VALUE", "column": c, "blendata": b.get(c, NULL), "oracle": o.get(c, NULL)})
            matched += 0 if row_diff else 1
    only_b = [k for k in bk if k not in ok_]
    only_o = [k for k in ok_ if k not in bk]
    for k in only_b:
        diffs.append({"key": k, "type": "ONLY_BLENDATA", "column": "", "blendata": f"{bk[k][0]['tbl']}/{bk[k][0]['status']}", "oracle": ""})
    for k in only_o:
        diffs.append({"key": k, "type": "ONLY_ORACLE", "column": "", "blendata": "", "oracle": f"{ok_[k][0]['tbl']}/{ok_[k][0]['status']}"})
    diffs = [d for d in diffs if not (d["type"] == "COUNT" )]
    with open(os.path.join(a.out, "D2_DIFF.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["key", "type", "column", "blendata", "oracle"])
        w.writeheader(); w.writerows(diffs)
    tb, to = Counter(f"{r['tbl']}/{r['status']}" for r in B), Counter(f"{r['tbl']}/{r['status']}" for r in O)
    lines = [f"# {a.label} — Blendata vs Oracle (row-level)", "",
             f"Blendata: `{os.path.basename(a.blendata)}` ({len(B)} แถว) · Oracle: `{os.path.basename(a.oracle)}` ({len(O)} แถว)", "",
             "| ผล | จำนวน |", "|---|---|",
             f"| ✅ ตรงกันทุกคอลัมน์ | {matched} |",
             f"| 🟡 ต่างแบบที่ยอมรับ/อธิบายได้ (Q6, HIST_DUP) | {len(accepted)} |",
             f"| ❌ ค่าต่าง (แถว/คอลัมน์) | {sum(1 for d in diffs if d['type']=='VALUE')} |",
             f"| ❌ มีเฉพาะ Blendata | {len(only_b)} |",
             f"| ❌ มีเฉพาะ Oracle | {len(only_o)} |", "",
             "## สรุปตาราง/สถานะ", "", "| tbl/status | Blendata | Oracle |", "|---|---|---|"]
    for s in sorted(set(tb) | set(to)):
        lines.append(f"| {s} | {tb.get(s, 0)} | {to.get(s, 0)} |")
    if col_counter:
        lines += ["", "## คอลัมน์ที่ต่าง", "", "| คอลัมน์ | จำนวนแถว |", "|---|---|"] + [f"| {c} | {n} |" for c, n in col_counter.most_common()]
    if accepted:
        lines += ["", "## ส่วนต่างที่ยอมรับ", "", "| key | กฎ | Blendata | Oracle | filter_error (Oracle) |", "|---|---|---|---|---|"]
        lines += [f"| {x['key']} | {x['rule']} | {x['blendata']} | {x['oracle']} | {x['note']} |" for x in accepted]
    if diffs:
        lines += ["", "## Diff (20 รายการแรก — ทั้งหมดใน D2_DIFF.csv)", "", "| key | type | column | Blendata | Oracle |", "|---|---|---|---|---|"]
        lines += [f"| {d['key']} | {d['type']} | {d['column']} | {d['blendata']} | {d['oracle']} |" for d in diffs[:20]]
    lines += ["", f"ไม่เทียบ: {', '.join(sorted(IGNORE - {'tbl'}))} (non-deterministic / ส่วนต่างที่ยอมรับ) · key: {' | '.join(KEY)} · spec: `{os.path.basename(spec_path) if spec_path else '-'}`",
              "", f"**RESULT: {'✅ PASS — diff = 0 (ยกเว้นส่วนต่างที่ยอมรับ)' if not diffs else '❌ FAIL — มี diff ที่ยังไม่อธิบาย'}**"]
    open(os.path.join(a.out, "D2_REPORT.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    print(lines[-1])
    raise SystemExit(0 if not diffs else 1)


if __name__ == "__main__":
    main()
