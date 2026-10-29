## งาน

- project / job:
- รอบ (R##) · ใบงาน #:
- ขั้นที่จบในรอบนี้ (ดู `/status`):

## ต้องให้ผู้อนุมัติตัดสิน

<!-- comment บรรทัดละข้อ: /approve Q14 B · /approve G2.M1 · /approve W1 -->
-

## เช็กก่อน merge

- [ ] `python tools/workspace.py check` ผ่าน
- [ ] กล่องสถานะล่าสุดอยู่ใน `status/MIGRATION_STATUS.md` (`/update-status`)
- [ ] ไม่มีผลรันจริง / รหัสผ่าน / host ใน diff (CI secret-scan)
- [ ] 1 PR = 1 งาน
