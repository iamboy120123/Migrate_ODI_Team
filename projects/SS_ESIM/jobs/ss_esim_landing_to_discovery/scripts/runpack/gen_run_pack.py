"""
gen_run_pack.py
----------------
Human-as-executor loop ("courier loop") — agent ยังเข้า Oracle Dev / ODI Dev / Blendata ตรงไม่ได้
จึงเตรียม "Run Pack" ให้คนรันตามลำดับ แล้ววางผลใน input/run_results/<pack>/ จากนั้น
scripts/runpack/read_run_results.py อ่านผลอัตโนมัติ -> run_packs/<pack>/REPORT.md

v2 (09-25): ทุกสคริปต์ SQL = **SELECT เดียว ไม่มีคำสั่งของ sqlplus** (SET/SPOOL/PROMPT/EXIT)
    -> รันได้ทั้ง DBeaver, SQL Developer, sqlplus (rp01 รอบแรก DBeaver ได้ ORA-00922 จาก SET MARKUP)
    -> ผลลัพธ์ export เป็น CSV (มี header) ชื่ออะไรก็ได้ — reader แยกประเภทไฟล์จาก header เอง
    -> preflight รวมเป็น UNION ALL คอลัมน์เดียวกัน (CHECK_ID, CHECK_NAME, ITEM, RESULT, EXPECTED)

Usage:
    python scripts/runpack/gen_run_pack.py [--config config/config.json] [--pack rp01]
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from gen_dba_prereq import collect_source_refs  # noqa: E402

RUN_NOTE = ("-- รันได้ทุก client (DBeaver / SQL Developer / sqlplus) — เป็น SELECT เดียว\n"
            "-- export ผลเป็น CSV (มี header) แล้ววางใน input/run_results/<ชื่อ pack นี้>/ ชื่อไฟล์อะไรก็ได้ (แนะนำ: {name})\n")


def q(s):
    return "'" + s.replace("'", "''") + "'"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("--pack", default="rp01")
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    odi = config.get("odi", {})
    day = datetime.now().strftime("%Y%m%d")
    existing = sorted(Path("run_packs").glob(f"{args.pack}_*"))
    pack = existing[-1] if existing else Path("run_packs") / f"{args.pack}_{day}"   # pack เดิมใช้ต่อ (ไม่สร้างซ้ำตามวัน)
    res_dir = Path("input") / "run_results" / pack.name   # ผลที่คนรันแล้ววางกลับ = ไฟล์จากภายนอก อยู่ใต้ input/
    if not Path("output/ddl/01_create_tables.sql").is_file():  # K-E4 (setup_migrate 2.7.2)
        sys.exit("[ERROR] ไม่พบ output/ddl/01_create_tables.sql - รัน python scripts/pipeline/gen_ddl.py และ gen_dba_prereq.py ก่อน (ยังไม่สร้างโฟลเดอร์ pack)")
    pack.mkdir(parents=True, exist_ok=True)
    res_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().isoformat(timespec="seconds")
    proj_code, proj_name = odi.get("project_code", "?"), odi.get("project_name", "?")
    pkg, lschema, ctx = odi.get("package_name", "?"), odi.get("logical_schema", "?"), odi.get("context_code", "?")
    work_user = (odi.get("work_user") or "WORK_USER").upper()
    xml = Path(config["paths"]["output_odi_export"])
    # ไฟล์ที่เอาไป Smart Import คือ zip ของ package (PROJ_EXPORT.xml คือ XML ตัวเดียวกันในซิป ไว้เปิดดู)
    _zip = xml.parent / f"{odi.get('package_name', 'PKG')}.zip"
    imp_file = _zip if _zip.exists() else xml
    manifest = json.loads(Path(config["paths"]["dml_manifest"]).read_text(encoding="utf-8"))
    targets = sorted({e["target_table"].upper() for e in manifest if not e.get("readonly")})
    tshort = [t.split(".")[-1] for t in targets]
    owner = targets[0].split(".")[0] if "." in targets[0] else work_user
    # K1 (2026-09-28): ค่าเฉพาะโปรเจกต์อ่านจาก raw manifest / dml manifest แทน hardcode ของ ss_esim
    raw_m = json.loads(Path(config["paths"]["raw_manifest"]).read_text(encoding="utf-8"))
    wf_name = next((m.get("workflow_name") for m in raw_m if m.get("workflow_name")), proj_name)
    schedule = next((m.get("schedule_time") for m in raw_m if m.get("schedule_time")), "?")
    excl = set((config.get("scope") or {}).get("excluded_tasks") or [])
    var_names = [v.get("name") for v in (odi.get("variables") or []) if v.get("name")]
    step_codes = sorted({(e["task_id"].split("_", 2)[2].split("_", 1)[0]) for e in manifest if e["task_id"].startswith("task_")} - excl)
    pkg_chain = " → ".join([f"`{v}`" for v in var_names] + step_codes)
    n_steps = len(var_names) + len(step_codes)
    lt_cfg = (config.get("profile") or {}).get("landing_table") or ""

    # ---- S0 gate ----
    v = subprocess.run([sys.executable, "scripts/pipeline/validate_odi_xml.py", "--config", args.config, "--source-check"],
                       capture_output=True, text=True)
    (pack / "S0_xml_validation.txt").write_text(v.stdout, encoding="utf-8")
    if v.returncode != 0:
        print(v.stdout)
        sys.exit(f"[STOP] PROJ_EXPORT.xml ไม่ผ่าน validate_odi_xml.py — ดู {pack}/S0_xml_validation.txt")
    s0 = v.stdout.strip().splitlines()[-1]

    # สคริปต์รุ่นเก่า (sqlplus) ถูกเขียนทับด้วยชื่อเดิมด้านล่าง — ไม่ลบไฟล์ใด ๆ, ไม่แตะ input/run_results/

    # ---- S1 ----
    (pack / "S1_odi_smart_import.md").write_text(f"""# S1 — ODI: Smart Import (ครั้งเดียว)

