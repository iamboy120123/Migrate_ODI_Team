---
description: ขั้น 1 — ไล่คำถาม intake I1–I17 ทีละข้อ (รายละเอียดต่อข้อ: `knowledge/reference/intake-questions.md`) โดยเติมคำตอบที่หาได้จากไฟล์ก่อน แล้วถามเฉพาะข้อที่ยังว่าง
argument-hint: "[I<n> ที่จะเริ่ม]"
---
1. อ่าน `knowledge/WORKFLOW.md`, `status/INTAKE.md` · รายละเอียดคำถามอยู่ที่ `knowledge/reference/intake-questions.md` (~165 KB) — **อย่าเปิดทั้งไฟล์**: อ่านหัวข้อ "กฎการถาม" ครั้งเดียว แล้วอ่านเฉพาะ `grep -n '^### \[I<n>/17\]'` ของข้อที่กำลังถาม
2. **ตาราง "ver 6" ใน intake-questions.md ชนะรายละเอียดต่อข้อ** — ข้อที่ถูกตัด (I1 I5 I9 I11 I17) ไม่ถาม · ข้อที่ลด (I4 I7 I8 I13 I14 I16) ถามเป็นคำยืนยันครั้งเดียว · อ่านค่าไม่เจอ = ถามตามเดิม ห้ามเดา
   ข้อที่ตอบจากไฟล์ได้ (`config/config.json`, export JSON, `status/OPEN_DECISIONS.md`, STATUS, `.design/`) → เติมใน `status/INTAKE.md` พร้อมแหล่งที่มา **ไม่ต้องถามซ้ำ** ("สิ่งที่ไม่ต้องถาม")
3. ข้อ ⬜ / ⚠️ → ถาม SA **ทีละข้อ** ในรูปแบบของ intake-questions.md (`**[I<n>/17]** ...` + ตัวอย่างคำตอบ) — ห้ามยิงหลายข้อรวด เริ่มที่ $ARGUMENTS ถ้าระบุ
4. คำตอบที่เป็นการตัดสินใจ (scope, semantics, load strategy, schema) → เปิด/อ้าง Q ใน `status/OPEN_DECISIONS.md` ด้วย `/decide` · ใส่ `✅ SA YYYY-MM-DD` เฉพาะเมื่อ SA ตอบในแชต
5. หลัง I1 ตอบแล้ว: สรุป business flow จาก DAG ("ขั้นเสริม") ลง `.design/02_architecture.md` นอก block AUTO
6. ครบแล้ว → เสนอ `/br-catalog` แล้ว `/update-status`