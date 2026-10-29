-- คอลัมน์ทั้ง schema ปลายทาง (ใช้ร่วมกันทุกงาน) · SELECT อย่างเดียว
-- 1) เปิดไฟล์นี้ใน DBeaver ที่ต่อ Oracle DEV  2) Ctrl+Enter
-- 3) Export ผลเป็น CSV มีหัวคอลัมน์ (UTF-8)  4) วางที่ shared/target/_incoming/ แล้วเลือก 'วางแล้ว ตรวจเลย'
SELECT owner, table_name, column_id, column_name, data_type, data_length,
       data_precision, data_scale, nullable, data_default
FROM   all_tab_columns
WHERE  owner = 'DSSDEV'
ORDER  BY table_name, column_id
