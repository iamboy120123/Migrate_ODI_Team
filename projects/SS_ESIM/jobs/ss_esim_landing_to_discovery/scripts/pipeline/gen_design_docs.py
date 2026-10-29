"""
gen_design_docs.py
------------------
สร้าง / อัปเดตเอกสารออกแบบใน .design/ จาก manifest + config (ไม่ต้องต่อ DB)

    python scripts/pipeline/gen_design_docs.py [--config config/config.json] [--design .design]

เขียนทับเฉพาะส่วนระหว่าง <!-- AUTO:BEGIN --> ... <!-- AUTO:END --> ของ
    .design/03_package_flow.md   ลำดับ step ใน ODI package (ตรงกับ build_odi_export.py)
    .design/04_task_mapping.md   Blendata task -> ODI procedure -> target
และเขียน .design/diagrams/package_flow.mmd ใหม่ทั้งไฟล์
สร้าง .design/specs/<code>_<name>.md ต่อ task เฉพาะไฟล์ที่ยังไม่มี (ไม่ทับงานที่ Claude / SA เขียนแล้ว)
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

BEGIN, END = "<!-- AUTO:BEGIN -->", "<!-- AUTO:END -->"


def load(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


def short_name(task_id: str) -> str:
    """task_<hash>_050100_append_x -> 050100_append_x (เหมือนชื่อ procedure ใน build_odi_export.py)"""
    if task_id.startswith("task_") and task_id.count("_") >= 2:
        return task_id.split("_", 2)[2]
    return task_id


def seq_key(name: str):
    head = name.split("_", 1)[0]
    return ((0, int(head)) if head.isdigit() else (1, 0)), name


def replace_auto(path: Path, body: str) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else f"{BEGIN}\n{END}\n"
    block = f"{BEGIN}\n_สร้างโดย gen_design_docs.py {datetime.now():%Y-%m-%d %H:%M}_\n\n{body.rstrip()}\n{END}"
    if BEGIN in text and END in text:
        pre, rest = text.split(BEGIN, 1)
        post = rest.split(END, 1)[1]
        text = pre + block + post
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return "update"


def md_cell(v) -> str:
    if v is None or v == "" or v == []:
        return "-"
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v)
    return str(v).replace("|", "\\|").replace("\n", " ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.json")
    ap.add_argument("--design", default=".design")
    args = ap.parse_args()

    cfg = load(args.config)
    if cfg is None:
        sys.exit(f"[ERROR] ไม่พบ {args.config}")
    paths = cfg.get("paths", {})
    odi = cfg.get("odi", {})
    design = Path(args.design)

    raw = load(paths.get("raw_manifest", "output/sql/raw/_manifest.json"), [])
    raw = raw.get("tasks", raw) if isinstance(raw, dict) else raw
    dml = load(paths.get("dml_manifest", "output/dml/_manifest.json"), [])
    dml = dml.get("tasks", dml) if isinstance(dml, dict) else dml
    if not raw and not dml:
        print("[SKIP] ยังไม่มี manifest — รัน extract_workflow.py / gen_dml.py ก่อน")
        return

    excluded = [str(x) for x in cfg.get("scope", {}).get("excluded_tasks", [])]
    variables = odi.get("variables", []) or []
    replaced = {str(t) for v in variables for t in v.get("replaces_tasks", [])}

    # raw manifest: task_id = task_<hash>, task_name = <code>_<name>
    raw_by = {}
    for r in raw:
        # K2 (2026-09-30): ใช้ชื่อไฟล์ raw (= ชื่อเดียวกับ DML/procedure) ก่อน — export แบบ tasks[] มี task_name ไม่มี code
        #   เดิมได้ spec ซ้ำ 2 ชุด (load_x.md + T001_load_x.md)
        rf = r.get("raw_sql_file")
        name = short_name(Path(rf).stem) if rf else (r.get("task_name") or short_name(r.get("task_id", "")))
        raw_by[name] = r
    dml_by = {short_name(d["task_id"]): d for d in dml}
    hash_to_name = {r.get("task_id"): n for n, r in raw_by.items()}

    names = sorted(set(raw_by) | set(dml_by), key=seq_key)

    def code(n):
        return n.split("_", 1)[0]

    def status(n):
        c = code(n)
        if c in excluded:
            return "excluded"
        if c in replaced:
            return "variable"
        if n in dml_by:
            return "procedure"
        return "pending"

    # ---------------- 04 task mapping ----------------
    rows = ["| # | Code | Blendata task | Kind / sink | Upstream | ODI | Target | Strategy | Spec |",
            "|---|---|---|---|---|---|---|---|---|"]
    for i, n in enumerate(names, 1):
        r, d = raw_by.get(n, {}), dml_by.get(n, {})
        ups = [hash_to_name.get(p, p) for p in (r.get("parent_task") or [])]
        ups = [code(u) for u in ups]
        st = status(n)
        odi_obj = {"procedure": f"`{n}`", "variable": "ODI variable", "excluded": "— (excluded)",
                   "pending": "_(ยังไม่มี DML)_"}[st]
        spec = f"[spec](specs/{n}.md)" if st in ("procedure", "pending") else "-"
        rows.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            i, code(n), md_cell(n), md_cell(f"{r.get('kind', '-')}/{r.get('sink_mode', d.get('sink_mode', '-'))}"),
            md_cell(ups), odi_obj, md_cell(d.get("target_table") or r.get("target_table")),
            md_cell(d.get("strategy_used")), spec))
    sched = sorted({r.get("schedule_time") for r in raw if r.get("schedule_time")})
    summary = (f"- Workflow: `{cfg.get('odi', {}).get('folder_name', '')}` · schedule (Blendata): "
               f"{', '.join(f'`{s}`' for s in sched) or '-'}\n"
               f"- task ทั้งหมด {len(names)} · procedure {sum(status(n) == 'procedure' for n in names)} · "
               f"variable {sum(status(n) == 'variable' for n in names)} · excluded {sum(status(n) == 'excluded' for n in names)} · "
               f"pending {sum(status(n) == 'pending' for n in names)}\n")
    reasons = cfg.get("scope", {}).get("excluded_reason", {})
    if reasons:
        summary += "\n**Excluded:** " + "; ".join(f"`{k}` — {v}" for k, v in reasons.items()) + "\n"
    print(f"[OK] {replace_auto(design / '04_task_mapping.md', summary + chr(10) + chr(10).join(rows))} .design/04_task_mapping.md")

    # ---------------- 03 package flow ----------------
    steps = []
    for v in variables:
        steps.append(("V", v["name"], "Refresh Variable", v.get("refresh_query", "")))
    for n in names:
        if status(n) == "procedure":
            d = dml_by[n]
            steps.append(("T", n, ", ".join(d.get("steps", [])), d.get("target_table", "")))
    tbl = ["| Seq | Type | Step | รายละเอียด | Target / query |", "|---|---|---|---|---|"]
    for i, (t, nm, det, tg) in enumerate(steps, 1):
        tbl.append(f"| {i} | {'Variable' if t == 'V' else 'Procedure'} | `{nm}` | {md_cell(det)} | {md_cell(tg)} |")
    mmd = ["flowchart TD", "  START([start])"]
    prev = "START"
    for i, (t, nm, _, _) in enumerate(steps, 1):
        node = f"S{i}"
        label = nm.replace('"', "'")
        mmd.append(f'  {node}{"[/" if t == "V" else "["}"{i}. {label}"{"/]" if t == "V" else "]"}')
        mmd.append(f"  {prev} --> {node}")
        prev = node
    mmd += ["  OK([success])", f"  {prev} --> OK", "  FAIL([fail: package หยุด])"]
    mmd += [f"  S{i} -. error .-> FAIL" for i in range(1, len(steps) + 1)]
    pkg_body = (f"Package: `{odi.get('package_name', '')}` · Project: `{odi.get('project_code', '')}` · "
                f"Logical schema: `{odi.get('logical_schema', '')}` / context `{odi.get('context_code', '')}`\n\n"
                + "\n".join(tbl) + "\n\n```mermaid\n" + "\n".join(mmd) + "\n```\n")
    print(f"[OK] {replace_auto(design / '03_package_flow.md', pkg_body)} .design/03_package_flow.md")
    (design / "diagrams").mkdir(parents=True, exist_ok=True)
    (design / "diagrams" / "package_flow.mmd").write_text("\n".join(mmd) + "\n", encoding="utf-8")
    print("[OK] write .design/diagrams/package_flow.mmd")

    # ---------------- specs ต่อ task ----------------
    tpl_path = design / "specs" / "_TASK_SPEC_TEMPLATE.md"
    created = 0
    for n in names:
        if status(n) not in ("procedure", "pending"):
            continue
        out = design / "specs" / f"{n}.md"
        if out.exists():
            continue
        r, d = raw_by.get(n, {}), dml_by.get(n, {})
        conv = (r.get("raw_sql_file") or "").replace("/raw/", "/converted/")
        ups = [code(hash_to_name.get(p, p)) for p in (r.get("parent_task") or [])]
        cols = d.get("columns") or []
        lines = [
            f"# Task spec: {n}", "",
            "> โครงสร้างโดย gen_design_docs.py — Claude เติม Business logic / Rules / Column mapping จาก SQL ด้วย `/design`", "",
            "| รายการ | ค่า |", "|---|---|",
            f"| Blendata task id | `{r.get('task_id', '-')}` |",
            f"| ODI procedure | `{n}` |",
            f"| Target | `{d.get('target_table') or r.get('target_table') or '-'}` |",
            f"| Load strategy | {md_cell(d.get('strategy_used') or r.get('sink_mode'))} |",
            f"| Upstream | {md_cell(ups)} |",
            f"| Raw / converted / DML | `{r.get('raw_sql_file', '-')}` / `{conv or '-'}` / `{d.get('dml_file', '-')}` |",
            f"| Steps | {md_cell(d.get('steps'))} |",
            "", "## Business logic", "_(เติมจาก SQL)_", "",
            "## Rules", "| # | Rule | ที่มา (บรรทัด SQL) |", "|---|---|---|", "",
            "## Column mapping", "| Target column | ที่มา / expression | หมายเหตุ |", "|---|---|---|",
        ]
        lines += [f"| {c} | | |" for c in cols]
        lines += ["", "## Dialect changes (Spark → Oracle)", "| เดิม | ใหม่ | เหตุผล |", "|---|---|---|", "",
                  "## Test cases", "| # | Input | Expected |", "|---|---|---|", "", "## Open questions", ""]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines), encoding="utf-8")
        created += 1
    print(f"[OK] specs: สร้างใหม่ {created} ไฟล์ (ไฟล์ที่มีอยู่แล้วไม่ถูกแก้)" + ("" if tpl_path.exists() else ""))


if __name__ == "__main__":
    main()
