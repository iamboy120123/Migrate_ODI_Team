# kit/ — ของกลางของทีม (แก้ผ่าน PR เท่านั้น · ผู้อนุมัติเป็น Code Owner)

| ไฟล์ / โฟลเดอร์ | คืออะไร |
|---|---|
| `setup_migrate.ps1` | ตัวสร้างงาน (kit ทำงาน 6 ขั้น) — `new-job` เรียกตัวนี้ · เปลี่ยนรุ่นด้วย `workspace.py extract-kit` |
| `CLAUDE.kit.md` | กฎของทีมสำหรับ AI (import จาก CLAUDE.md ของทุกงาน) |
| `CLAUDE.job.md` | ส่วนกลางของ CLAUDE.md ที่เหมือนกันทุกงาน (สร้างโดย slim-job ครั้งแรก) |
| `job/` | ไฟล์ที่ `sync-kit` วางลงทุกงาน (สถานะ · hook GitHub · run_pack · เกรด · รายงาน) |
| `patches/` | การแก้ kit ที่ promote จากงาน (K#) — sync-kit วางทับให้ทุกงาน จนกว่าจะ backport เข้า setup |
| `base_manifest.json` | sha ของไฟล์ kit ตอนสร้างงานแรก — ใช้หาการแก้ kit ที่ค้างในงาน |
| `lessons-learned.md` | บทเรียนที่ทีมอนุมัติแล้ว (AI อ่านก่อนถาม) |
| `grading-rules.md` | กติกาเกรด A / B / F และระดับความเร็ว |
| `CHANGES-ws.md` | การแก้ kit ที่ยังไม่ backport |
| `github/` | แม่แบบ .github (CI 4 ตัว · PR template) — `init-github` ก๊อปไป `.github/` |
