---
description: รวมผลตรวจ SQL ทุกชั้น (①–⑦ + ความเร็ว) เป็น status/SQL_REVIEW.md แล้วไล่ ⛔ ก่อน · 🟡 ถามว่าไม่ต้องแก้ใช่ไหม
---
1. `python scripts/checks/review_report.py` → `status/SQL_REVIEW.md` (สรุป ✅ · 🟡 · ⛔ ต่อ task)
2. ชั้น ⑥ คอมไพล์กับฐานจริง: ถ้ายังเป็น – ให้สร้าง pack `python scripts/checks/review_report.py --make-compile-pack` แล้วทำตามโหมดการเช็กฐานของงาน
   (AI ต่อเนื่อง = รัน `python scripts/runpack/run_pack.py rp_compile --compile` · ถามทีละขั้น = ถามก่อนรัน · คนรันทั้งหมด = บอกตามลำดับ: ไฟล์ไหน · รันเพื่ออะไร · export เป็นอะไร · วางที่ไหน)
3. แสดงสรุปบนจอ: "✅ n · 🟡 n · ⛔ n" แล้วไล่ข้อ ⛔ ก่อนทีละข้อ (แก้ที่ converted SQL เฉพาะ dialect ที่ไม่เปลี่ยนความหมาย · เปลี่ยนความหมาย = เปิด Q)
4. ข้อ 🟡 ที่เป็น WARN: ถามทีละข้อ "ข้อนี้ไม่ต้องแก้ใช่ไหม" พร้อม [แนะนำ] และเหตุผล → ตอบใช่ = บันทึก `NO_CHANGE` + เหตุผลใน `status/PHASE4_REVIEW_LOG.md` (ห้ามแก้ SQL เพียงให้ WARN หาย)
5. มี ⛔ = ห้าม build · จบแล้วรัน `/update-status` (แสดงกล่องสถานะ)
