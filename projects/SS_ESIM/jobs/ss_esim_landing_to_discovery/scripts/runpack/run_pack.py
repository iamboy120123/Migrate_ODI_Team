"""
run_pack.py — ชื่อเดิมของตัวรัน Run Pack (คงไว้ให้คำสั่งเก่าใช้ได้) · 2.10.0 ส่งต่อให้ run_sql.py ทั้งหมด

    python scripts/runpack/run_pack.py rp01             = run_sql.py rp01 (Terminal: แสดงแผนแล้วถาม · AI: แสดงแผน + คำถามให้ถามคนในแชท)
    python scripts/runpack/run_pack.py rp01 --check     = run_sql.py rp01 --plan (ไม่ต่อฐาน)
    python scripts/runpack/run_pack.py rp01 --only S2b  = run_sql.py rp01 --only S2b
    python scripts/runpack/run_pack.py rp_compile --compile = run_sql.py rp_compile --compile

กติกาทั้งหมดอยู่ที่ run_sql.py / dbx.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_sql  # noqa: E402

if __name__ == "__main__":
    sys.argv = [sys.argv[0]] + ["--plan" if x == "--check" else x for x in sys.argv[1:]]
    sys.exit(run_sql.main())