ไฟล์ที่ import: `{imp_file.as_posix()}`
Project ปลายทาง: **{proj_name}** (`{proj_code}`)

1. ODI Studio → Designer → Import → **Smart Import** → เลือกไฟล์ข้างบน
2. หน้า Import Actions: object ที่มีอยู่แล้ว (GlobalId ตรงกัน) ให้เลือก **Overwrite** สำหรับ procedure / package ที่ code เปลี่ยน — **Merge ไม่อัปเดต SQL ของ step ที่มีอยู่แล้ว** (K7, rp01 2026-09-29); Merge ใช้ได้กับ project / folder
   - ถ้าขึ้นเป็น **Create** ทั้งหมด = GlobalId ไม่ตรง → **หยุด** ส่งภาพหน้าจอมาแทน
   - ห้ามเลือก **Create Copy** — จะได้ project ใหม่ "Copy of ..." GlobalId ใหม่ทั้งหมด (เกิดใน rp01)
3. (หลักฐานสำหรับการทดสอบ G4 เท่านั้น — ไม่ใช่ input ของ build และไม่ต้องทำก่อนเทส) คลิกขวา project `{proj_name}` → **Smart Export** → บันทึกลง `{res_dir.as_posix()}/`
4. ถ้า import error → คัดลอกข้อความลง `{res_dir.as_posix()}/S1_error.txt`
""", encoding="utf-8")

    # ---- S2 preflight: 1 query ----
    # K17 (2026-10-01): ตารางที่มีอยู่แล้วใน Oracle (gen_ddl K16 marker) ไม่ใส่ใน S2a — รันทับใน Dev ได้ ORA-00955 และชวนสับสน
    ddl_txt = Path("output/ddl/01_create_tables.sql").read_text(encoding="utf-8")
    if "-- K16: " in ddl_txt:
        blocks = re.split(r"(?m)^(?=-- K16: )", ddl_txt)
        head, blocks = blocks[0], blocks[1:]
        keep = [b_ for b_ in blocks if "ไม่พบในผล all_tab_columns" in b_.splitlines()[0]]
        skipped = [b_.split()[2] for b_ in blocks if b_ not in keep]
        ddl_txt = (head + f"-- K17: ข้าม {len(skipped)} ตารางที่มีอยู่แล้วใน Oracle: {', '.join(skipped)}\n"
                   "-- ก่อนรัน: ดูผล S2b check 2b (MISSING_TABLE) — ถ้าตารางด้านล่างมีอยู่แล้ว ไม่ต้องรันไฟล์นี้\n\n"
                   + ("\n".join(keep) if keep else "-- (ไม่มีตารางที่ต้องสร้าง)\n"))
    (pack / "S2a_create_tables_DRAFT.sql").write_text(ddl_txt, encoding="utf-8")
    refs = collect_source_refs(Path(config["paths"]["output_converted_sql"]), config)
    external = sorted(k for k in refs if k not in tshort)
    unq = sorted(k for k, v in refs.items() if v["unqualified"])
    tlist = ", ".join(q(t) for t in tshort)
    parts = [
        # [0] version — PRODUCT_COMPONENT_VERSION อ่านได้ทุก user (v$parameter อาจไม่มีสิทธิ์)
        "SELECT '0' AS check_id, 'DB_VERSION' AS check_name, product AS item, version AS result, '19.x' AS expected "
        "FROM product_component_version WHERE UPPER(product) LIKE '%DATABASE%'",
        # [2]
        f"SELECT '2', 'TARGET_TABLES', 'found', TO_CHAR(COUNT(*)), '{len(tshort)}' FROM all_tables "
        f"WHERE owner = {q(owner)} AND table_name IN ({tlist})",
        # [2b]
        f"SELECT '2b', 'MISSING_TABLE', t.column_value, 'MISSING', 'none' FROM TABLE(sys.odcivarchar2list({tlist})) t "
        f"WHERE NOT EXISTS (SELECT 1 FROM all_tables a WHERE a.owner = {q(owner)} AND a.table_name = t.column_value)",
        # [5]
        f"SELECT '5', 'EXTERNAL_OBJECT', e.column_value, NVL((SELECT MIN(o.owner || '.' || o.object_type) FROM all_objects o "
        f"WHERE o.object_name = e.column_value), 'NOT FOUND'), 'found' FROM TABLE(sys.odcivarchar2list({', '.join(q(x) for x in external)})) e",
        # [6]
        f"SELECT '6', 'IS_OWNER', {q(work_user)}, CASE WHEN {q(work_user)} = {q(owner)} THEN 'YES' ELSE 'NO' END, 'YES' FROM dual",
        # [7]
        f"SELECT '7', 'NAME_RESOLUTION', n.column_value, CASE "
        f"WHEN EXISTS (SELECT 1 FROM all_objects o WHERE o.owner = {q(work_user)} AND o.object_name = n.column_value "
        f"AND o.object_type IN ('TABLE','VIEW','MATERIALIZED VIEW')) THEN 'OWN OBJECT' "
        f"WHEN EXISTS (SELECT 1 FROM all_synonyms s WHERE s.owner IN ({q(work_user)}, 'PUBLIC') AND s.synonym_name = n.column_value) "
        f"THEN 'SYNONYM' ELSE 'NOT RESOLVABLE' END, 'OWN OBJECT|SYNONYM' "
        f"FROM TABLE(sys.odcivarchar2list({', '.join(q(x) for x in unq)})) n",
    ]
    (pack / "S2b_preflight.sql").write_text(
        f"-- S2b preflight ({stamp}) — รันเป็น {work_user} บน Oracle Dev\n" + RUN_NOTE.format(name="preflight.csv") +
        "-- ผลต้องได้หลายแถว: check 0,2,5,6,7 (+2b ถ้ามีตารางขาด)\n" + "\nUNION ALL\n".join(parts) + "\nORDER BY 1, 3\n",
        encoding="utf-8")
    (pack / "S2c_compatible_optional.sql").write_text(
        "-- S2c (option) COMPATIBLE — ต้องมีสิทธิ์อ่าน v$parameter; ถ้า ORA-00942 ข้ามได้ (DB_VERSION ใน S2b พอ)\n"
        + RUN_NOTE.format(name="compatible.csv") +
        "SELECT 'C' AS check_id, 'COMPATIBLE' AS check_name, name AS item, value AS result, '>= 12.2' AS expected\n"
        "FROM v$parameter WHERE name = 'compatible'\n", encoding="utf-8")

    # K17: S2d index ที่มีอยู่จริงของ target (เทียบกับ index ที่ gen_ddl เสนอ / unique key ของ MERGE) — G6.M2
    (pack / "S2d_existing_indexes.sql").write_text(
        f"-- S2d index ที่มีอยู่จริงของ target — รันเป็น {work_user} บน Oracle Dev\n" + RUN_NOTE.format(name="indexes.csv") +
        "SELECT i.table_name, i.index_name, i.uniqueness, c.column_position, c.column_name\n"
        "FROM all_indexes i JOIN all_ind_columns c ON c.index_owner = i.owner AND c.index_name = i.index_name\n"
        f"WHERE i.table_owner = {q(owner)} AND i.table_name IN ({tlist})\n"
        "ORDER BY i.table_name, i.index_name, c.column_position\n", encoding="utf-8")

    # ---- S3 ----
    (pack / "S3a_blendata_stack_smoke_test.sql").write_text(
        "-- S3a smoke test (Blendata): ยืนยันว่ารองรับ stack() แบบ 2 ชั้นที่ profile ใช้ (ผลต้องได้ 2 แถว)\n"
        "SELECT 'smoke' AS tbl, col, max_len, null_cnt, row_cnt FROM (\n"
        "  SELECT row_cnt, stack(2, 'a', ml_0, nc_0, 'b', ml_1, nc_1) AS (col, max_len, null_cnt)\n"
        "  FROM (SELECT 1 AS row_cnt, 3 AS ml_0, CAST(0 AS BIGINT) AS nc_0, 5 AS ml_1, CAST(1 AS BIGINT) AS nc_1) a\n"
        ") t\n", encoding="utf-8")
    shutil.copy(Path("output/ddl/03_profile_source_lengths.sql"), pack / "S3b_blendata_profile.sql")
    pc = config.get("profile") or {}
    lt, lcols = pc.get("landing_table"), list((pc.get("landing_column_map") or {}).keys())
    if lt and lcols:
        (pack / "S3_ALT_oracle_landing_profile.sql").write_text(
            f"-- S3-ALT (Oracle) — แทน S3 เมื่อยังรันบน Blendata ไม่ได้; รันเป็น {work_user}\n"
            + RUN_NOTE.format(name="profile_result.csv") +
            "-- ⚠️ ต้องมีข้อมูลใน landing ก่อน (rp01: landing ใน Dev = 0 แถว → ผลจะว่าง)\n"
            + "\nUNION ALL\n".join(f"SELECT '{lt}' AS tbl, '{c}' AS col, MAX(LENGTH({c})) AS max_len, "
                                   f"COUNT(*) - COUNT({c}) AS null_cnt, COUNT(*) AS row_cnt FROM {lt}" for c in lcols) + "\n",
            encoding="utf-8")

    # ---- S4 checklist ----
    chk = pack / "odi_checklist.md"
    if not (chk.exists() and re.search(r"^- \[[xX]\]", chk.read_text(encoding="utf-8"), flags=re.M)):
        chk.write_text(f"""# S4 — ODI checklist (ติ๊ก [x] เมื่อทำแล้ว, ใส่หมายเหตุหลัง —)

