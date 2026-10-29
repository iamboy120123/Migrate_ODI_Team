# ADR-002: ใช้ ODI Variable (Refresh Query) แทน task precheck

- Status: Proposed
- Date: 2026-10-29
- Deciders: 41642975+iamboy120123@users.noreply.github.com

## Context
workflow ต้นทางมี task ตรวจ landing ก่อนประมวลผล — ใน ODI ทำเป็น procedure ได้ แต่ตัดสินใจ flow (หยุด / ไปต่อ) ไม่ได้

## Options
| Option | ข้อดี | ข้อเสีย |
|---|---|---|
| A. Variable `v_max_partition` / `v_lag_minutes` + (ภายหลัง) Evaluate step | เห็นค่าใน Operator, ทำ fail-fast ได้ | Evaluate (VE) ต้องมี sample จาก Studio ก่อน generate |
| B. Procedure precheck เหมือนเดิม | ง่าย | หยุด package ตามเงื่อนไขไม่ได้ |

## Decision
เลือก A — refresh variable ต้น package; Evaluate `v_lag_minutes <= 120` เพิ่มเมื่อได้ sample

## Consequences
- config: `odi.variables[].replaces_tasks` ตัด task precheck ออกจาก package
- ระหว่างยังไม่มี Evaluate: landing ค้าง package ก็ยังรัน
