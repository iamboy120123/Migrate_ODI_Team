# BUSINESS RULES CATALOG — SS_ESIM_L2D

Updated: 2026-10-29 · โครงสร้างโดย `setup_migrate.ps1` · เติมด้วย `/br-catalog` จาก `output/sql/raw/*.sql` (Spark SQL = ความจริงของ As-Is) · **SA ยืนยันทีละข้อ**

## วิธีอ่าน / บันทึก

- 1 แถว = 1 กฎ · `ที่มา` = task + clause ใน raw SQL ที่อ้างตรงตัว
- `Oracle` = วิธีที่ converted SQL ทำ (FIXED/ACCEPTED ตาม `status/PHASE4_REVIEW_LOG.md`) · ต่างจาก Spark → อ้าง `GAP-nn`
- `Test` = test case ที่ครอบคลุม (Run Pack `TEST_CASE`) — BR ที่ยังไม่มี test = ต้องเพิ่มก่อน G5
- `SA` = ⬜ รอยืนยัน · `✅ SA YYYY-MM-DD` ยืนยันแล้ว (เขียนแทนได้เฉพาะเมื่อ SA ยืนยันในแชต)
- ชื่อ status ของ workflow: _(เติมจาก SQL จริง เช่น MAN / TYP / DUP / MAP / UNMAP)_

## A. Orchestration / checkpoint

| BR | Task | กฎ (ภาษาธุรกิจ) | ที่มา (raw clause) | Oracle | Gap | Test | SA |
|---|---|---|---|---|---|---|---|

## B. อ่านและเตรียมข้อมูล

| BR | Task | กฎ | ที่มา | Oracle | Gap | Test | SA |
|---|---|---|---|---|---|---|---|

## C. Validation และ status

| BR | Task | กฎ | ที่มา | Oracle | Gap | Test | SA |
|---|---|---|---|---|---|---|---|

## D. เขียนผลลัพธ์

| BR | Task | กฎ | ที่มา | Oracle | Gap | Test | SA |
|---|---|---|---|---|---|---|---|

## E. นอก scope ของ package นี้

| BR | Task | กฎ | ที่มา | สถานะ |
|---|---|---|---|---|

## สรุปความครอบคลุม test

| ระดับ | BR |
|---|---|
| ครอบคลุมดี | |
| บางส่วน / ทางอ้อม | |
| ยังไม่มี test | |