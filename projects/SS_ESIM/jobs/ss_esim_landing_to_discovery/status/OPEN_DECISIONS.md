# Open Decisions — ss_esim_landing_to_discovery (SS_ESIM_L2D)

รวมประเด็นที่ต้องให้ SA / ทีมตัดสินใจ — ตอบโดยใส่ X ในช่อง `[ ]` แล้วบอก Claude Code ให้อัปเดต kit ต่อ
ตัวเลือก **[แนะนำ]** คือคำแนะนำจากการวิเคราะห์ ไม่ใช่ค่าที่ตั้งไว้แล้ว

---

## Phase 0 — Environment & Config

### Q1. Landing retention
landing `tb_staging_ss_esim_landing_to_discovery_workflow_status` เก็บย้อนหลังกี่วัน (กำหนด point of no return ของ rollback)

- [ ] A) ระบุ: ____ วัน
- [ ] B) ยังไม่ทราบ — ต้องถามทีม ingestion

### Q2. Fail-fast เมื่อ landing ค้าง
ต้องการให้ package หยุดเมื่อ lag > 120 นาทีหรือไม่ (ต้องมี Evaluate Variable sample จาก Studio)

- [ ] A) ต้องการ **[แนะนำ]**
- [ ] B) ไม่ต้อง — รันต่อแม้ landing ค้าง

### Q3. Spark config ของ Blendata (มีผลต่อความหมายของ SQL)
ข้อเท็จจริง (จากโปรเจกต์ก่อน): ค่าเหล่านี้ทำให้ผลของ SQL เดียวกันต่างกัน — `ansi.enabled` (CAST ที่แปลงไม่ได้ = error แทน NULL), `legacy.timeParserPolicy` (EXCEPTION ทำให้ workflow ล้มทั้งรอบเมื่อเจอวันที่ผิดรูป), `parser.escapedStringLiterals` (false = backslash ใน regex literal ถูกตัด → regex อาจไม่ match)
ขอทีม Blendata รันใน workspace ของ workflow นี้ แล้วกรอก:
- `SELECT version()`: ____ · `SET spark.sql.ansi.enabled`: ____ · `SET spark.sql.legacy.timeParserPolicy`: ____ · `SET spark.sql.parser.escapedStringLiterals`: ____ · `SET spark.sql.sources.partitionOverwriteMode`: ____ · `SET spark.sql.session.timeZone`: ____ · regex_test (ถ้า SQL มี regexp_replace/regexp_extract ที่มี backslash): รัน pattern จริงกับข้อความตัวอย่างบน Blendata แล้วจดผล — ใช้ตัดสินแทนการเดาจาก escapedStringLiterals (E26)
- [ ] A) ได้ค่าครบแล้ว **[แนะนำ — ต้องมีก่อนปิด Phase 4]**
- [ ] B) ยังขอไม่ได้ — D1 (PySpark) รันทุกค่าที่เป็นไปได้ และถือว่ากฎถูกเฉพาะเมื่อผลตรงกันทุกแบบ

### Q4. Data contract ของ landing `tb_staging_ss_esim_landing_to_discovery_workflow_status`
ข้อเท็จจริง: landing ใน Oracle ที่ Spark JDBC สร้างมักมีชนิดต่างจาก Blendata (เช่น timestamp = TIMESTAMP(6), string = VARCHAR2(255), partition = NUMBER(19)) — กฎแปลงขึ้นกับชนิดจริง
- [ ] A) ใช้ชนิดตาม `all_tab_columns` ของ Oracle Dev + ขอ `DESCRIBE` จาก Blendata มาเทียบ **[แนะนำ]**
- [ ] B) กำหนด DDL landing ใหม่เอง (ต้องแจ้งทีมที่เติม landing)
- ผู้เติม landing ใน Prod: ____

