# 03 — ODI Package Flow: PKG_SS_ESIM_L2D

ส่วน AUTO สร้างจาก `output/dml/_manifest.json` + `config/config.json` ด้วย `python scripts/pipeline/gen_design_docs.py`

<!-- AUTO:BEGIN -->
_ยังไม่มี manifest — รัน `/convert` และ `/gen-export` ก่อน แล้ว `python scripts/pipeline/gen_design_docs.py`_
<!-- AUTO:END -->

## Error / restart behaviour

| สถานการณ์ | ผล | วิธี restart |
|---|---|---|
| step ใด fail | package หยุด (fail-fast) | แก้สาเหตุ → รัน package ใหม่ทั้งหมด (idempotent?) _(ยืนยัน)_ |
| landing ค้าง | _(ขึ้นกับ Evaluate step — ดู OPEN_DECISIONS)_ | |
