"""
agent_reviewer.py
-------------------
Runbook Phase 4 (SQL Review & Resolution) - เฉพาะกรณี AI Mode = "auto"

หน้าที่:
    อ่าน status/REVIEW_FLAGS.md + output/sql/converted/*.sql
    ถ้า ai_mode == "auto": เรียก LLM (Claude) แก้ SQL ที่ถูก flag ตาม
        CLAUDE.md ข้อ 8 "AI Agent Instructions" คือ:
            - OUTPUT ONLY VALID ORACLE SQL CODE
            - ห้ามห่อ markdown code block
            - ห้ามมีคำอธิบาย/ขอโทษ/ข้อความสนทนาใดๆ
            - รักษา indentation/structure เดิมให้มากที่สุด
    ถ้า ai_mode == "manual": สคริปต์นี้จะไม่แก้ไขอะไร แค่พิมพ์คำแนะนำ
        ให้ SA ไปแก้ไฟล์ด้วยตนเอง (เพราะเป็น Human-Decide ตาม RACI)

ข้อกำหนดสำหรับ AI Mode = "auto":
    - ต้องติดตั้ง: pip install anthropic
    - ต้องตั้งค่า environment variable: ANTHROPIC_API_KEY
    - โมเดลอ่านจาก config.json -> ai_review.model (ปรับได้)

คำเตือน (จาก Runbook / RACI): แม้ AI Mode = auto ก็ยังควรมีคนตรวจทานผลลัพธ์
ก่อนเข้า Phase 5 จริง โดยเฉพาะ task ที่ถูก flag เป็น [CRITICAL] เพราะ AI
อาจตีความ business intent ผิดได้หากไม่มี context เพียงพอ

Usage:
    python scripts/pipeline/agent_reviewer.py [--config config/config.json]
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

SYSTEM_PROMPT = """You are acting as agent_reviewer.py inside an As-Is Blendata (Spark SQL) to Oracle 19c
migration pipeline. Rules you MUST follow exactly:
1. OUTPUT ONLY VALID ORACLE 19c SQL CODE.
2. DO NOT wrap the output in Markdown code blocks (no ```sql, no ```).
3. DO NOT provide explanations, apologies, or any conversational text.
4. Maintain the original indentation and structure of the provided SQL as much as possible.
5. Do NOT change business logic, WHERE clauses, or JOIN conditions - this is an As-Is
   platform migration only. Only fix the specific dialect/syntax issue described in the flag reason.
6. If SELECT *, expr appears without a table alias, rewrite as SELECT t.*, expr FROM tbl t
   using a short sensible alias.
7. If TO_DATE(...) has a lowercase or non-Oracle format mask, convert it to the correct
   Oracle format mask (e.g. yyyy-mm-dd -> YYYY-MM-DD). If it clearly represents "now", use TRUNC(SYSDATE).
"""


def load_review_flags(path: Path) -> dict:
    """แปลง status/REVIEW_FLAGS.md (markdown table) กลับเป็น dict {task_id: [reasons]}"""
    if not path.exists():
        sys.exit(f"[ERROR] ไม่พบ {path} - รัน convert_sql.py ก่อน")
    text = path.read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*([^\|]+?)\s*\|\s*([^\|]+?)\s*\|\s*`?([^\|`]*)`?\s*\|\s*([^\|]+?)\s*\|$",
                       text, flags=re.MULTILINE)
    flagged = {}
    for task_id, reason, snippet, status in rows:
        task_id = task_id.strip()
        if task_id in ("Task ID", "-") or re.fullmatch(r"-+", task_id):
            continue  # header row or markdown separator row (|---|---|...)
        if status.strip().upper().startswith("RESOLVED"):
            continue
        flagged.setdefault(task_id.strip(), []).append(reason.strip())
    return flagged


def call_claude_fix(sql_text: str, reasons: list[str], model: str, max_tokens: int) -> str:
    try:
        import anthropic
    except ImportError:
        sys.exit(
            "[ERROR] ต้องติดตั้งก่อน: pip install anthropic\n"
            "        และตั้งค่า ANTHROPIC_API_KEY ใน environment variable"
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("[ERROR] ไม่พบ ANTHROPIC_API_KEY ใน environment variable")

    client = anthropic.Anthropic(api_key=api_key)

    reason_text = "\n".join(f"- {r}" for r in reasons)
    user_prompt = (
        f"Flag reasons for this SQL task:\n{reason_text}\n\n"
        f"SQL to fix:\n{sql_text}"
    )

    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    fixed = "".join(block.text for block in resp.content if hasattr(block, "text"))
    # กันเคส AI แอบห่อ markdown มาทั้งที่สั่งห้ามแล้ว
    fixed = re.sub(r"^```(sql)?\s*|\s*```$", "", fixed.strip(), flags=re.IGNORECASE)
    return fixed.strip()


def update_review_flags_status(path: Path, resolved_task_ids: set, note: str):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    out = []
    for line in lines:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 5 and parts[1] in resolved_task_ids:
            parts[-2] = f"RESOLVED ({note})"
            line = "| " + " | ".join(parts[1:-1]) + " |"
        out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.json")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    ai_mode = config.get("ai_mode", "manual")
    converted_dir = Path(config["paths"]["output_converted_sql"])
    review_flags_path = Path(config["paths"]["review_flags"])

    flagged = load_review_flags(review_flags_path)

    if not flagged:
        print("[INFO] ไม่มีรายการค้างใน status/REVIEW_FLAGS.md -> ข้าม Phase 4 ไปที่ gen_dml.py ได้เลย")
        return

    if ai_mode != "auto":
        print(f"[INFO] AI Mode = '{ai_mode}' -> สคริปต์นี้จะไม่แก้ไขไฟล์ใดๆ")
        print("[ACTION REQUIRED] กรุณาแก้ไข SQL ต่อไปนี้ด้วยตนเองใน output/sql/converted/:")
        for task_id, reasons in flagged.items():
            print(f"  - {task_id}: {', '.join(reasons)}")
        print("\nหลังแก้เสร็จ ให้เปลี่ยน status ในแถวนั้นของ status/REVIEW_FLAGS.md เป็น RESOLVED (manual)")
        return

    # ai_mode == "auto"
    model = config.get("ai_review", {}).get("model", "claude-sonnet-4-5")
    max_tokens = config.get("ai_review", {}).get("max_tokens", 4096)

    resolved = set()
    for task_id, reasons in flagged.items():
        sql_path = None
        for candidate in converted_dir.glob(f"{task_id}*.sql"):
            sql_path = candidate
            break
        if sql_path is None:
            print(f"[WARN] ไม่พบไฟล์ SQL สำหรับ {task_id} - ข้าม")
            continue

        original = sql_path.read_text(encoding="utf-8")
        print(f"[AI] กำลังแก้ {task_id} ({', '.join(reasons)}) ...")
        fixed = call_claude_fix(original, reasons, model, max_tokens)
        sql_path.write_text(fixed, encoding="utf-8")
        resolved.add(task_id)
        print(f"[OK] {task_id} แก้แล้ว -> {sql_path}")

    update_review_flags_status(review_flags_path, resolved, "AI")

    print(f"\n[SUMMARY] AI แก้ไปทั้งหมด {len(resolved)}/{len(flagged)} task")
    print("[ACTION REQUIRED] SA ควรสุ่มตรวจ task ที่เป็น [CRITICAL] ก่อนเข้า Phase 5 จริง")
    print("\nขั้นตอนถัดไป: python scripts/pipeline/gen_dml.py")


if __name__ == "__main__":
    main()
