# input/ — ทุกอย่างที่คนเป็นคนให้ (AI อ่านอย่างเดียว)

แยกโฟลเดอร์ตามหัวข้อ · ไม่มีไฟล์ที่ kit สร้างอยู่ในนี้ (ค่าตั้งของ kit อยู่ `config/` · ตัวอย่างอยู่ `references/example/`)

| โฟลเดอร์ | ใส่อะไร | ใครเอามา | ใช้ทำอะไร |
|---|---|---|---|
| `input/blendata/` | ไฟล์เก่าจาก Blendata ทั้งหมด: export_workflow.json (บังคับ) · เอกสาร · ข้อมูลเทส · expected_results.csv · .sql seed | เจ้าของงาน / ผู้ดูแล Blendata | ต้นทางของการแปลงทั้งหมด |
| `input/odi_reference/` | Smart Export (.xml / .zip) ของ repository ปลายทางที่จะ import จริง | ODI Studio ของ repository ปลายทาง | Logical Schema · Context · เวอร์ชัน repository · GUID ของ Topology |
| `input/oracle_ddl/` | ผล `all_tab_columns` ของตารางปลายทาง (CSV มีหัว TABLE_NAME, COLUMN_NAME) | คนรัน query จาก Run Pack `T1` แล้ว export | `check_sql.py --ddl` · column list ของ INSERT |
| `input/run_results/<pack>/` | ผลที่คนรัน Run Pack แล้ว export (CSV / ภาพ) · `profile_result.csv` วางที่ `input/run_results/` | คนรันบน Oracle / ODI | `/read-results` |