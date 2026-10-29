# .design — เอกสารออกแบบ SS_ESIM_L2D (ss_esim_landing_to_discovery)

| ไฟล์ | เนื้อหา | ใครดูแล |
|---|---|---|
| `01_methodology.md` | วิธีทำงาน AI-assisted migration, phase, courier loop, human vs agent decide | SA (แก้น้อย) |
| `02_architecture.md` | As-Is (Blendata) vs To-Be (ODI / Oracle), data flow | SA + Claude |
| `03_package_flow.md` | ลำดับ step ใน ODI package — ส่วน AUTO สร้างจาก manifest | `gen_design_docs.py` + SA |
| `04_task_mapping.md` | Blendata task → ODI procedure → target table — ส่วน AUTO | `gen_design_docs.py` |
| `adr/` | Architecture Decision Record (1 เรื่อง 1 ไฟล์) | SA อนุมัติ, Claude ร่างด้วย `/adr` |
| `specs/` | design spec ต่อ task (สร้างโครงอัตโนมัติ, Claude เติม logic ด้วย `/design`) | Claude + SA review |
| `diagrams/*.mmd` | Mermaid source: as-is, to-be, package flow (AUTO), courier loop | Claude |

กฎ:
- เนื้อหาระหว่าง `<!-- AUTO:BEGIN -->` … `<!-- AUTO:END -->` ถูกเขียนใหม่ทุกครั้งที่รัน `python scripts/pipeline/gen_design_docs.py` — แก้ด้วยมือนอก block เท่านั้น
- ADR ที่ `Status: Accepted` แล้วห้ามแก้เนื้อหา ถ้าเปลี่ยนใจให้เขียน ADR ใหม่ที่ `Supersedes`
- spec ต่อ task: ส่วน "Business logic" และ "Rules" ต้องเขียนจาก SQL จริง ห้ามเดา — ถ้าไม่ชัดให้ใส่ใน "Open questions"
