---
description: Phase 5 — generate DML + ODI Smart Import XML แล้ว validate
---
0. **ด่านของครบ (บังคับ):** `python scripts/checks/check_inputs.py` — ต้องขึ้น `[พร้อม]` ก่อน ถ้าขึ้น `[ยังไม่พร้อม]` ให้รายงานรายการที่ขาดทั้งหมดพร้อมวิธีได้มาแก่ผู้ใช้ (ทีละข้อ) แล้วหยุด **ห้าม build/ส่ง package ที่ยังไม่ครบ** เพราะ import เข้า ODI Studio ทำ **ครั้งเดียวตอนจบ** (Smart Import) หลังจากนั้นเป็นเรื่องทดสอบ ไม่มีรอบ "import ลองก่อนแล้วเอาผลกลับมาแก้"
1. `python scripts/pipeline/gen_dml.py`
2. `python scripts/pipeline/build_odi_export.py` (reuse GlobalId อัตโนมัติเมื่อชื่อตรงกับ build ก่อน — ห้ามใส่ `--new-guid` เว้นแต่ SA สั่ง · builder ของ md15: อ่าน topology/SnpOrigTxt/SqlIndGrp จาก `input/odi_reference/` · รัน `check_sql` ทุก step · **ปฏิเสธเขียนไฟล์ถ้ามี error** เช่น ตารางไม่มี schema, TRUNCATE ตารางที่มี partition, INSERT ไม่มี column list — ห้ามหาทางอ้อม แก้ที่ converted SQL / gen_dml แล้วรันใหม่)
3. `python scripts/pipeline/validate_odi_xml.py --source-check`
4. `python scripts/pipeline/gen_design_docs.py` (อัปเดต package flow / task mapping ใน .design)
4b. ใช้ subagent `xml-auditor` ตรวจ drift (GlobalId / ลำดับ step / SQL ใน XML = DML)
5. ถ้า validator มี error → แก้ที่ต้นทาง (converted SQL / config / generator) แล้ววนซ้ำจน 0 error
6. สรุป: จำนวน procedure / step / variable, warning ที่เหลือ, path ของ `output/odi_export/<package>.zip` (ไฟล์เดียวที่ใช้ **Smart Import** — ห้ามใช้ Import Project / Import Selected Objects; `PROJ_EXPORT.xml` คือไฟล์กลาง) และขั้นตอน import **ครั้งเดียว**: Smart Import → **Overwrite** สำหรับ procedure/package ที่ชื่อตรงกับของเดิม (ห้าม Create Copy) · หลัง import ไม่ต้องส่งอะไรกลับมาให้ AI ก่อนทดสอบ — ไปขั้นทดสอบ `/run-pack` ต่อได้เลย (Smart Export กลับจาก Studio เป็นหลักฐานการทดสอบ G4 เท่านั้น ไม่ใช่ input ของ build)
