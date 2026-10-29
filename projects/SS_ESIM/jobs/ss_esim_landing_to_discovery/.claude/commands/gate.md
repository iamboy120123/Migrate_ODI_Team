---
description: ประเมิน gate ตาม status/GATES.md (PASS / BLOCKED / WAIVED) ก่อนข้ามช่วงงาน
argument-hint: "<G0..G7 | all>"
---
1. ถ้า $ARGUMENTS ว่างหรือเป็น `all` → `python scripts/checks/check_gate.py --all`; ไม่งั้น `python scripts/checks/check_gate.py $ARGUMENTS`
2. สรุปผล: ข้อ auto ที่ ❌ (บอกวิธีแก้), ข้อ manual ที่ ⬜ (บอกว่า SA ต้องทำอะไร / ส่งหลักฐานอะไร), waiver ที่เปิดอยู่
3. **ห้ามติ๊ก manual checklist แทน SA** — ติ๊กได้เฉพาะเมื่อ SA ยืนยันในแชต และต้องเขียน `✅ SA YYYY-MM-DD` ในบรรทัดเดียวกัน (hook บังคับ)
4. ถ้า BLOCKED แต่ SA อยากไปต่อ → เสนอ waiver (ข้อที่ยกเว้น, ขอบเขต, เงื่อนไขปิด) ให้ SA อนุมัติ แล้วบันทึกใน Waiver log ของ `status/GATES.md`
5. บันทึกผลใน `status/MIGRATION_STATUS.md` ด้วย `/update-status` เมื่อ gate เปลี่ยนสถานะ
