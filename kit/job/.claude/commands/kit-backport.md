---
description: (workspace) เตรียมส่งบทเรียน / การแก้ kit (K#) ของงานนี้เข้า kit กลาง — ผ่าน PR แยก ผู้อนุมัติ review ก่อน
---
1. อ่าน `status/MIGRATION_STATUS.md` หัวข้อ "Kit — สิ่งที่แก้/เพิ่ม" (K#) และ `knowledge/lessons-learned.md` (L# ที่ระบุว่าใช้ได้ทุกงาน)
2. แยกเป็นตาราง: | รหัส | ชนิด (บทเรียน / สคริปต์ / คำสั่ง) | ใช้ได้ทุกงาน? | ไฟล์ | ความเสี่ยง | — เฉพาะงานนี้ = ไม่ส่ง
3. **บทเรียน (L#)** ที่ใช้ได้ทุกงาน → ร่างข้อความสำหรับ `kit/lessons-learned.md` ของ workspace (มีหลักฐาน · ไม่มีข้อมูลลูกค้า / รหัสผ่าน)
4. **การแก้สคริปต์ / คำสั่ง (K#)** → ขั้นตอนที่คนรันที่ root ของ workspace (บอกตรงตัว):
   `python tools/workspace.py kit-promote --job <งานนี้> --k K<เลข>-<หัวข้อ> --reason "…"` — สร้าง branch `kit/<เรื่อง>` + commit · push = ถามก่อน
5. ถามผู้อนุมัติก่อนทุกครั้ง (ทีละข้อ พร้อม [แนะนำ]) · ห้ามแก้ไฟล์ใน `kit/` ของ workspace เอง และห้ามแก้ payload ใน setup_migrate.ps1
6. หลัง merge: ทุกคน `git pull` + `python tools/workspace.py sync-kit --all` · งานถัดไป AI อ้าง L# ตอน intake
