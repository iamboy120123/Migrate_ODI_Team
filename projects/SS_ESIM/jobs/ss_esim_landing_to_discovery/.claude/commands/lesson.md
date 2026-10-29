---
description: บันทึกบทเรียน (lessons-learned §2) หรือข้อเท็จจริงของ environment (environment-facts) พร้อมแหล่งที่มา
argument-hint: "<สิ่งที่เรียนรู้ / ข้อเท็จจริง>"
---
1. แยกประเภทของ: $ARGUMENTS
   - **ข้อเท็จจริงของ environment** (version, schema, NLS, timezone, ชนิดคอลัมน์, Spark config, path) → `knowledge/environment-facts.md`
   - **บทเรียน** (ปัญหาที่เจอ + ผลถ้าพลาด + วิธีทำ) → `knowledge/lessons-learned.md` §2 เลข L ถัดไป (ต่อจากเลขสุดท้ายของทั้งไฟล์)
   - ศัพท์ใหม่ → `knowledge/glossary.md`
2. ต้องมี **แหล่งที่มา** ทุกข้อ (ไฟล์ผลใน `input/run_results/<pack>/`, screenshot, บรรทัด SQL, ข้อความของ SA พร้อมวันที่) — ไม่มีหลักฐาน = ถาม SA ก่อน ห้ามบันทึกจากการเดา
3. ตรวจว่าไม่ซ้ำหรือขัดกับข้อเดิม — ขัด = แก้ข้อเดิมพร้อมหมายเหตุวันที่ (ห้ามลบประวัติ)
4. ถ้าเป็นบทเรียนที่ใช้ได้ทุกโปรเจกต์ → ระบุว่าเป็น generic (สำหรับ `/kit-backport`) · ถ้าต้องแก้ script เพื่อป้องกัน → เสนอ K#
5. ตอบสั้น ๆ ว่าเพิ่มที่ไหน เลขอะไร