### Q5. Schedule และ timezone
ข้อเท็จจริง: Airflow ใช้ **UTC** เป็น default ถ้า DAG ไม่กำหนด timezone · SQL มักใช้ `SYSDATE` (เวลาของ DB server)
- cron เดิมของ DAG: ____ · timezone ของ DAG: ____ · `SELECT DBTIMEZONE, SESSIONTIMEZONE, SYSTIMESTAMP FROM dual` (Dev/Prod): ____
- ตัวเลือก schedule ใน ODI:
  - [ ] A) Scenario + ODI Agent schedule + กันรอบซ้อน (Limit Concurrent Executions / guard flag) **[แนะนำ]**
  - [ ] B) Load Plan
  - [ ] C) scheduler ภายนอก (`startscen`) — ระบุ: ____

### Q6. แจ้งเตือนและ recovery
ข้อเท็จจริง: task recover ของ Blendata (ถ้ามี) มักถูก exclude · ODI KO path แจ้งเตือนได้เฉพาะเมื่อ session เริ่มแล้ว (Agent ล่ม = เงียบ)
- ช่องทาง / SMTP: ____ · ผู้รับ WARNING: ____ · ผู้รับ CRITICAL: ____
- [ ] A) OdiSendMail ใน KO path + runbook "Restart session เดิม" + missing-run check จากภายนอก **[แนะนำ]**
- [ ] B) monitoring ภายนอกอ่าน `SNP_SESSION` อย่างเดียว

### Q7. Work repository
ตาราง `SNP_*` อยู่ใน schema ของ work repository (Dev อาจเป็น `SYSTEM`) — ต้องรู้เพื่อ query log ใน Run Pack
- schema ของ work repo (Dev): ____ · (Prod): ____ · user ที่มีสิทธิ์ SELECT: ____
- [ ] A) กรอกครบแล้ว (ใส่ `odi.work_repo_schema` ใน config ด้วย)

---

## Workflow (setup_migrate) (2026-10-29)

### Q8. Schema qualification ของตารางใน step SQL (D-R2 ↔ kit odi-step-sql ข้อ 6)
ข้อเท็จจริง: คู่มือบังคับ qualify schema ทุกตาราง (`check_sql.py` D-R2 = ERROR, เคยเกิด ORA-00942 — lessons-learned L25 / เคส 19) · kit ห้าม hardcode schema (V3 ต้อง = 0 ก่อน G6) เพราะ schema ของ Prod อาจต่าง · ผล `check_sql.py` ล่าสุด: `output/verify/sql_check_converted.txt`
ยังไม่รู้: login / owner ของตารางใน SIT และ Prod เป็น user เดียวกันหรือไม่ · ตาราง external / master อยู่ schema เดียวกันหรือไม่
- [ ] A) `schema_mode = odiref` ใน config — kit เติม `<%=odiRef.getSchemaName("<logical schema>","D")%>.` หน้าทุกตาราง (SELECT + ตารางปลายทางใน DML, K3) · portable ข้าม environment · ผ่าน D-R2 ไม่ต้อง waiver · ไม่ต้องแก้ generator · Run Pack ต้องแทน tag เป็น schema จริงก่อนรันใน DBeaver **[แนะนำ — ใช้จริงแล้ว SS_PAYMENT_3BB_VDO: Smart Import + Dev run ผ่าน]**
- [ ] B) `schema_mode = literal` (ค่าตั้งต้น) — hardcode `target_table_prefix` (เช่น `dssdev.`) · check_sql ผ่าน แต่ V3 FAIL และต้อง build ใหม่เมื่อ Prod ใช้ schema อื่น
- [ ] C) ไม่ qualify (ชื่อตารางเปล่า) — **kit 2.8.x ไม่รองรับ**: `convert_sql.py` / `check_inputs.py` หยุดเมื่อ prefix ว่าง → ต้องแก้ kit (K#) + บังคับ data server login = owner ทุก environment (G4.M2, G6.M4) + waiver D-R2 ใน `status/GATES.md`