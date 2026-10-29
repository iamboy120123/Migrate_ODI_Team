---
description: G5.M2 — เทียบผลระดับแถว Blendata vs Oracle ด้วย scripts/testing/compare_results.py (D2 seed / D3 backtest)
argument-hint: "<blendata.csv> <oracle.csv> [label]"
---
1. input = $ARGUMENTS — ถ้าว่าง ให้หา CSV คู่ล่าสุดใน `input/run_results/` (ไฟล์ผลของ Blendata และ Oracle ของ test case ชุดเดียวกัน) แล้วยืนยันกับ SA ก่อน
2. spec: `config/compare_spec.json` ถ้ามี · ไม่มี → ร่างจาก `references/example/compare_spec.example.json` ให้ตรงกับคอลัมน์ของ workflow นี้ (key / compare / ignore / ts / num) — **กฎส่วนต่างที่ยอมรับ (ACCEPTED) ในตัวอย่างมาจากโปรเจกต์ก่อน ต้องปิดไว้จนกว่าจะมี Q ของโปรเจกต์นี้ที่ SA ปิดแล้ว**
3. `python scripts/testing/compare_results.py --blendata <B> --oracle <O> --out run_packs/<pack>/d2 --label "<label>" [--spec config/compare_spec.json]`
4. อ่าน `D2_REPORT.md` / `D2_DIFF.csv` แล้วสรุป: จำนวนแถวต่อฝั่ง, diff ที่ยังไม่อธิบาย (ต่อคอลัมน์/สาเหตุ), ACCEPTED (อ้าง Q), EXPLAINED
5. diff ที่ยังไม่อธิบาย → `/diagnose` หรือเปิด Q (`/decide`) — ห้ามเพิ่มกฎ ACCEPTED เอง
6. diff = 0 (ยกเว้นส่วนที่ยอมรับ) → เสนอ SA ติ๊ก G5.M2 พร้อม path ของ report
