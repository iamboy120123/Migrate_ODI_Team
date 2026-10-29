---
description: อัปเดตเอกสารออกแบบใน .design/ (AUTO จาก manifest + เติม spec ต่อ task จาก SQL)
argument-hint: "[task code เช่น 040000 | all]"
---
1. `python scripts/pipeline/gen_design_docs.py` — อัปเดต block AUTO ใน `03_package_flow.md`, `04_task_mapping.md`, `diagrams/package_flow.mmd` และสร้างโครง spec ที่ยังไม่มี
2. สำหรับ task: $ARGUMENTS (ว่าง = เฉพาะ spec ที่ยังมี `_(เติมจาก SQL)_`) ใช้ subagent `spec-writer` (หลาย task = เรียกขนานกันได้) อ่าน raw + converted + DML แล้วเติมใน `.design/specs/<task>.md`:
   - Business logic (อ่านจากไหน กรองอะไร join อะไร เขียนอะไร), Rules พร้อมอ้างบรรทัด, Column mapping, Dialect changes, Test cases อย่างน้อย 3 (ปกติ / ขอบ / reject)
   - สิ่งที่ไม่ชัด → "Open questions" (ห้ามเดา); ถ้าเป็นเรื่องตัดสินใจ → `status/OPEN_DECISIONS.md`
3. ถ้าข้อเท็จจริงใน `02_architecture.md` เปลี่ยน (schedule, landing, downstream) → แก้นอก block AUTO
4. `python scripts/checks/verify_all.py --level V8` — spec ที่ยังไม่เติมต้องเหลือ 0 สำหรับ task ที่มี DML
5. สรุปว่าไฟล์ไหนเปลี่ยนบ้าง