- [ ] Topology: logical schema `{lschema}` ใน context `{ctx}` ผูกกับ physical schema `{work_user}` (ไม่ใช่ schema log/work ของ ODI)
- [ ] Data server ใช้ user `{work_user}` —
- [ ] Package `{pkg}`: {pkg_chain} ({n_steps} step)
- [ ] Retry ทุก step ตามที่ SA กำหนด (Blendata เดิม: retry=false) —
- [ ] Generate scenario ของ `{pkg}` แล้ว — ชื่อ/เวอร์ชัน scenario:
- [ ] Schedule `{schedule}` (เท่ากับ Blendata) — **ยังไม่ต้องเปิดใช้** จนกว่า Dev run ผ่าน
- [ ] ไม่มี project ซ้ำ (`Copy of ...`) จากการ import ผิดโหมด
""", encoding="utf-8")

    # ---- S5 ----
    (pack / "S5a_odi_dev_run.md").write_text(f"""# S5 — รัน package ใน Dev แล้วดึง log

1. ODI Studio → scenario ของ `{pkg}` → Run → context **{ctx}**
2. รอจนจบ (success หรือ error ก็ได้)
3. ถ้า fail: **ห้าม** execute ใหม่ทั้ง package — ส่งผลมาก่อน
4. รัน `S5b_odi_session_log.sql` ด้วย user ของ **ODI work repository** → export CSV ลง `{res_dir.as_posix()}/`
   - query error (ชื่อคอลัมน์ต่างตามเวอร์ชัน) → Operator → session ล่าสุด → **ภาพหน้าจอ** ที่เห็นสถานะทุก step
     + ข้อความ error ของ step ที่ fail (วางเป็น .png ใน `{res_dir.as_posix()}/` ได้เลย agent อ่านภาพได้)
