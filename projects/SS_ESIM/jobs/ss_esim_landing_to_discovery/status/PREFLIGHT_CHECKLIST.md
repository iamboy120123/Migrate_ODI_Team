# Pre-flight Checklist — SS_ESIM_L2D

Updated by Setup.ps1 on 2026-10-29 · passed **2/5** · update by running `Setup.ps1 -Mode InPlace` in this folder, or edit the table (✅ / ⬜)

README / Runbook Phase 0: **do not run `extract_workflow.py` (Phase 1) on real data until all items pass.**

| # | Status | Item | Note | Checked by |
|---|---|---|---|---|
| 1 | ✅ | Automation scripts are ready and pass the smoke test | smoke test passed | Setup.ps1 (auto) |
| 2 | ⬜ | ODI Topology in the target repository has JDBC URL + user/password set on the data server (not in the export) — logical schema 'DSS_ODI_LOG' / context 'DEV' / login 'DSSDEV' (from Smart Export) | pending | SA |
| 3 | ⬜ | Target Oracle schema / DDL is ready in DSSDEV (else use output/ddl from Phase 6) | pending | SA |
| 4 | ✅ | The real Blendata workflow export (.json) is in input/blendata/ | input/blendata/export_workflow.json | Setup.ps1 (auto) |
| 5 | ⬜ | DBA is informed + privileges for ODI Smart Import | pending | SA |

## ก่อนเข้า G4 (ไม่นับใน 5/5)

- [ ] เทียบ Data Server UserName และ Physical Schema ใน Smart Export (input/odi_reference/) กับ odi.work_user ใน config และ Q ที่ตัดสินเรื่อง work user / prefix ใน status/OPEN_DECISIONS.md ว่าตรงกัน (ตรงกับ G4.M3 ใน status/GATES.md — AI อ่านจากไฟล์เทียบเอง)
