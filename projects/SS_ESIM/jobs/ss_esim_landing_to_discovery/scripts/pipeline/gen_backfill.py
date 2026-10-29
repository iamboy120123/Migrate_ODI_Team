"""
gen_backfill.py
----------------
Runbook Phase 8 prep — History Backfill Pack (Q17 = ย้ายเต็ม 3 ตาราง)

ทำไมต้องมี:
    040000 dedup ด้วย LEFT JOIN (valid ∪ temp).chk_duplicate แบบไม่มีขอบเขตเวลา และ 020000/040000
    อ่าน MAX(checkpoint_partition) — ถ้า Oracle เริ่มจากตารางว่าง ODI จะ (1) มองทุก ICCID เก่าเป็น MAP ใหม่
    (2) ประมวลผล landing ย้อนหลังทั้งหมด -> ต้องย้าย history + state ก่อน parallel run

ตารางที่ย้าย (คำนวณจาก dml manifest):
    history : target ที่ไม่มี task ใด TRUNCATE (append/merge) -> valid, reject, temp
    state   : target ที่ถูก overwrite และชื่อลงท้าย _CHECKPOINT -> checkpoint (เล็ก, ย้ายทั้งตาราง)

Output: output/backfill/
    00_README.md                 ลำดับรัน + ตัวแปร
    01_baseline_spark.sql        จด baseline ณ T_snap (Blendata)
    02_export_spark.sql          SELECT สำหรับ export (column order = Oracle DDL, timestamp เป็น string)
    03_pre_load_oracle.sql       guard ตารางว่าง + ปิด lookup index ชั่วคราว
    04_load_<table>.ctl          SQL*Loader control file (direct path)
    05_post_load_oracle.sql      rebuild index + gather stats + integrity check
    06_reconcile_{oracle,spark}.sql  ผลลัพธ์ shape เดียวกัน เอาไป diff
    07_seed_state_oracle.sql     reset state ที่ไม่ได้ย้าย (workflow_status, temp staging)
    08_cutover_delta_oracle.sql  ใช้ตอน CUTOVER_RUNBOOK C5: ลบ output ของ ODI shadow แล้วโหลด delta

Usage:
    python scripts/pipeline/gen_backfill.py [--config config/config.json]
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SEP_HEX = "1F"          # ASCII unit separator - err_msg/filter_error มี '|' และ ',' อยู่แล้ว ใช้เป็น delimiter ไม่ได้
TS_SPARK = "yyyy-MM-dd HH:mm:ss.SSSSSS"
TS_ORA = "YYYY-MM-DD HH24:MI:SS.FF6"


def parse_ddl(ddl_path: Path) -> dict:
    """{TABLE_SHORT: [(col, type), ...]} จาก 01_create_tables.sql"""
    out = {}
    text = ddl_path.read_text(encoding="utf-8")
    for m in re.finditer(r"CREATE TABLE\s+(?:\w+\.)?(\w+)\s*\((.*?)\n\);", text, flags=re.S):
        cols = []
        for line in m.group(2).splitlines():
            line = line.split("--")[0].strip().rstrip(",")
            mm = re.match(r"(\w+)\s+(\w+(?:\(\d+(?:,\d+)?\))?)", line)
            if mm:
                cols.append((mm.group(1).upper(), mm.group(2).upper()))
        out[m.group(1).upper()] = cols
    return out


def spark_expr(col: str, typ: str) -> str:
    c = col.lower()
    if typ.startswith(("TIMESTAMP", "DATE")):
        return f"date_format({c}, '{TS_SPARK}') AS {c}"
    return c


def ctl_field(col: str, typ: str) -> str:
    if typ.startswith(("TIMESTAMP", "DATE")):
        return f'  {col:28s} TIMESTAMP "{TS_ORA}" NULLIF {col}=BLANKS'
    if typ.startswith("VARCHAR2"):
        n = re.search(r"\((\d+)\)", typ)
        return f"  {col:28s} CHAR({n.group(1) if n else 4000})"
    return f"  {col:28s} DECIMAL EXTERNAL NULLIF {col}=BLANKS"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    manifest = json.loads(Path(config["paths"]["dml_manifest"]).read_text(encoding="utf-8"))
    # entry readonly (เช่น 000000 precheck) ไม่ได้เขียน target -> ไม่นับเป็น target table
    manifest = [e for e in manifest if not e.get("readonly")]
    ddl_path = Path("output/ddl/01_create_tables.sql")
    if not ddl_path.exists():
        sys.exit("[ERROR] ไม่พบ output/ddl/01_create_tables.sql - รัน gen_ddl.py ก่อน")
    ddl = parse_ddl(ddl_path)
    project = config.get("project_name", "MIGRATION")
    work_user = ((config.get("odi") or {}).get("work_user") or "<work_user>")
    stamp = datetime.now().isoformat(timespec="seconds")
    out = Path("output/backfill"); out.mkdir(parents=True, exist_ok=True)

    targets, truncated = {}, set()
    for e in manifest:
        full = e["target_table"].upper()
        short = full.rsplit(".", 1)[-1]
        targets[short] = full
        if any("TRUNCATE" in s.upper() for s in e.get("steps", [])):
            truncated.add(short)
    history = sorted(t for t in targets if t not in truncated)
    state = sorted(t for t in truncated if t.endswith("_CHECKPOINT"))
    reset = sorted(t for t in truncated if t not in state)
    for t in history + state:
        if t not in ddl:
            sys.exit(f"[ERROR] {t} ไม่อยู่ใน 01_create_tables.sql")
    spark_name = {t: t.lower() for t in targets}   # Blendata ใช้ชื่อตารางตัวเล็กไม่มี schema
    has_wpd = {t: any(c == "WORKFLOW_PROCESS_DATE" for c, _ in ddl[t]) for t in history}

    # ---------- 01 baseline ----------
    b = [f"-- 01_baseline_spark.sql  (Blendata / Spark SQL, generated {stamp})",
         "-- รัน ณ T_snap แล้วจดค่าลง 00_README.md ตาราง Baseline — ${SNAP_WPD} = MAX(workflow_process_date) ของ run",
         "-- ที่ success ล่าสุด (ต้องเป็นรอบที่จบแล้ว ไม่ใช่รอบที่กำลังรัน)\n",
         "-- [B0] run ล่าสุดต้อง success ก่อนจด",
         "SELECT success, running, workflow_process_date FROM "
         + next((t.lower() for t in targets if t.endswith("_WORKFLOW_STATUS")), "<workflow_status_table>") + ";\n"]  # K3
    for t in history:
        extra = ", MAX(workflow_process_date) AS max_wpd" if has_wpd[t] else ""
        b.append(f"SELECT '{t}' AS tbl, COUNT(*) AS cnt, COUNT(DISTINCT chk_duplicate) AS dist_chk_dup{extra}\n"
                 f"FROM   {spark_name[t]};")
    for t in state:
        b.append(f"SELECT '{t}' AS tbl, COUNT(*) AS cnt, MIN(checkpoint_partition) AS min_ckpt, "
                 f"MAX(checkpoint_partition) AS max_ckpt\nFROM   {spark_name[t]};")
    (out / "01_baseline_spark.sql").write_text("\n".join(b) + "\n", encoding="utf-8")

    # ---------- 02 export ----------
    x = [f"-- 02_export_spark.sql  (Blendata / Spark SQL, generated {stamp})",
         "-- column order ตรงกับ Oracle DDL และ 04_load_*.ctl — ห้ามสลับ",
         f"-- timestamp export เป็น string '{TS_SPARK}' (ctl อ่านด้วย '{TS_ORA}')",
         f"-- delimiter: X'{SEP_HEX}' (ASCII unit separator) ไม่มี quote — err_msg/filter_error มี '|' และ ',' ในข้อมูลจริง",
         "--   ถ้าเครื่องมือ export ของ Blendata ตั้ง delimiter นี้ไม่ได้ ให้แก้ FIELDS TERMINATED BY ใน .ctl ให้ตรง",
         "--   และตรวจว่าไม่มีตัวคั่นนั้นอยู่ในข้อมูล (ดู [X0])",
         "--",
         "-- MODE = FULL  : WHERE workflow_process_date <= '${SNAP_WPD}'            (ก่อน parallel run)",
         "-- MODE = DELTA : WHERE workflow_process_date >  '${SNAP_WPD}'",
         "--                  AND workflow_process_date <= '${CUTOVER_WPD}'         (CUTOVER_RUNBOOK C5)",
         "-- ขอบบนตาม workflow_process_date ทำให้ snapshot คงที่แม้ Blendata ยังรันต่อระหว่าง export\n",
         "-- [X0] ตรวจ newline และตัวคั่น X'1F' ในข้อมูล (ถ้า > 0 ต้อง export แบบ quote หรือ replace ก่อน)"]
    str_cols = {t: [c for c, ty in ddl[t] if ty.startswith("VARCHAR2")] for t in history}
    for t in history:
        conds = " OR ".join(f"instr({c.lower()}, '\\n') > 0 OR instr({c.lower()}, chr(31)) > 0" for c in str_cols[t])
        x.append(f"SELECT '{t}' AS tbl, COUNT(*) AS rows_with_newline FROM {spark_name[t]} WHERE {conds};")
    x.append("")
    for t in history + state:
        sel = ",\n       ".join(spark_expr(c, ty) for c, ty in ddl[t])
        if t in history and has_wpd[t]:
            where = "WHERE  workflow_process_date <= '${SNAP_WPD}';   -- FULL (เปลี่ยนเป็น DELTA ตามหัวไฟล์)"
        else:
            where = ";   -- state table: export ทั้งตารางทุกครั้ง (FULL และ DELTA)"
        x.append(f"-- ===== {t} -> file: {t.lower()}.dat =====\nSELECT {sel}\nFROM   {spark_name[t]}\n{where}\n")
    (out / "02_export_spark.sql").write_text("\n".join(x), encoding="utf-8")

    # ---------- 03 pre-load ----------
    ddl_text = ddl_path.read_text(encoding="utf-8")
    lookup_ix = re.findall(r"CREATE INDEX\s+(\w+)\s+ON\s+([\w.]+)", ddl_text)
    uniq_ix = re.findall(r"CREATE UNIQUE INDEX\s+(\w+)\s+ON\s+([\w.]+)", ddl_text)
    owner = targets[history[0]].rsplit(".", 1)[0] if "." in targets[history[0]] else "USER"
    pre = [f"-- 03_pre_load_oracle.sql  ({project}, generated {stamp})",
           f"-- รันเป็น {work_user} ก่อนโหลด FULL — ตารางต้องสร้างจาก 01_create_tables.sql แล้ว\n",
           "-- [P1] guard: ตาราง history ต้องว่าง (FULL load ใช้ APPEND ไม่ลบของเดิม)"]
    for t in history:   # state table ใช้ TRUNCATE mode ใน ctl จึงไม่ต้อง guard
        pre.append(f"SELECT '{t}' AS tbl, COUNT(*) AS cnt, 0 AS expected FROM {targets[t]};")
    pre.append("-- ถ้าไม่ว่าง = ยังมีข้อมูลทดสอบจาก Dev run ค้าง -> ล้างก่อน (ห้ามโหลด history ทับข้อมูลทดสอบ)")
    pre += ["", "-- [P2] ปิด lookup index ชั่วคราว (non-unique) — โหลด direct path เร็วขึ้น rebuild ใน 05",
            "--      unique index ของ merge key ต้องคงไว้ (unusable unique index ทำให้ INSERT fail)"]
    pre += [f"ALTER INDEX {owner}.{ix} UNUSABLE;" for ix, tbl in lookup_ix
            if tbl.rsplit(".", 1)[-1].upper() in history]
    pre += ["-- sqlldr ข้าม index ที่ UNUSABLE ด้วย OPTIONS SKIP_UNUSABLE_INDEXES=TRUE ใน 04_*.ctl แล้ว", ""]
    (out / "03_pre_load_oracle.sql").write_text("\n".join(pre) + "\n", encoding="utf-8")

    # ---------- 04 ctl ----------
    for t in history + state:
        fields = ",\n".join(ctl_field(c, ty) for c, ty in ddl[t])
        mode = "TRUNCATE" if t in state else "APPEND"
        ctl = (f"-- 04_load_{t.lower()}.ctl  (generated {stamp})\n"
               f"-- sqlldr userid={work_user} control=04_load_{t.lower()}.ctl data={t.lower()}.dat "
               f"log={t.lower()}.log bad={t.lower()}.bad errors=0\n"
               f"-- errors=0: แถวไหนโหลดไม่ได้ให้หยุดทันที (ห้ามปล่อยให้ history หาย แล้ว dedup ผิดแบบเงียบ)\n"
               f"-- {mode}: " + ("state table ทับทั้งตารางทุกครั้ง" if t in state else "history ต่อท้าย (FULL บนตารางว่าง / DELTA หลังลบ shadow)") + "\n"
               f"OPTIONS (DIRECT=TRUE, ERRORS=0, SKIP_UNUSABLE_INDEXES=TRUE)\n"
               f"LOAD DATA\nCHARACTERSET AL32UTF8\nINFILE '{t.lower()}.dat'\n{mode}\nINTO TABLE {targets[t]}\n"
               f"FIELDS TERMINATED BY X'{SEP_HEX}'\nTRAILING NULLCOLS\n(\n{fields}\n)\n")
        (out / f"04_load_{t.lower()}.ctl").write_text(ctl, encoding="utf-8")

    # ---------- 05 post-load ----------
    post = [f"-- 05_post_load_oracle.sql  ({project}, generated {stamp})\n",
            "-- [Q1] rebuild lookup index"]
    post += [f"ALTER INDEX {owner}.{ix} REBUILD;" for ix, tbl in lookup_ix
             if tbl.rsplit(".", 1)[-1].upper() in history]
    post += ["", "-- [Q2] index ต้อง VALID ทั้งหมด",
             f"SELECT index_name, status FROM all_indexes WHERE owner = '{owner}' AND table_name IN ("
             + ", ".join(f"'{t}'" for t in history) + ") ORDER BY 1;", "",
             "-- [Q3] optimizer stats (dedup 040000 join กับ history — ไม่มี stats = plan ผิด)"]
    post += [f"BEGIN DBMS_STATS.GATHER_TABLE_STATS('{owner}', '{t}', cascade => TRUE); END;" for t in history + state]   # ไม่ใช้ EXEC (SQL*Plus-only -> ORA-00900 ใน DBeaver)
    post += ["", "-- [Q4] integrity: cdr_id ห้ามซ้ำในแต่ละตาราง"]
    post += [f"SELECT '{t}' AS tbl, COUNT(*) - COUNT(DISTINCT cdr_id) AS dup_cdr_id, 0 AS expected FROM {targets[t]};"
             for t in history if any(c == "CDR_ID" for c, _ in ddl[t])]
    vt = [t for t in history if t.endswith(("_VALID", "_TEMP"))]
    if len(vt) == 2:
        post += ["", "-- [Q5] chk_duplicate ข้าม valid/temp (= L3 R4) — ถ้า Blendata เองมีซ้ำอยู่แล้ว ให้จดเป็น baseline ไม่ใช่ความผิดของการโหลด",
                 f"SELECT COUNT(*) AS overlap_chk_dup FROM (SELECT chk_duplicate FROM {targets[vt[0]]} "
                 f"INTERSECT SELECT chk_duplicate FROM {targets[vt[1]]});"]
    (out / "05_post_load_oracle.sql").write_text("\n".join(post) + "\n", encoding="utf-8")

    # ---------- 06 reconcile ----------
    def recon(dialect: str) -> str:
        lines = [f"-- 06_reconcile_{dialect}.sql  (generated {stamp})",
                 "-- รันคู่กันด้วย ${SNAP_WPD} (และ ${CUTOVER_WPD} หลัง delta) เดียวกัน แล้ว diff — ต้องตรง 100% ทุกแถว",
                 "-- Oracle: แทน ${...} ด้วยค่าจริง หรือใช้ &SNAP_WPD / &CUTOVER_WPD ใน SQL*Plus\n"]
        for t in history:
            name = targets[t] if dialect == "oracle" else spark_name[t]
            w = "WHERE  workflow_process_date <= '${UPPER_WPD}'" if has_wpd[t] else ""
            lines.append(f"SELECT '{t}' AS tbl, partition_date, COUNT(*) AS cnt,\n"
                         f"       COUNT(DISTINCT cdr_id) AS dist_cdr_id, COUNT(DISTINCT chk_duplicate) AS dist_chk_dup,\n"
                         f"       MIN(workflow_process_date) AS min_wpd, MAX(workflow_process_date) AS max_wpd\n"
                         f"FROM   {name}\n{w}\nGROUP  BY partition_date\nORDER  BY partition_date;\n")
        for t in state:
            name = targets[t] if dialect == "oracle" else spark_name[t]
            lines.append(f"SELECT '{t}' AS tbl, COUNT(*) AS cnt, MIN(checkpoint_partition) AS min_ckpt, "
                         f"MAX(checkpoint_partition) AS max_ckpt FROM {name};\n")
        lines.append("-- ${UPPER_WPD} = ${SNAP_WPD} หลัง FULL, = ${CUTOVER_WPD} หลัง DELTA")
        return "\n".join(lines) + "\n"
    (out / "06_reconcile_oracle.sql").write_text(recon("oracle"), encoding="utf-8")
    (out / "06_reconcile_spark.sql").write_text(recon("spark"), encoding="utf-8")

    # ---------- 07 seed state ----------
    seed = [f"-- 07_seed_state_oracle.sql  ({project}, generated {stamp})",
            "-- รันหลัง 05 ผ่าน และก่อนเปิด ODI shadow run รอบแรก",
            f"-- state ที่ย้ายมาแล้ว: {', '.join(state)} (checkpoint ของ Blendata ณ T_snap)",
            "-- state ที่ reset: ตาราง overwrite อื่น ๆ — ODI เขียนใหม่ทุก run อยู่แล้ว ต้องไม่ค้างค่าจากการทดสอบ Dev",
            "-- ⚠️ workflow_status ว่าง = ผ่าน gate ของ 020000 (COALESCE(success,'TRUE'))\n"]
    seed += [f"BEGIN EXECUTE IMMEDIATE 'TRUNCATE TABLE {targets[t]}'; END;\n/" for t in reset]
    seed += ["", "-- ยืนยัน: checkpoint ต้องเท่ากับ baseline B (max_ckpt) ของ 01_baseline_spark.sql"]
    seed += [f"SELECT MAX(checkpoint_partition) AS max_ckpt FROM {targets[t]};" for t in state]
    (out / "07_seed_state_oracle.sql").write_text("\n".join(seed) + "\n", encoding="utf-8")

    # ---------- 08 cutover delta ----------
    d = [f"-- 08_cutover_delta_oracle.sql  ({project}, generated {stamp})",
         "-- CUTOVER_RUNBOOK C5: ให้ Blendata เป็น source of truth จนถึงวินาที cutover",
         "-- ขั้นตอน: (1) ลบแถวที่ ODI shadow สร้างหลัง T_snap  (2) โหลด DELTA จาก 02 (MODE = DELTA) ด้วย 04_*.ctl",
         "--         (3) โหลด state table ใหม่ทั้งตาราง  (4) รัน 07 + 06 reconcile ด้วย UPPER_WPD = CUTOVER_WPD",
         "-- ⚠️ ต้องปิด schedule ODI + Blendata ก่อน (C2/C3) — ลบระหว่างมี run ค้าง = ข้อมูลเพี้ยน",
         "-- ⚠️ เทียบ workflow_process_date ข้ามระบบได้เพราะเป็น 'YYYYMMDDHH24MISS' ทั้งคู่ — ต้องยืนยันว่า",
         "--    Blendata และ Oracle ใช้ timezone เดียวกัน (Asia/Bangkok) ไม่งั้นขอบ SNAP_WPD เหลื่อม\n",
         "-- [D1] ดูก่อนลบ"]
    for t in history:
        if has_wpd[t]:
            d.append(f"SELECT '{t}' AS tbl, COUNT(*) AS shadow_rows FROM {targets[t]} WHERE workflow_process_date > '&SNAP_WPD';")
    d += ["", "-- [D2] ลบ output ของ ODI shadow"]
    for t in history:
        if has_wpd[t]:
            d.append(f"DELETE FROM {targets[t]} WHERE workflow_process_date > '&SNAP_WPD';")
    d += ["COMMIT;", "", "-- [D3] โหลด DELTA ด้วย sqlldr + 04_load_*.ctl (history = APPEND, checkpoint = TRUNCATE)",
          "-- [D4] รัน 05 [Q3]-[Q5], 07 และ 06 reconcile (UPPER_WPD = CUTOVER_WPD)"]
    (out / "08_cutover_delta_oracle.sql").write_text("\n".join(d) + "\n", encoding="utf-8")

    # ---------- README ----------
    rd = [f"# History Backfill Pack — {project}", "",
          f"Generated: {stamp} | Q17 = ย้ายเต็ม | อ้างอิง `status/CUTOVER_RUNBOOK.md` §2 และ C5", "",
          f"- **history** (append/merge, ย้ายตาม `workflow_process_date`): " + ", ".join(f"`{t}`" for t in history),
          f"- **state** (ย้ายทั้งตารางทุกครั้ง): " + ", ".join(f"`{t}`" for t in state),
          f"- **reset** (TRUNCATE ใน 07, ODI เขียนใหม่ทุก run): " + ", ".join(f"`{t}`" for t in reset), "",
          "## ลำดับ — FULL (ก่อน parallel run)", "",
          "| # | ที่ | ไฟล์ | ผ่านเมื่อ |", "|---|---|---|---|",
          "| 1 | Blendata | `01_baseline_spark.sql` | B0 success = TRUE, จดค่าลงตาราง Baseline |",
          "| 2 | Blendata | `02_export_spark.sql` [X0] | newline = 0 ทุกตาราง |",
          "| 3 | Blendata | `02_export_spark.sql` (FULL) → ไฟล์ `.dat` | ได้ไฟล์ครบ " + str(len(history + state)) + " ไฟล์ |",
          "| 4 | Oracle | `03_pre_load_oracle.sql` | P1 cnt = 0 ทุกตาราง |",
          "| 5 | Oracle | `sqlldr` + `04_load_*.ctl` | log: 0 rejected |",
          "| 6 | Oracle | `05_post_load_oracle.sql` | index VALID, dup_cdr_id = 0 |",
          "| 7 | ทั้งคู่ | `06_reconcile_*.sql` (UPPER_WPD = SNAP_WPD) | diff = 0 |",
          "| 8 | Oracle | `07_seed_state_oracle.sql` | max_ckpt = baseline |",
          "| 9 | ODI | เปิด shadow run (CUTOVER_RUNBOOK §3) | — |", "",
          "## ลำดับ — DELTA (วัน cutover, C5)", "",
          "`01` (จด CUTOVER_WPD) → `02` MODE = DELTA → `08` [D1][D2] → sqlldr → `05` → `07` → `06` (UPPER_WPD = CUTOVER_WPD)", "",
          "## Baseline (เติมตอนรัน)", "",
          "| ค่า | FULL (T_snap) | DELTA (cutover) |", "|---|---|---|",
          "| SNAP_WPD / CUTOVER_WPD | | |"]
    rd += [f"| {t} count | | |" for t in history]
    rd += [f"| {t} max_ckpt | | |" for t in state]
    rd += ["", "## ⚠️ ข้อควรรู้", "",
           "- ความยาวคอลัมน์ใน `.ctl` มาจาก DDL DRAFT — ถ้าแก้ DDL (หลัง `03_profile_source_lengths.sql`) ให้รัน `gen_backfill.py` ใหม่",
           f"- delimiter `X'{SEP_HEX}'`: `err_msg`/`filter_error` มี `|` จากข้อมูลจริง (`'partner is NULL|'`) ใช้ `|` หรือ `,` ไม่ได้",
           "- `cdr_id` ย้ายค่าเดิม — ไม่ชนกับที่ ODI สร้างใหม่เพราะ prefix เป็นเวลา run (`YYYYMMDDHH24MISS`)",
           "- โหลดแบบ direct path + `ERRORS=0`: แถวเดียวเสีย = หยุดทั้งไฟล์ ตั้งใจให้เป็นแบบนี้ (history หายแบบเงียบ = dedup ผิดแบบเงียบ)"]
    (out / "00_README.md").write_text("\n".join(rd) + "\n", encoding="utf-8")

    print(f"[OK] output/backfill/ history={history} state={state} reset={len(reset)}")
    print(f"[OK] {len(history + state)} ctl + 8 sql/md")


if __name__ == "__main__":
    main()
