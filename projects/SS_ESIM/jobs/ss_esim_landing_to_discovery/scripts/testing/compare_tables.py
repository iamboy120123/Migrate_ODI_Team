#!/usr/bin/env python3
"""compare_tables.py - compare an Oracle table export (CSV) with the reference CSV from spark_reference_run.py.
USE WHEN: quick check during development, no spec needed (step 3 of test-method; the gate decision is compare_results.py).  Reads two CSV files only - no database access.

USAGE
  python3 compare_tables.py --ref ref_out/01_round1/99_final_tb_x.csv --actual oracle_tb_x.csv \
      --ignore create_by,process_date,cdr_id,filter_dtm [--key iccid,eid] [--case-insensitive-headers]

HOW IT COMPARES
  * columns are matched by name (case-insensitive); columns missing on one side are reported
  * values are normalised before comparing:  NULL == '' (Oracle stores '' as NULL) ; '10000049.0' == '10000049' ;
    timestamps compared to the second ('2026-08-27 10:00:00.000000' == '2026-08-27 10:00:00') ; booleans true/false == 1/0 ;
    surrounding whitespace is NOT stripped (a value with spaces must stay different - that is a real finding)
  * without --key : multiset comparison of whole rows (row order never matters)
  * with --key    : rows are paired by key, then differing columns are listed per key
  * prints PASS / FAIL and exits 0 / 1
"""
import argparse, csv, re, sys
from collections import Counter, defaultdict


def norm(v):
    if v is None: return None
    s = v
    if s == "" or s.upper() == "NULL" or s == "\\N": return None
    if re.fullmatch(r"-?\d+\.0+", s): return s.split(".")[0]
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(\.\d+)?(\s*[+-]\d{2}:?\d{2}|Z)?", s)
    if m: return m.group(1) + " " + m.group(2)
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) 00:00:00", s)
    if s.lower() == "true": return "1"
    if s.lower() == "false": return "0"
    return s


def read(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f); h = next(rd)
        return [x.strip().lower() for x in h], list(rd)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", required=True); ap.add_argument("--actual", required=True)
    ap.add_argument("--key", default=""); ap.add_argument("--ignore", default="")
    ap.add_argument("--show", type=int, default=15)
    a = ap.parse_args()
    ignore = {c.strip().lower() for c in a.ignore.split(",") if c.strip()}
    key = [c.strip().lower() for c in a.key.split(",") if c.strip()]
    hr, rr = read(a.ref); ha, ra = read(a.actual)
    common = [c for c in hr if c in ha and c not in ignore]
    only_ref = [c for c in hr if c not in ha and c not in ignore]; only_act = [c for c in ha if c not in hr and c not in ignore]
    print("rows: ref=%d actual=%d | compared columns=%d | ignored=%s" % (len(rr), len(ra), len(common), sorted(ignore) or "-"))
    if only_ref: print("columns only in REF   :", only_ref)
    if only_act: print("columns only in ACTUAL:", only_act)
    ir = {c: hr.index(c) for c in common}; ia = {c: ha.index(c) for c in common}
    tr = [tuple(norm(r[ir[c]]) for c in common) for r in rr]
    ta = [tuple(norm(r[ia[c]]) for c in common) for r in ra]
    ok = len(rr) == len(ra) and not only_ref
    if not key:
        cr, ca = Counter(tr), Counter(ta)
        miss, extra = cr - ca, ca - cr
        if miss or extra: ok = False
        print("rows only in REF   : %d" % sum(miss.values()))
        for r, n in list(miss.items())[:a.show]: print("   -", dict(zip(common, r)), "x%d" % n)
        print("rows only in ACTUAL: %d" % sum(extra.values()))
        for r, n in list(extra.items())[:a.show]: print("   +", dict(zip(common, r)), "x%d" % n)
    else:
        for k in key:
            if k not in common: sys.exit("key column %s not in both files / is ignored" % k)
        ki = [common.index(k) for k in key]
        def group(rows):
            g = defaultdict(list)
            for r in rows: g[tuple(r[i] for i in ki)].append(r)
            return g
        gr, ga = group(tr), group(ta)
        for k in sorted(set(gr) | set(ga), key=lambda x: tuple(str(i) for i in x)):
            lr, la = gr.get(k, []), ga.get(k, [])
            if len(lr) != len(la):
                ok = False; print("KEY %s: ref has %d row(s), actual has %d" % (k, len(lr), len(la))); continue
            for x, y in zip(sorted(lr, key=str), sorted(la, key=str)):
                d = [(c, x[i], y[i]) for i, c in enumerate(common) if x[i] != y[i]]
                if d:
                    ok = False; print("KEY %s differs:" % (k,)); [print("     %-22s ref=%r actual=%r" % t) for t in d]
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
