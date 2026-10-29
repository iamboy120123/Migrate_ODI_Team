---
description: ร่าง Architecture Decision Record ใหม่ใน .design/adr/
argument-hint: "<หัวข้อการตัดสินใจ>"
---
1. หาเลขถัดไปจาก `.design/adr/ADR-*.md` (ข้าม ADR-000-template)
2. สร้าง `.design/adr/ADR-NNN-<slug>.md` จาก `ADR-000-template.md` หัวข้อ: $ARGUMENTS
3. Context ต้องอ้างข้อเท็จจริง (ไฟล์ / ผล Run Pack / Q ใน OPEN_DECISIONS); Options อย่างน้อย 2 พร้อมข้อดีข้อเสีย
4. `Status: Proposed` เสมอ — SA เป็นคนเปลี่ยนเป็น Accepted (ห้าม agent เปลี่ยนเอง)
5. ถ้าแทน ADR เดิม ใส่ `Supersedes ADR-XXX` และแก้ ADR เดิมแค่บรรทัด Status
