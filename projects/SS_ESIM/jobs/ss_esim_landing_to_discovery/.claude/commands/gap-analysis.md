---
description: ขั้น 2 — อัปเดต status/GAP_ANALYSIS.md (As-Is Spark ↔ To-Be Oracle) จาก review log, decisions, BR catalog และผล check_sql พร้อม disposition K/M/A/R
---
1. รัน `/sql-check` (หรือใช้ผลล่าสุดใน `output/verify/sql_check_*.txt`) และอ่าน `status/PHASE4_REVIEW_LOG.md` (แถว ACCEPTED / เปลี่ยน semantics = ใช่), `status/OPEN_DECISIONS.md`, `status/BUSINESS_RULES.md`, `knowledge/lessons-learned.md` (L29, L34 ฯลฯ), `knowledge/reference/validation-and-cutover.md` §E2
2. ทุกความต่างที่ทำให้ผล/พฤติกรรมไม่เท่าเดิม = 1 แถว `GAP-nn` ในหมวด 1–4 · ใส่ BR ที่กระทบ, ผลกระทบ H/M/L, disposition K/M/A/R, Q/ADR, หลักฐานที่ต้องมี (D1/D2/test) · ไล่ checklist "gap ที่พบบ่อย" ท้ายไฟล์ทุกข้อ
3. disposition ≠ K และยังไม่มี Q ที่ SA ปิด → `/decide` (ห้ามตัดสินเอง) · เรื่องออกแบบ → `/adr` (Proposed)
4. GAP ที่ต้องมี test → แจ้ง `test-designer` · GAP ที่ต้องเทียบ Blendata → รายการของ `/compare-d2`
5. อัปเดตตารางสรุป แล้ว `/update-status`