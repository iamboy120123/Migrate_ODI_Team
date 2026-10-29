---
description: วิธี import package ของ kit เข้า ODI Studio (Smart Import), การ import ทับ project เดิม และการตรวจหลัง import (setup_migrate 2.8.0)
---
# กฎ: import / อัปเดต project ใน ODI

1. ไฟล์ที่เอาไป import คือ `output/odi_export/<package>.zip` (ชื่อจาก `odi.package_name`) เป็น **Smart Export** (มี topology และ SnpReferencedObject ตามไฟล์ reference ของ repository ปลายทาง) → ใช้ **Designer → Import → Smart Import** เท่านั้น · ห้ามบอกให้ใช้ Import Project / Import Selected Objects (ใช้กับไฟล์ที่ export ทีละ object) · `PROJ_EXPORT.xml` คือ XML ตัวเดียวกันในซิป ไว้เปิดดู ไม่ต้องเอาไป import
2. import ทับ: GlobalId ถูกจำตามชื่อใน `output/odi_export/_guid_keys.json` — project code + project name + folder + package ตรงกับ build ก่อนหน้า = ใช้ GlobalId เดิม → Smart Import เลือก **Overwrite** ได้ · ชื่อไม่ตรงหรือใช้ `--new-guid` = project ใหม่ · **ยังไม่ได้ยืนยันการ import ทับใน Studio จริง** ให้ทดสอบใน Dev ก่อนเสมอ · procedure ที่เอาออกจาก build ไม่ถูกลบใน repository (ลบเองใน Studio) · ถ้าเปลี่ยนแค่ชื่อ folder/package อาจเจอ ODI-10244 (ยังไม่ยืนยัน) ให้หยุดแล้วถามผู้ใช้
3. Topology ต้องตั้งเองใน Studio และ Scenario ต้อง generate เองใน Studio (kit ไม่สร้างให้) · ช่องรหัสผ่านเป็น null เสมอ
4. หลัง Smart Import (ครั้งเดียว): เปิด step ที่แก้ล่าสุดดู code จริง · แผง "Smart Export - Log" ใน Studio อาจเป็น log ของ project อื่น อย่าใช้เป็นหลักฐาน · (เฟสทดสอบ ไม่บังคับ) ถ้าต้องการหลักฐาน G4: Smart Export ของ project นี้ → `input/odi_reference/` → `/sync-guid` → `check_gate.py G4` -- ไม่ใช่เงื่อนไขก่อนเทส และไม่ต้อง import ซ้ำ
5. ก่อนสร้าง Run Pack ต้องมี `output/ddl/01_create_tables.sql` (รัน `gen_ddl.py` + `gen_dba_prereq.py`) แม้ตารางจะมีอยู่แล้ว