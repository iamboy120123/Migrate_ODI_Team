---
paths:
  - "output/sql/converted/**"
  - "output/dml/**"
---
# กฎ SQL ที่จะเป็น ODI procedure step (Oracle 19c)

แก้ได้เฉพาะ `output/sql/converted/*.sql` — `output/dml/**` เป็นของ generator (แก้ที่ converted แล้ว `/gen-export`)

1. SQL ธรรมดา **ห้ามมี `;` ท้าย** (ORA-00911) · PL/SQL block ต้องจบด้วย `END;` · ห้ามมีบรรทัด `/`
2. ห้ามอักขระนอก ISO-8859-1 นอก comment (Smart Export เป็น latin-1 → ภาษาไทยกลายเป็น `????`) — comment ภาษาไทยได้ generator ตัดให้
3. alias ที่เป็น Oracle reserved word (เช่น `raw`, `date`, `level`, `comment`) → เติม `_` เฉพาะ alias ห้ามแตะ string literal
4. `''` ใน Oracle = NULL — `col = ''` ไม่มีวันจริง, `col <> ''` ตัด NULL ด้วย → ตรวจ semantics ทุกจุด (ดู skill `spark-oracle-dialect`)
5. ก่อนแปลง expression บนคอลัมน์ของ landing ให้ดูชนิดจริงจาก `all_tab_columns` (ผล `/preflight` P3) — `TO_TIMESTAMP(<TIMESTAMP>)` / `TO_DATE(<DATE>)` แปลงผ่าน NLS แล้วได้ NULL/ผิดเงียบ ๆ (L1, V6 FAIL)
6. ห้าม hardcode schema (`DSSDEV.`) เพิ่ม — V3 นับและต้องเป็น 0 ก่อน G6
7. feature ที่อาจไม่มีใน 19c (`BOOLEAN` ใน SQL, `JSON_TABLE` ขั้นสูง, `SQL_MACRO`) → V3 WARN ต้องยืนยันบน 19c
8. ทุกการแก้ที่ไม่ใช่ dialect ล้วน → บันทึกแถวใน `status/PHASE4_REVIEW_LOG.md`; เปลี่ยน business logic = human-decide (`/decide`)
9. หลังแก้: hook รัน V1 ให้อัตโนมัติ → ต่อด้วย `/gen-export` จน `validate_odi_xml.py` 0 error (XML stale = V2 FAIL)
