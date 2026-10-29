#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspect_reference.py -- dump everything a build needs out of a REAL ODI
SmartExport export, so nothing has to be guessed.

Run this FIRST, before writing any build spec:

    python inspect_reference.py /path/to/SmartExport_xxx.xml
    python inspect_reference.py ref.xml --sql-out ./real_sql     # also dump SQL bodies
    python inspect_reference.py ref.xml --dump-layout SnpStep    # field/type table

What it prints:
  * object counts per class                    -> what the reference can teach
  * topology objects + their GlobalIds         -> answers Group D of the intake
  * SnpOrigTxt standing ids per slot           -> the ids you MUST NOT invent
  * SnpLineTrt execution defaults              -> context/lschema/techno to reuse
  * the package's step chain incl. OkExit      -> the wiring rule, proven
  * procedures and their command lines         -> where each SQL body lives
  * SqlIndGrp rules, with how many examples     -> what it can and cannot settle
    back each one                                  about a new statement
  * conventions readable from this reference    -> and which ones will fall back
                                                   to a literal from elsewhere
  * builder-vs-reference field layout drift    -> whether odi_smartexport.py's
                                                  CANONICAL tables still match
                                                  this ODI version
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from odi_smartexport import (Reference, ORIGTXT_SLOTS,      # noqa: E402
                             FALLBACK_CONVENTIONS)


def safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "unnamed")[:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reference", help="path to a real SmartExport .xml")
    ap.add_argument("--sql-out", help="directory to write every SQL body into")
    ap.add_argument("--dump-layout", metavar="CLASS",
                    help="print the field name/type table for one Snp* class")
    args = ap.parse_args()

    ref = Reference(args.reference)

    if args.dump_layout:
        layout = ref.field_layout(args.dump_layout)
        if layout is None:
            print(f"{args.dump_layout}: not present in this reference")
            return
        for n, t in layout:
            print(f"{n:<28} {t}")
        return

    out = {}

    # ---- counts -----------------------------------------------------------
    out["object_counts"] = dict(sorted(ref.counts().items()))

    # ---- topology ---------------------------------------------------------
    topo = []
    for cls, fields in ref.topology_objects():
        row = {"class": cls, "GlobalId": Reference.val(fields, "GlobalId")}
        for key in ("ConName", "ContextCode", "LschemaName", "SchemaName",
                    "IConnect", "IContext", "ILschema", "IPschema", "ITechno",
                    "JavaDriver", "UserName", "FullTxt"):
            v = Reference.val(fields, key)
            if v is not None:
                row[key] = v
        topo.append(row)
    out["topology_objects"] = topo
    out["topology_fkxrefs"] = [
        {"RefKey": k, "GlobalId": g, "FQName": fq, "FQType": ft}
        for k, g, fq, ft, _l in ref.topology_fkxrefs()
    ]

    # ---- standing SnpOrigTxt ids (never invent these) ---------------------
    out["origtxt_ids"] = {
        slot: {"ITxtOrig": v[0], "OrigineName": v[1],
               "SnpsTable": ORIGTXT_SLOTS[slot][0], "SnpsCol": ORIGTXT_SLOTS[slot][1]}
        for slot, v in ref.origtxt_ids().items()
    }
    missing = [s for s in ORIGTXT_SLOTS if s not in ref.origtxt_ids()]
    if missing:
        out["origtxt_missing_slots"] = missing

    # ---- execution defaults ----------------------------------------------
    out["linetrt_defaults"] = ref.linetrt_defaults()
    out["variable_lschema"] = ref.var_lschema_name()

    # ---- step chain -------------------------------------------------------
    steps = []
    for fields in ref.of_class("SnpStep"):
        steps.append({
            "IStep": Reference.val(fields, "IStep"),
            "StepName": Reference.val(fields, "StepName"),
            "StepType": Reference.val(fields, "StepType"),
            "ITrt": Reference.val(fields, "ITrt"),
            "IVar": Reference.val(fields, "IVar"),
            "OkNextStep": Reference.val(fields, "OkNextStep"),
            "OkExit": Reference.val(fields, "OkExit"),
            "KoExit": Reference.val(fields, "KoExit"),
            "KoNextStep": Reference.val(fields, "KoNextStep"),
            "PosX": Reference.val(fields, "PosX"),
            "PosY": Reference.val(fields, "PosY"),
        })
    steps.sort(key=lambda s: int(s["IStep"] or 0))
    out["step_chain"] = steps

    # ---- procedures + their command lines --------------------------------
    txt_by_id = {Reference.val(f, "ITxt"): Reference.val(f, "Txt")
                 for f in ref.of_class("SnpTxtHeader")}
    procs = []
    for fields in ref.of_class("SnpTrt"):
        itrt = Reference.val(fields, "ITrt")
        lines = []
        for lf in ref.of_class("SnpLineTrt"):
            if Reference.val(lf, "ITrt") != itrt:
                continue
            body = txt_by_id.get(Reference.val(lf, "DefITxt"))
            lines.append({
                "OrdTrt": Reference.val(lf, "OrdTrt"),
                "DefITxt": Reference.val(lf, "DefITxt"),
                "chars": len(body or ""),
                "preview": (body or "")[:90].replace("\n", " "),
            })
        lines.sort(key=lambda l: int(l["OrdTrt"] or 0))
        procs.append({"ITrt": itrt,
                      "TrtName": Reference.val(fields, "TrtName"),
                      "lines": lines})
    out["procedures"] = procs

    # ---- variables --------------------------------------------------------
    out["variables"] = [{
        "IVar": Reference.val(f, "IVar"),
        "VarName": Reference.val(f, "VarName"),
        "sql": txt_by_id.get(Reference.val(f, "ITxtVarIn")),
    } for f in ref.of_class("SnpVar")]

    # ---- what this reference can teach ------------------------------------
    out["sqlindgrp_rules"] = {
        slot: {kw or "(empty)": dict(sorted(counts.items()))
               for kw, counts in rules.items()}
        for slot, rules in ref.sqlindgrp_rules().items()
    }
    out["conventions"] = {cls: ref.conventions(cls)
                          for cls in FALLBACK_CONVENTIONS}
    out["convention_gaps"] = {
        cls: sorted(set(FALLBACK_CONVENTIONS[cls]) - set(ref.conventions(cls)))
        for cls in FALLBACK_CONVENTIONS
        if set(FALLBACK_CONVENTIONS[cls]) - set(ref.conventions(cls))
    }

    # ---- layout drift -----------------------------------------------------
    out["layout_warnings"] = ref.verify_layouts()

    # ---- optional: dump SQL bodies ---------------------------------------
    if args.sql_out:
        os.makedirs(args.sql_out, exist_ok=True)
        written = []
        for p in procs:
            for ln in p["lines"]:
                body = txt_by_id.get(ln["DefITxt"])
                if not body:
                    continue
                fn = os.path.join(args.sql_out,
                                  f"{safe(p['TrtName'])}__ord{ln['OrdTrt']}.sql")
                with open(fn, "w", encoding="utf-8") as fh:
                    fh.write(body)
                written.append(fn)
        for v in out["variables"]:
            if v["sql"]:
                fn = os.path.join(args.sql_out, f"{safe(v['VarName'])}.sql")
                with open(fn, "w", encoding="utf-8") as fh:
                    fh.write(v["sql"])
                written.append(fn)
        out["sql_written"] = written

    # ---- human-readable ---------------------------------------------------
    def head(t):
        print("\n" + t)
        print("-" * len(t))

    head("Object counts")
    for k, v in out["object_counts"].items():
        print(f"  {k:<32} {v}")

    head("Topology objects (clone these VERBATIM -- do not retype)")
    for row in topo:
        extras = " ".join(f"{k}={v}" for k, v in row.items()
                          if k not in ("class", "GlobalId"))
        print(f"  {row['class']:<18} {row['GlobalId']}  {extras}")

    head("Topology FKXRefs")
    for r in out["topology_fkxrefs"]:
        print(f"  {r['RefKey']:<20} {r['GlobalId']}  {r['FQName'] or ''}")

    head("SnpOrigTxt standing ids  (NEVER invent these -- import throws "
         "SnpsInexistantObjectException)")
    for slot, v in out["origtxt_ids"].items():
        print(f"  {slot:<16} ITxtOrig={v['ITxtOrig']:<6} "
              f"{v['SnpsTable']}.{v['SnpsCol']}  \"{v['OrigineName']}\"")
    if missing:
        print(f"  !! missing slots in this reference: {missing} -- export a "
              "reference containing BOTH a Procedure and a Variable")

    head("SnpLineTrt execution defaults")
    for k, v in out["linetrt_defaults"].items():
        print(f"  {k:<18} {v}")
    print(f"  {'Variable LschemaName':<18} {out['variable_lschema']}")

    head("Step chain (note the OkExit rule: 0 while continuing, 1 only at the end)")
    for s in steps:
        print(f"  IStep={s['IStep']:<4} {str(s['StepName'])[:46]:<46} "
              f"type={s['StepType']} ITrt={str(s['ITrt']):<5} "
              f"IVar={str(s['IVar']):<5} Ok->{str(s['OkNextStep']):<5} "
              f"OkExit={s['OkExit']} KoExit={s['KoExit']}")

    head("Procedures")
    for p in procs:
        print(f"  ITrt={p['ITrt']:<5} {p['TrtName']}")
        for ln in p["lines"]:
            print(f"      ord={ln['OrdTrt']:<4} {ln['chars']:>6} chars  {ln['preview']}")

    head("Variables")
    for v in out["variables"]:
        print(f"  IVar={v['IVar']:<4} {str(v['VarName']):<28} "
              f"{(v['sql'] or '')[:70]}")

    head("SqlIndGrp rules this reference teaches (statement kind -> value x times seen)")
    for slot, rules in out["sqlindgrp_rules"].items():
        for kw, counts in sorted(rules.items()):
            shown = ", ".join(f"{g} x{n}" for g, n in counts.items())
            if len(counts) > 1:
                note = "   <-- AMBIGUOUS, must be given explicitly"
            elif sum(counts.values()) < 2:
                note = "   <-- ONE example only, not yet a rule"
            else:
                note = ""
            print(f"  {slot:<14} {kw:<10} {shown}{note}")
    if "linetrt_sql" in out["sqlindgrp_rules"]:
        kws = set(out["sqlindgrp_rules"]["linetrt_sql"])
        for want in ("TRUNCATE", "INSERT", "MERGE"):
            if want not in kws:
                print(f"  !! no {want} example -- a procedure line starting with "
                      f"{want} cannot have its SqlIndGrp derived")

    head("Conventions readable from this reference")
    for cls, conv in out["conventions"].items():
        if conv:
            print(f"  {cls:<14} " + "  ".join(f"{k}={v!r}" for k, v in conv.items()))
    if out["convention_gaps"]:
        print("\n  Not readable -- the builder will use a built-in literal from "
              "another repository and warn:")
        for cls, fields in out["convention_gaps"].items():
            print(f"    {cls:<14} {fields}")

    head("Builder layout check (odi_smartexport.CANONICAL vs this reference)")
    if out["layout_warnings"]:
        for w in out["layout_warnings"]:
            print(f"  ! {w}")
        print("\n  Fix odi_smartexport.py's CANONICAL tables before building, "
              "or the generated objects will not match this ODI version.")
    else:
        print("  OK -- builder field layouts match this reference exactly")

    if args.sql_out:
        head(f"SQL bodies written to {args.sql_out}")
        for fn in out.get("sql_written", []):
            print(f"  {fn}")


if __name__ == "__main__":
    main()
