# Environment facts — SS_ESIM_L2D

กรอกเฉพาะ**ข้อเท็จจริงที่มีหลักฐาน** (ไฟล์ผลใน `input/run_results/`, screenshot, คำยืนยันของทีม) — สมมติฐานให้เขียนใน OPEN_DECISIONS

| หัวข้อ | Dev | SIT | Prod | แหล่งที่มา |
|---|---|---|---|---|
| Oracle version | | | | |
| schema เจ้าของตาราง / user ที่ ODI connect (DSSDEV) | | | | |
| ODI version / work repo / schema ของ `SNP_*` | 14.1.2 / / | | | |
| logical schema / context | DSS_ODI_LOG / DEV | | | |
| DB timezone (`DBTIMEZONE`, `SYSTIMESTAMP`) | | | | |
| NLS (`NLS_DATE_FORMAT`, `NLS_TIMESTAMP_FORMAT`) | | | | |
| ชนิดคอลัมน์ landing `tb_staging_ss_esim_landing_to_discovery_workflow_status` (`all_tab_columns`) | | | | |
| Spark version / ansi / timeParserPolicy / escapedStringLiterals (Blendata) | | | | |
| Airflow schedule + timezone ของ DAG | | | | |