""", encoding="utf-8")
    repo = (odi.get("work_repo_schema") or "").strip().upper()
    px = f"{repo}." if repo else ""
    (pack / "S5b0_find_work_repo_schema.sql").write_text(
        "-- S5b0 หา schema ของ ODI work repository (ที่มีตาราง SNP_SESSION) — รันด้วย user ไหนก็ได้\n"
        "-- ถ้าไม่มีแถว = user นี้มองไม่เห็นตาราง repository → ถาม ODI admin ชื่อ schema (มักเป็น <PREFIX>_ODI_REPO)\n"
        "-- ได้ชื่อแล้วบอก agent (จะใส่ config.odi.work_repo_schema แล้ว generate S5b ใหม่) หรือ login ด้วย user นั้นรัน S5b\n"
        "SELECT owner, table_name FROM all_tables WHERE table_name IN ('SNP_SESSION','SNP_STEP_LOG','SNP_SESS_STEP') ORDER BY owner, table_name\n",
        encoding="utf-8")
    (pack / "S5b_odi_session_log.sql").write_text(
        "-- S5b session log (ODI 12c/14c work repository)\n"
        + (f"-- ใช้ schema {repo} (config.odi.work_repo_schema) — user ที่รันต้องมี SELECT บนตาราง SNP_* ของ {repo}\n" if repo else
           "-- ⚠️ ต้องรันด้วย **user ของ work repository** (ไม่ใช่ user ของ schema งาน — จะได้ ORA-00942) หรือหา schema ด้วย S5b0 ก่อน\n")
        + RUN_NOTE.format(name="session_log.csv") +
        "SELECT s.sess_no, s.sess_name, s.scen_name, s.scen_version, s.context_code,\n"
        "       TO_CHAR(s.sess_beg,'YYYY-MM-DD HH24:MI:SS') AS sess_beg,\n"
        "       TO_CHAR(s.sess_end,'YYYY-MM-DD HH24:MI:SS') AS sess_end, s.sess_status,\n"
        "       sl.nno, ss.step_name, sl.nb_run, sl.step_status,\n"
        "       TO_CHAR(sl.step_beg,'YYYY-MM-DD HH24:MI:SS') AS step_beg,\n"
        "       TO_CHAR(sl.step_end,'YYYY-MM-DD HH24:MI:SS') AS step_end,\n"
        "       sl.nb_row, sl.nb_ins, sl.nb_upd, sl.nb_del,\n"
        "       REPLACE(REPLACE(DBMS_LOB.SUBSTR(sl.error_message, 2000, 1), CHR(10), ' '), CHR(13), ' ') AS error_message\n"
        # K6 2026-09-29: JOIN snp_sess_step ได้ 0 แถวใน ODI 14.1.2 (rp01) -> เริ่มจาก snp_session แล้ว LEFT JOIN ทั้งคู่
        f"FROM   {px}snp_session s\n"
        f"LEFT JOIN {px}snp_step_log sl ON sl.sess_no = s.sess_no\n"
        f"LEFT JOIN {px}snp_sess_step ss ON ss.sess_no = sl.sess_no AND ss.nno = sl.nno\n"
        f"WHERE  s.sess_no = (SELECT MAX(sess_no) FROM {px}snp_session WHERE UPPER(sess_name) LIKE '%{pkg.replace('PKG_', '')}%')\n"
        "ORDER  BY sl.nno, sl.nb_run\n", encoding="utf-8")

    # ---- S6 ----
    status_tbl = next((t for t in targets if t.endswith("_WORKFLOW_STATUS")), None)
    status_tmp = next((t for t in targets if t.endswith("_WORKFLOW_STATUS_TEMP")), None)
    ckpt_tbl = next((t for t in targets if t.endswith("_CHECKPOINT")), None)
    wpd_tbls = [e["target_table"].upper() for e in manifest
                if not e.get("readonly") and "WORKFLOW_PROCESS_DATE" in [c.upper() for c in e.get("columns", [])]
                and not any("TRUNCATE" in s.upper() for s in e.get("steps", []))]
    rows = []
    if status_tbl:
        rows.append(f"SELECT 'STATUS' AS item, 'running|success|workflow_process_date' AS name, "
                    f"running || '|' || success || '|' || workflow_process_date AS value FROM {status_tbl}")
    if status_tmp:
        rows.append(f"SELECT 'STATUS_TEMP', 'success_of_previous_run', success FROM {status_tmp}")
    if ckpt_tbl:
        rows.append(f"SELECT 'CHECKPOINT', 'min|max|rows', MIN(checkpoint_partition) || '|' || MAX(checkpoint_partition) || '|' || COUNT(*) FROM {ckpt_tbl}")
    rows.append(f"SELECT 'LANDING', 'max_partition_minute|rows', MAX(partition_minute) || '|' || COUNT(*) FROM {lt or lt_cfg}")
    for t in sorted(set(wpd_tbls)):
        rows.append(f"SELECT 'LAST_WPD', '{t.split('.')[-1]}', MAX(workflow_process_date) FROM {t}")
    rows += [f"SELECT 'ROWCOUNT', '{t.split('.')[-1]}', TO_CHAR(COUNT(*)) FROM {t}" for t in targets]
    # K1: ชุด TESTDATA (iccid 'TESTSA%') ของ ss_esim ถูกตัดออก — ยังไม่มี seed script ของ payment_3bb_vdo
    (pack / "S6_post_run_capture.sql").write_text(
        f"-- S6 post-run capture — รันเป็น {work_user} หลัง S5 (success หรือ fail ก็รัน)\n" + RUN_NOTE.format(name="post_run.csv") +
        "-- หมายเหตุ: step สุดท้าย (success) TRUNCATE ตาราง status แล้วเขียนแค่ success → workflow_process_date ของ run หายจากตารางนี้\n"
        "--          (เหมือน Blendata) — LAST_WPD อ่านจากตาราง transaction แทน\n"
        + "\nUNION ALL\n".join(rows) + "\n", encoding="utf-8")

    # ---- S6b: reset flag running (ADR-006 O11) — Dev เท่านั้น ----
    if status_tbl:
        (pack / "S6b_reset_running_flag_DEV.sql").write_text(
            f"-- S6b reset flag running (ADR-006 O11) — **Oracle Dev เท่านั้น** รันเป็น {work_user} · Execute Script (Alt+X)\n"
            "-- ใช้เมื่อรอบทดสอบล้มกลางทางแล้ว running = 'TRUE' ค้าง (รอบถัดไปจะเจอ ORA-20003 หลังเพิ่ม guard)\n"
            "-- ผลเท่ากับจบ step 080000 (success = 'TRUE') · ห้ามใช้ใน SIT/PROD — ใช้ runbook ADR-007\n"
            f"SELECT 'BEFORE' AS t, running, success, workflow_process_date FROM {status_tbl};\n"
            f"DELETE FROM {status_tbl} WHERE running = 'TRUE';\n"
            f"INSERT INTO {status_tbl} (success) SELECT 'TRUE' FROM dual WHERE NOT EXISTS (SELECT 1 FROM {status_tbl});\n"
            "COMMIT;\n"
            f"SELECT 'AFTER' AS t, running, success, workflow_process_date FROM {status_tbl};\n", encoding="utf-8")

    # ---- manifest + README ----
    (pack / "MANIFEST.json").write_text(json.dumps({
        "pack": pack.name, "generated": stamp, "version": 2, "project": proj_code, "package": pkg,
        "context": ctx, "work_user": work_user,
        "note": "ผล CSV ตั้งชื่ออะไรก็ได้ — read_run_results.py จำประเภทจาก header"}, indent=2, ensure_ascii=False), encoding="utf-8")
    (pack / "README.md").write_text(f"""# Run Pack {pack.name} — {wf_name} (v2)

