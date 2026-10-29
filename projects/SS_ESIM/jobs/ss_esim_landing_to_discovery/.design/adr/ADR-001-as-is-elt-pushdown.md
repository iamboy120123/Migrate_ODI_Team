# ADR-001: As-Is migration แบบ ELT pushdown (1 Blendata task = 1 ODI procedure)

- Status: Accepted
- Date: 2026-10-29
- Deciders: 41642975+iamboy120123@users.noreply.github.com

## Context
ต้องย้าย `ss_esim_landing_to_discovery` จาก Blendata (Spark SQL) ไป ODI 14.1.2 / Oracle 19c โดยลดความเสี่ยงเรื่องผลลัพธ์ต่าง และให้เทียบผลกับ Blendata ได้ทีละ task

## Options
| Option | ข้อดี | ข้อเสีย |
|---|---|---|
| A. ODI Procedure ต่อ task (SQL pushdown) | แปลงตรง, เทียบผลต่อ task ได้, generate อัตโนมัติ | ไม่ได้ใช้ mapping / lineage ของ ODI |
| B. ODI Mapping + KM | lineage ดี | redesign ทุก task, ใช้เวลามาก, เสี่ยง semantics เปลี่ยน |

## Decision
เลือก A — procedure ต่อ task, SQL แปลง dialect อย่างเดียว, สร้าง Smart Import XML ด้วย `build_odi_export.py` (builder ของ md15 ใน `scripts/odi_builder/`)

## Consequences
- ทุกการแก้ต้องแก้ที่ converted SQL แล้ว regenerate
- lineage อยู่ใน `.design/04_task_mapping.md` แทน ODI mapping
