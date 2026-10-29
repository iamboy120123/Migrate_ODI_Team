---
description: Sync GlobalId + project code จาก Smart Export ที่ export จาก ODI Studio
argument-hint: "<path ของ Smart Export XML>"
---
(เฟสทดสอบ ไม่บังคับ — ไม่ใช่เงื่อนไขก่อน build/ก่อนเทส; ใช้เมื่อมีการแก้ project ใน Studio หลัง Smart Import แล้วต้องการให้ GlobalId ตรงกัน)

1. ถ้าไฟล์ $ARGUMENTS ยังไม่อยู่ใน `input/odi_reference/` → copy ไปเก็บเป็น `smart_export_<desc>_<YYYYMMDD>.xml`
2. `python scripts/pipeline/sync_guid_from_export.py --export <file> --dry-run` แล้วสรุปสิ่งที่จะเปลี่ยน (project code/name, จำนวน GlobalId)
3. ถ้า project code เปลี่ยน → ถาม SA ก่อน แล้วค่อยรันจริงด้วย `--update-config`
4. ต่อด้วย `/gen-export` และยืนยันว่า SQL ใน XML ตรงกับของใน Studio
5. `python scripts/checks/check_gate.py G4` — auto ตรวจว่า code ใน Smart Export = DML ทุก step และ GlobalId map ตรงกับ Studio (ใช้ Smart Export ล่าสุดที่ใหม่กว่า PROJ_EXPORT.xml)
