---
description: วินิจฉัยอาการจากผลรัน (ORA/ODI error, 0 แถว, ผลไม่ตรง) → สร้าง diagnose script แบบ SELECT อย่างเดียวให้คนรัน
argument-hint: "<อาการ เช่น 'valid = 0' หรือ ORA-xxxxx>"
---
1. ใช้ subagent `run-result-analyst` กับ Run Pack ล่าสุดและอาการ: $ARGUMENTS
2. ถ้าเป็น ORA/ODI error: เทียบกับ `KNOWN_ERRORS` ใน `scripts/runpack/read_run_results.py` — ไม่อยู่ในรายการ = **ห้ามเดาแก้** ขอ log/หลักฐานเพิ่ม
3. เขียนสมมติฐานเรียงตามความน่าจะเป็น แต่ละข้อบอกว่าหลักฐานอะไรยืนยัน/หักล้าง
4. สร้าง `run_packs/<pack>/S<nn>_diagnose_<desc>.sql` — SELECT อย่างเดียว, คั่นแต่ละ query ด้วย label คอลัมน์แรก (`'S<nn>a' AS chk`), รันด้วย Alt+X, บอกชื่อไฟล์ CSV ที่ต้อง export
5. บอก SA เป็นขั้นตอนมีเลขกำกับ (user ที่ใช้รัน, ต้องเก็บ screenshot อะไร, **ยังไม่ต้อง cleanup** ถ้าข้อมูลยังใช้วิเคราะห์)
6. บันทึกอาการ + สมมติฐานใน `status/MIGRATION_STATUS.md` §5 (ระบุว่า "สมมติฐาน")