Updated: {stamp} | Project `{proj_code}` | Context `{ctx}` | User `{work_user}`

**S0 (agent ทำแล้ว):** `validate_odi_xml.py` — {s0}

- สคริปต์ SQL ทุกไฟล์เป็น **SELECT เดียว** — รันใน DBeaver / SQL Developer / sqlplus ได้ (ไม่มี SET/SPOOL แล้ว)
- ผลลัพธ์: export เป็น **CSV มี header** วางใน `{res_dir.as_posix()}/` — **ชื่อไฟล์อะไรก็ได้** (reader จำจาก header); ภาพหน้าจอ .png ก็วางได้
- เสร็จแล้วบอก agent หรือรัน `python scripts/runpack/read_run_results.py --pack {pack.as_posix()}`

| Step | ที่ไหน | ทำอะไร | ผล | หยุดถ้า |
|---|---|---|---|---|
| S1 | ODI Studio | `S1_odi_smart_import.md` | Smart Export .xml | Import Actions ขึ้น Create / Create Copy |
| S2a | Oracle Dev ({work_user}) | `S2a_create_tables_DRAFT.sql` — **เฉพาะถ้ายังไม่มีตาราง** (script หลาย statement: รันแบบ Execute Script) | — | — |
| S2b | Oracle Dev ({work_user}) | `S2b_preflight.sql` | CSV | — |
| S2c | Oracle Dev | `S2c_compatible_optional.sql` (option — ต้องมีสิทธิ์ v$parameter) | CSV | — |
| S2d | Oracle Dev ({work_user}) | `S2d_existing_indexes.sql` — index จริงเทียบกับที่ DDL เสนอ (unique key ของ MERGE) | CSV | — |
| S3 | Blendata | `S3a_blendata_stack_smoke_test.sql` → `S3b_blendata_profile.sql` (รวมผลทุก query เป็น CSV เดียว) | CSV | S3a error |
| S3-ALT | Oracle Dev ({work_user}) | `S3_ALT_oracle_landing_profile.sql` — แทน S3 **หลัง landing มีข้อมูล** | CSV | landing ว่าง |
| S4 | ODI Studio | ติ๊ก `odi_checklist.md` (ในโฟลเดอร์ pack) | ไฟล์เดิม | Topology ผูกผิด schema |
| S5 | ODI Studio + work repo | `S5a_odi_dev_run.md` → `S5b_odi_session_log.sql` ด้วย **user ของ work repository** (ไม่ใช่ {work_user}; หา schema ด้วย `S5b0_find_work_repo_schema.sql`) | CSV หรือ**ภาพ Operator** | preflight [2] [5] [7] ไม่ผ่าน |
| S6 | Oracle Dev ({work_user}) | `S6_post_run_capture.sql` | CSV | — |
| S6b | Oracle Dev ({work_user}) | `S6b_reset_running_flag_DEV.sql` — **เฉพาะเมื่อรอบทดสอบล้มแล้ว running = 'TRUE' ค้าง** (Dev เท่านั้น) | — | — |
""", encoding="utf-8")
    print(f"[OK] {pack}/ — " + ", ".join(sorted(p.name for p in pack.iterdir())))


if __name__ == "__main__":
    main()
