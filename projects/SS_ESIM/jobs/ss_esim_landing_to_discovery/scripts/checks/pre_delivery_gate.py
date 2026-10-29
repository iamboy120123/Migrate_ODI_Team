#!/usr/bin/env python3
"""pre_delivery_gate.py -- ด่านตรวจก่อนส่ง SQL/XML ให้ผู้ใช้ import (ติดตั้งโดย setup_migrate.ps1 2.6.9)

ทำไมต้องมี: check_sql.py ข้ามกฎ D-R7/D-R8 เงียบๆ ถ้าไม่ได้ป้อน --ddl / --partitions และมองไม่เห็น
TRUNCATE ที่ห่อด้วย BEGIN EXECUTE IMMEDIATE ... <%=odiRef.getObjectName(...)%> ใน output/dml
ด่านนี้ตรวจซ้ำ 5 เรื่องที่เคยทำให้ import ผ่านแต่รันพัง:
  P1 config/partitions_check.csv ต้องมี (ไม่มี = FAIL ห้ามเดาว่า overwrite = TRUNCATE)
  P2 check_sql ต้องรันพร้อม --ddl และ --partitions (ไม่ครบ = FAIL)
  P3 TO_TIMESTAMP/TO_DATE ... DEFAULT ... ON CONVERSION ERROR ต้องเรียง  x DEFAULT NULL ON CONVERSION ERROR, 'fmt'
  P4 ตารางที่ partitions ไม่ว่าง (N) ห้ามถูก TRUNCATE ทั้งตาราง (D-R7)
  P5 ชื่อ object ยาวเกิน 30 ตัว = เตือนให้ตรวจ Max Table Name Length ของ Oracle technology ใน Topology
ใช้:  python scripts/checks/pre_delivery_gate.py [--root .]   (exit 1 = มี FAIL)
"""
import argparse, csv, glob, os, re, subprocess, sys

