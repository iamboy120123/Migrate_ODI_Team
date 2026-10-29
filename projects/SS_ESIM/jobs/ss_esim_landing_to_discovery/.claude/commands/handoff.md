---
description: สรุปจบ session สำหรับส่งต่อ (ทำอะไรไป, สถานะ gate, สิ่งที่คนต้องทำ, เส้นตาย) — ไม่แก้ไฟล์นอกจาก STATUS
---
1. `python scripts/checks/check_gate.py --all` และ `python scripts/checks/verify_all.py --quiet`
2. อ่าน `status/MIGRATION_STATUS.md` (rev ล่าสุด), `status/OPEN_DECISIONS.md`, `status/GATES.md`, REPORT ของ Run Pack ล่าสุด
3. สรุป (ภาษาไทย กระชับ):
   - **ทำไปใน session นี้** — ไฟล์ที่เปลี่ยน (converted SQL / config / scripts K# / docs)
   - **สถานะ** — phase ปัจจุบัน, ตาราง gate, verify ที่ FAIL/WARN
   - **รอ SA** — Q ที่เปิด, manual checklist ที่ค้าง, ADR ที่รอ Accepted
   - **คนต้องทำต่อ** — เป็นขั้นตอนมีเลขกำกับ พร้อม **เส้นตาย** (เช่น seed หมดอายุใน 120 นาที, ต้อง Smart Import Overwrite ก่อนรัน)
   - **ข้อมูลทดสอบที่ค้างในตาราง** (marker) และวิธี cleanup
   - **สมมติฐานที่ยังไม่ยืนยัน**
4. ถ้า STATUS ยังไม่ครอบคลุม session นี้ → `/update-status` ก่อน
5. ถ้าผู้ใช้ต้องการเก็บไว้อ่านต่อ ให้เสนอเขียนลง Project / ไฟล์ `HANDOFF_<YYYYMMDD>.md`
