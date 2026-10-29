---
description: ก่อนบอกผู้ใช้ว่า SQL/XML พร้อม import หรือรัน ต้องรัน scripts/checks/pre_delivery_gate.py ให้ FAIL = 0 และห้ามเลือก DELETE/TRUNCATE เอง
---
# กฎ: ด่านตรวจก่อนส่งมอบ (เกิดจากเหตุจริงของงาน esim: import ผ่าน แต่รันพังทีละ step)

เหตุที่ต้องมีกฎนี้ (ภาษาธรรมดา): ตัวตรวจ `check_sql.py` จะ "ข้าม" กฎสำคัญ (D-R7 เรื่อง TRUNCATE กับ partition, D-R8 เรื่องแปลงวันที่) โดยไม่ฟ้อง ถ้าไม่ได้ป้อนไฟล์ `--ddl` และ `--partitions` และมันมองไม่เห็น TRUNCATE ที่ห่อไว้ใน `BEGIN EXECUTE IMMEDIATE ...` ผลคือบอกว่า "ผ่าน" ทั้งที่ SQL พังหรือทำงานผิดความหมาย

## ต้องทำทุกครั้งก่อนบอกผู้ใช้ว่า "พร้อม import / พร้อมรัน"

1. รัน `python scripts/checks/pre_delivery_gate.py` แล้วต้องได้ **FAIL = 0** (เก็บผลไว้ที่ `output/verify/pre_delivery_gate.txt`)
2. `check_sql.py` ที่ไม่ได้ป้อน `--ddl` และ `--partitions` **ไม่นับว่าผ่าน**
3. **overwrite ห้ามเลือก DELETE หรือ TRUNCATE เอง** อ่าน `config/partitions_check.csv` ก่อน: partitions ไม่ว่าง (N) = DELETE ตาม partition · ว่าง (Y) = TRUNCATE · ถ้าจะ TRUNCATE ตารางที่เป็น N ต้องมี SA ตัดสินใจเป็นลายลักษณ์อักษร แล้วบันทึกใน `config/gate_waivers.txt` (`P4 <เลข task> | SA <วันที่> <เหตุผล>`)
4. ถ้ามีผลงานเดิมของ workflow เดียวกันที่ **รันผ่านจริงแล้ว** ให้เทียบ SQL ทีละ task กับของใหม่ก่อนส่ง ความต่างที่อธิบายไม่ได้ = ยังไม่พร้อม
5. **รอบแรกที่ส่งไปรัน ให้เป็นโครงพื้นฐานตามคู่มือเท่านั้น** ของเสริม (guard, LOG ERRORS ฯลฯ) เติมทีหลัง ทีละอย่าง หลังรอบพื้นฐานผ่านครบ จะได้รู้ทันทีว่าตัวไหนทำพัง
6. ชื่อ object ยาวเกิน 30 ตัว + ใช้ `odiRef.getObjectName`: ให้ผู้ใช้ตรวจ Topology > Technologies > Oracle > Max Table Name Length ก่อนรันครั้งแรก
7. ก่อน import ครั้งแรก (Designer → Import → **Smart Import** ไฟล์ zip, ดู `.claude/rules/odi-import.md`): ให้ผู้ใช้ตรวจ Designer ว่ามี project รหัสเดียวกันอยู่แล้วหรือไม่ — มีและชื่อตรงกัน = เลือก Overwrite, ไม่ตรง = จะได้ project ใหม่

ทำงานร่วมกับ `one-at-a-time.md` (ขอผู้ใช้ทีละ 1 ข้อ) และ `ask-with-recommendation.md`