def read(p):
    with open(p, encoding='utf-8', errors='replace') as f:
        return f.read()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    res = []  # (level, id, msg)
    def add(level, pid, msg): res.append((level, pid, msg))

    part_csv = os.path.join(root, 'config', 'partitions_check.csv')
    ddl_files = sorted(glob.glob(os.path.join(root, 'input', 'oracle_ddl', '*.csv')))
    dml_dir = os.path.join(root, 'output', 'dml')
    conv_dir = os.path.join(root, 'output', 'sql', 'converted')
    check_py = os.path.join(root, 'scripts', 'checks', 'check_sql.py')

    # P1
    parts = {}
    if not os.path.isfile(part_csv):
        add('FAIL', 'P1', 'ไม่พบ config/partitions_check.csv -- รัน scripts/checks/extract_partitions.py ก่อน และตอบ I14 (DELETE vs TRUNCATE) ทีละ task')
    else:
        with open(part_csv, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                t = (r.get('TABLE_NAME') or '').strip().lower()
                if t: parts[t] = (r.get('PARTITIONS_EMPTY') or '').strip().upper()
        add('PASS', 'P1', 'partitions_check.csv มี %d ตาราง (partitions ไม่ว่าง: %d)' % (len(parts), sum(1 for v in parts.values() if v == 'N')))

    # P2
    if not os.path.isfile(check_py):
        add('FAIL', 'P2', 'ไม่พบ scripts/checks/check_sql.py')
    elif not ddl_files:
        add('FAIL', 'P2', 'ไม่พบ input/oracle_ddl/*.csv -- check_sql จะข้าม D-R5/D-R6/D-R8 (ต้องมี DDL จริงจาก Oracle)')
    elif not parts:
        add('FAIL', 'P2', 'ไม่มี partitions file -- check_sql จะข้าม D-R7')
    else:
        if len(ddl_files) > 1:
            add('WARN', 'P2', 'มี DDL หลายไฟล์ (%d) -- ส่งเข้า check_sql ได้ครั้งละไฟล์ ใช้ไฟล์แรก: %s' % (len(ddl_files), os.path.basename(ddl_files[0])))
        target = conv_dir if glob.glob(os.path.join(conv_dir, '*.sql')) else dml_dir
        if not glob.glob(os.path.join(target, '*.sql')):
            add('WARN', 'P2', 'ยังไม่มี SQL ใน output/sql/converted หรือ output/dml -- ข้าม')
        else:
            p = subprocess.run([sys.executable, check_py, target, '--ddl', ddl_files[0], '--partitions', part_csv],
                               capture_output=True, text=True, encoding='utf-8', errors='replace')
            out = (p.stdout or '') + (p.stderr or '')
            if re.search(r'no --(ddl|partitions) given', out):
                add('FAIL', 'P2', 'check_sql แจ้งว่าไม่ได้รับ --ddl/--partitions ครบ -- ผลตรวจไม่สมบูรณ์')
            errs = {}
            for m in re.finditer(r'\[ERROR\][^\n]*?\(rule (D-R\d)\)', out):
                errs[m.group(1)] = errs.get(m.group(1), 0) + 1
            other = {k: v for k, v in errs.items() if k not in ('D-R2', 'D-R3')}
            summ = ', '.join('%s=%d' % kv for kv in sorted(errs.items())) or 'ไม่มี ERROR'
            if other:
                add('FAIL', 'P2', 'check_sql (%s) ERROR นอกเหนือ D-R2/D-R3: %s -- ดู output/verify/sql_check_*.txt' % (os.path.basename(target), summ))
            else:
                add('PASS', 'P2', 'check_sql (%s) พร้อม --ddl --partitions: %s (D-R2/D-R3 = ผลของ Q8 / ตัดตอนสร้าง XML ตรวจมือแล้วเท่านั้น)' % (os.path.basename(target), summ))

    # waiver ที่ SA ตัดสินใจแล้ว: config/gate_waivers.txt  บรรทัดละรายการ  เช่น  P4 020000 | SA 2026-10-12 Q14=A
    waivers = []
    wf = os.path.join(root, 'config', 'gate_waivers.txt')
    if os.path.isfile(wf):
        for line in read(wf).splitlines():
            m = re.match(r'\s*(P\d)\s+(\S+)\s*\|\s*(.+)$', line)
            if m: waivers.append((m.group(1), m.group(2), m.group(3).strip()))
    def waived(pid, fname):
        return any(w[0] == pid and w[1] in fname for w in waivers)

    # รวม SQL ที่จะส่ง
    files = sorted(glob.glob(os.path.join(dml_dir, '*.sql')) + glob.glob(os.path.join(conv_dir, '*.sql')))
    texts = {f: read(f) for f in files}

    # P3
    bad = []
    pat3 = re.compile(r"(?is),\s*'[^']*'\s+DEFAULT\s+\w+\s+ON\s+CONVERSION\s+ERROR")
    for f, t in texts.items():
        t2 = re.sub(r'(?m)--[^\n]*', '', t)
        n = len(pat3.findall(t2))
        if n and not waived('P3', f): bad.append('%s/%s (%d จุด)' % (os.path.basename(os.path.dirname(f)), os.path.basename(f)[:60], n))
    if bad:
        add('FAIL', 'P3', "ลำดับ DEFAULT ... ON CONVERSION ERROR ผิด (ต้องเป็น x DEFAULT NULL ON CONVERSION ERROR, 'fmt' ไม่ใช่ 'fmt' DEFAULT ... -> ORA-00907): " + '; '.join(bad))
    elif texts:
        add('PASS', 'P3', 'ลำดับ DEFAULT ... ON CONVERSION ERROR ถูกทุกไฟล์')

    # P4
    trunc_pat = re.compile(r'(?is)TRUNCATE\s+TABLE\s+(?:<%=\s*odiRef\.getObjectName\(\s*"L"\s*,\s*"(\w+)"[^%]*%>|(?:\w+\.)?(\w+))')
    viol = []
    for f, t in texts.items():
        t2 = re.sub(r'(?m)--[^\n]*', '', t)
        for m in trunc_pat.finditer(t2):
            name = (m.group(1) or m.group(2) or '').lower()
            if parts.get(name) == 'N' and not waived('P4', f):
                viol.append('%s TRUNCATE %s' % (os.path.basename(f), name))
    if waivers:
        add('INFO', 'P4', 'มี waiver %d รายการใน config/gate_waivers.txt (ต้องมีเหตุผลและวันที่ SA ทุกบรรทัด)' % len(waivers))
    if viol:
        add('FAIL', 'P4', 'D-R7: ตารางที่ partitions ไม่ว่างถูก TRUNCATE ทั้งตาราง (Spark ลบเฉพาะ partition) ต้องใช้ DELETE ตาม partition หรือให้ SA ตัดสินใจ I14 เป็นลายลักษณ์อักษร: ' + '; '.join(sorted(set(viol))) + ' -- ถ้า SA ตั้งใจจริง ให้บันทึกใน config/gate_waivers.txt: P4 <เลขtask> | SA <วันที่> <เหตุผล>')
    elif parts:
        add('PASS', 'P4', 'ไม่พบ TRUNCATE ทั้งตารางบนตารางที่ partitions ไม่ว่าง')

    # P5
    names = set()
    for t in texts.values():
        t2 = re.sub(r'(?m)--[^\n]*', '', t)
        names.update(re.findall(r'getObjectName\(\s*"L"\s*,\s*"(\w+)"', t2))
        names.update(re.findall(r'(?i)\b(?:dssdev|\w+)\.(\w{25,})\b', t2))
    long_names = sorted({n for n in names if len(n) > 30}, key=len, reverse=True)
    if long_names:
        add('WARN', 'P5', 'มีชื่อ object ยาวกว่า 30 ตัว (ยาวสุด %d: %s) -- ก่อนรันให้ตรวจ Topology > Technologies > Oracle > Max Table Name Length ว่า >= %d ถ้าใช้ odiRef.getObjectName ชื่อจะถูกตัดแล้ว ORA-00942' % (len(long_names[0]), long_names[0], len(long_names[0])))
    elif names:
        add('PASS', 'P5', 'ชื่อ object ทุกตัวไม่เกิน 30 ตัว')

    # P6 เตือนเสมอ
    add('INFO', 'P6', 'ก่อน Smart Import (ทำครั้งเดียวตอนจบ): ตรวจ Designer ว่ามี project รหัสเดียวกันใน repository แล้วหรือไม่ (ODI-10244) -- ของที่ AI ต้องใช้ต้องครบก่อน build (รัน /inputs = scripts/checks/check_inputs.py) ไม่มีรอบ "import ลองดูก่อน"')

    w = max(len(x[1]) for x in res)
    for lv, pid, msg in res:
        print('[%-4s] %s  %s' % (lv, pid, msg))
    fails = sum(1 for x in res if x[0] == 'FAIL')
    print('\nสรุป: FAIL=%d WARN=%d PASS=%d' % (fails, sum(1 for x in res if x[0] == 'WARN'), sum(1 for x in res if x[0] == 'PASS')))
    if fails:
        print('ห้ามบอกผู้ใช้ว่า "พร้อม import/รัน" จนกว่า FAIL = 0')
    return 1 if fails else 0

if __name__ == '__main__':
    sys.exit(main())