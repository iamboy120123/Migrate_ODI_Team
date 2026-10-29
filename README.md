# Migration Workspace — Blendata → ODI 14c (ทีม)

สร้างโดย `setup_migrate.ps1 -Mode Workspace` (2.10.0) · 1 repo ทั้งทีม · ของกลางชุดเดียว · แต่ละงานแยกโฟลเดอร์ แยกแชท แยก branch

## เริ่มต้น (ทำทีละข้อ)

| ใคร | ทำอะไร | คำสั่ง |
|---|---|---|
| Tech Lead (ครั้งเดียว) | ตั้งทีม 12 ข้อ | `python tools/workspace.py init` |
| Tech Lead (ครั้งเดียว) | ตั้ง GitHub (CI · ใบงานปักหมุด · labels) | `python tools/workspace.py init-github` |
| ทุกคน | ดึงของล่าสุด | `git switch main && git pull` · `python tools/workspace.py fix-mtime` · `python tools/workspace.py sync-kit --all` |
| เจ้าของงาน | เปิดงานใหม่ | `python tools/workspace.py new-job` |
| เจ้าของงาน | ทำงานในแชท | เปิด Claude Code ที่ `projects/<P>/jobs/<job>/` แล้ว `/next-step` |
| เจ้าของงาน | ก่อน / หลัง Smart Import | `import-lock --job <job>` · `import-unlock --job <job>` |
| Tech Lead | เพิ่ม / แก้การเชื่อมต่อฐาน (SIT / PROD · user ที่เขียนได้) | `python tools/workspace.py db-connect --env SIT` |
| ทุกคน | ดูสถานะ | `python tools/workspace.py status` (เลือกเลขเพื่อดูงานนั้นทุกขั้น) · ในแชท `/status` |

Windows: ใช้ `tools\ws.cmd <คำสั่ง>` แทน `python tools\workspace.py <คำสั่ง>` ได้

## โครง

```
tools/          workspace.py + wscore/ (คำสั่งทั้งหมด)
kit/            setup_migrate.ps1 · CLAUDE.kit.md (กฎทีมของ AI) · job/ (ไฟล์ที่วางลงทุกงาน) · patches/ · lessons-learned.md
shared/         team.json (ค่าของทีม) · approvers.txt · target/ (Smart Export + คอลัมน์ DEV ชุดเดียว)
projects/<P>/   _project/ (glossary · DECISIONS) · jobs/<job>/ (1 Blendata workflow = 1 ODI package)
registry/       สร้างใหม่ได้เสมอ ไม่ commit (jobs.csv · import_log.csv · lessons.csv)
STATUS.md       สร้างโดย report ไม่ commit
```

## กติกาสำคัญ 5 ข้อ

1. 1 งาน = 1 โฟลเดอร์ = 1 แชท = 1 branch
2. จบขั้นต้อง `/update-status` แล้ว push
3. ห้าม import โดยไม่ผ่าน `import-lock`
4. ✅ มาจากผู้อนุมัติเท่านั้น (PR `/approve …` หรือ commit จากบัญชีผู้อนุมัติ)
5. AI จะเขียนขึ้น GitHub หรือต่อฐาน ต้องได้รับอนุญาตก่อน

## สิ่งที่ยังต้องยืนยันบนระบบจริง

- GitHub Actions 4 ตัว (approve-command · verify-approvals · secret-scan · workspace-check) — ต้องเปิด Actions ใน org และ Workflow permissions = Read and write
- ชื่อตาราง `SNP_*` ของ ODI 14c ที่ใช้ตรวจรหัสซ้ำ (import-lock) และเวลาต่อ step (perf_summary) — ยังไม่ยืนยันกับ repository ของทีม
- `run_sql.py` ต่อ Oracle จริง (ต้อง `pip install oracledb` + ตัวแปร `ORA_RO_PASSWORD` / `ORA_RW_PASSWORD`) · ทั้งอ่านและเขียน (DML / DDL) · การยืนยันชื่อตารางก่อนลบ
- Smart Import ของแพ็กเกจที่ generate ตั้งแต่ต้นจนจบ
