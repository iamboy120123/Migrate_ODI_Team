# ADR-003: Courier loop (agent ไม่เข้าระบบจริงโดยตรง)

- Status: Accepted
- Date: 2026-10-29
- Deciders: 41642975+iamboy120123@users.noreply.github.com

## Context
Oracle Dev, ODI Dev และ Blendata ยังไม่อนุญาตให้ agent เชื่อมต่อตรง

## Decision
agent สร้าง Run Pack (สคริปต์ SELECT/DML ธรรมดา + README) → คนรันและ export ผล → agent อ่านผลด้วย `read_run_results.py`

## Consequences
- สคริปต์ต้องรันได้ทุก client (ไม่มี `SET` / `SPOOL`)
- ความเร็วขึ้นกับรอบคนรัน — รวมหลาย check ใน pack เดียว
- เมื่อได้สิทธิ์เชื่อมต่อ (read-only) ค่อยพิจารณา ADR ใหม่เรื่อง direct access
