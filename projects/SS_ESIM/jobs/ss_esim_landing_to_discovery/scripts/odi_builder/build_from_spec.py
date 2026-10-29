#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_from_spec.py -- turn a JSON build spec into an importable ODI 14c
SmartExport zip.

    python build_from_spec.py spec.json
    python build_from_spec.py spec.json --dry-run   # validate, write nothing
    python build_from_spec.py spec.json --force     # overrule the bind-prefix
                                                    # check only

Structural errors -- no package steps, missing topology, a stray ITxtOrig, a
dangling text pointer, malformed XML, text ISO-8859-1 cannot carry -- are never
written out, with or without --force. A package that imports cleanly and then
does nothing is worse than a build that failed, because nobody finds out until
someone runs it.

Since v7 the same refusal covers two SQL faults that also import cleanly and
then fail at RUN time (appendix/C cases 18-19): an INSERT with no column list,
and a table reference with no schema prefix. Since v8, pointing "ddl_file" at
the table structure collected in Q3 adds two more: a column name that does not
exist (ORA-00904) and a NOT NULL column left out of the list (ORA-01400). They are checked by check_sql.py
against every SQL body in the spec. The column-list rule cannot be switched
off. The schema rule is switched off by setting "qualify_tables": false in the
spec, which is only correct when the user chose at Q4 to set CURRENT_SCHEMA on
the Data Server instead -- and that then has to be reported as an open item.

Since v16, pointing "partitions_file" at a CSV/TSV/JSON built from the Q14
answers (TABLE_NAME, PARTITIONS_EMPTY) turns on rule D-R7: a TRUNCATE TABLE
standing in for an Overwrite task whose sinkOption.partitions was non-empty
(appendix/C case 26, checklist item 41 -- the highest-rated risk in the whole
catalog) becomes a hard ERROR instead of a WARN to confirm by hand.
"partitions_file" is not set does not weaken anything already checked: every
TRUNCATE TABLE still gets a WARN either way, it just cannot be escalated to
ERROR without that file.

The spec is the written record of every decision the user signed off on
during intake (see the Q1-Q17 intake in MIGRATE-BLENDATA-TO-ODI-14C.md). Keep it next to the
output zip -- regenerating the package later then costs one command instead
of another round of questions.

Exit code is non-zero when validation finds errors, so this is safe to wire
into a check step.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import odi_smartexport as _lib                                  # noqa: E402
from odi_smartexport import Reference, Doc, rename_bind_prefix  # noqa: E402
import check_sql as _sqlcheck                                   # noqa: E402


def _resolve(spec_dir, path):
    return path if os.path.isabs(path) else os.path.join(spec_dir, path)


# Every SQL body the spec pulls in, in the order it was read, so the SQL
# checks can name the file (or the inline entry) that carries a fault.
_SQL_BODIES = []


def _sql(entry, spec_dir, sql_dir, old_prefix, new_code, label=None):
    """Read a SQL body from 'sql' (inline) or 'sql_file' (path)."""
    if "sql" in entry:
        text = entry["sql"]
    elif "sql_file" in entry:
        base = _resolve(spec_dir, sql_dir) if sql_dir else spec_dir
        path = entry["sql_file"]
        path = path if os.path.isabs(path) else os.path.join(base, path)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    else:
        raise KeyError(f"entry {entry!r} has neither 'sql' nor 'sql_file'")
    if entry.get("strip", True):
        text = text.strip()
    if old_prefix:
        text = rename_bind_prefix(text, old_prefix, new_code)
    _SQL_BODIES.append((entry.get("sql_file") or label or "<inline>", text))
    return text


def _run_sql_checks(schema, qualify, allow, ddl=None, partitions=None):
    """Static SQL checks over every body the spec brought in.

    Returns (errors, warnings, ok_count) as lists of printable strings.
    """
    errors, warnings, oks = [], [], 0
    for label, text in _SQL_BODIES:
        for level, lab, ln, msg in _sqlcheck.check_text(
                text, label, schema=schema, allow=allow, ddl=ddl,
                partitions=partitions):
            if level == "OK":
                oks += 1
                continue
            if not qualify and "schema-qualified" in msg:
                continue
            line = f"{lab}:{ln}  {msg}"
            (errors if level == "ERROR" else warnings).append(line)
    return errors, warnings, oks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="write output despite the bind-variable prefix check, "
                         "the one error a human can reasonably overrule. It "
                         "cannot bypass a structural error or a SQL error.")
    args = ap.parse_args()

    spec_dir = os.path.dirname(os.path.abspath(args.spec))
    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)

    proj = spec["project"]
    new_code = proj["code"]
    old_prefix = spec.get("rename_bind_prefix_from")
    sql_dir = spec.get("sql_dir")

    ref = Reference(_resolve(spec_dir, spec["reference_smartexport"]))
    doc = Doc(ref,
              project_name=proj["name"],
              project_code=new_code,
              folder_name=proj.get("folder", "First Folder"),
              package_name=proj.get("package"))

    doc.clone_topology()
    doc.add_project()
    if spec.get("include_seed_states", True):
        doc.clone_seed_states()

    # sql_ind_grp and ord are optional: the builder derives SqlIndGrp from the
    # statement kind using the reference's own examples, and numbers the
    # command lines 10, 20, 30 by position. Both were previously guessed here
    # from the command order, which put "0" on an append procedure's INSERT.
    for v in spec.get("variables", []):
        doc.add_variable(v["name"],
                         _sql(v, spec_dir, sql_dir, old_prefix, new_code,
                              label=f"variable {v['name']}"),
                         sql_ind_grp=v.get("sql_ind_grp"))

    for p in spec.get("procedures", []):
        lines = [(ln.get("ord"),
                  ln.get("sql_ind_grp"),
                  _sql(ln, spec_dir, sql_dir, old_prefix, new_code,
                       label=f"procedure {p['name']} line {i + 1}"))
                 for i, ln in enumerate(p["lines"])]
        doc.add_procedure(p["name"], lines)

    # An empty/absent "steps" is not a crash: let validate() report it as the
    # structural error it is, so the user sees the whole picture at once.
    if spec.get("steps"):
        doc.add_steps([{"name": s["name"], "type": s["type"], "ref": s["ref"],
                        "pos": tuple(s.get("pos", (100 + 130 * i, 120)))}
                       for i, s in enumerate(spec["steps"])])

    forbid = (f"#{old_prefix}.",) if old_prefix else ()
    report = doc.validate(forbid_prefixes=forbid)

    schema = spec.get("default_schema")
    qualify = spec.get("qualify_tables", True)
    allow = spec.get("allow_unqualified", [])
    ddl = None
    ddl_note = ("ddl_file not set -- checklist items 32-34 (column names exist, "
                "NOT NULL columns covered) stay UNCHECKED")
    if spec.get("ddl_file"):
        ddl = _sqlcheck.load_ddl(_resolve(spec_dir, spec["ddl_file"]))
        ddl_note = "ddl_file: %d table(s) -- %s" % (len(ddl), ", ".join(sorted(ddl)))
    partitions = None
    partitions_note = ("partitions_file not set -- checklist item 41 / rule D-R7 "
                        "(TRUNCATE vs sinkOption.partitions, appendix/C's own "
                        "highest-rated risk) stays at WARN only, never ERROR")
    if spec.get("partitions_file"):
        partitions = _sqlcheck.load_partitions(_resolve(spec_dir, spec["partitions_file"]))
        partitions_note = "partitions_file: %d table(s) -- %s" % (
            len(partitions), ", ".join(sorted(partitions)))
    sql_errors, sql_warnings, sql_oks = _run_sql_checks(
        schema, qualify, allow, ddl, partitions)

    print(f"odi_smartexport {_lib.__version__}\n")
    print("Objects by class:")
    for k, v in report["summary"]["objects_by_class"].items():
        print(f"  {k:<28} {v}")
    print(f"  {'SnpFKXRef':<28} {report['summary']['fkxrefs']}")

    print("\nStep chain:")
    for s in report["summary"]["steps"]:
        print(f"  {s['istep']:>3}  {s['name'][:46]:<46} {s['type']}  "
              f"ref={s['ref'][:34]:<34} Ok->{str(s['ok_next']):<5} "
              f"OkExit={s['ok_exit']}")

    print(f"\nSQL checks (check_sql {_sqlcheck.__version__}): "
          f"{len(_SQL_BODIES)} body(ies), {sql_oks} INSERT(s) OK, "
          f"{len(sql_errors)} error(s), {len(sql_warnings)} warning(s)")
    print(f"  {ddl_note}")
    print(f"  {partitions_note}")
    if not qualify:
        print("  ! qualify_tables=false -- the schema-prefix rule (D-R2) was "
              "SKIPPED. This is only correct when CURRENT_SCHEMA is set on the "
              "Data Server. Record it as an open item in the closing report.")
    for w in sql_warnings:
        print(f"  ! {w}")
    for e in sql_errors:
        print(f"  X [sql] {e}")

    if report["warnings"]:
        print("\nWarnings:")
        for w in report["warnings"]:
            print(f"  ! {w}")

    if report["errors"]:
        fatal = set(report["fatal"])
        print("\nERRORS:")
        for e in report["errors"]:
            print(f"  X {'[structural] ' if e in fatal else '[overridable] '}{e}")
    else:
        print("\nValidation: clean")

    for ex in spec.get("excluded_tasks", []):
        print(f"\nExcluded from the package: {ex.get('task')} -- {ex.get('reason')}")

    # Documentation-only keys (v10). They change nothing in the build; they are
    # reprinted so a rebuild cannot quietly drop a disclosure the first build
    # made. Both belong in the closing report -- appendix/E6 items 10 and 11.
    guessed = spec.get("guessed_column_tables", [])
    if guessed:
        print("\nColumn list GUESSED, not verified against real DDL "
              "(checklist 35) -- these must appear by name in the closing "
              "report, listed apart from the tables that had DDL:")
        for t in guessed:
            print(f"  ? {t}")
    scope = spec.get("overwrite_scope", [])
    if scope:
        print("\nOverwrite scope confirmed with the user (checklist 41):")
        for s in scope:
            print(f"  - {s.get('table')}: {s.get('decision')}"
                  f"{' -- ' + s['note'] if s.get('note') else ''}")
    elif any("truncate" in str(ln.get("sql_file", "")).lower()
             for p in spec.get("procedures", []) for ln in p.get("lines", [])):
        print("\nNOTE: this spec builds at least one TRUNCATE but carries no "
              "'overwrite_scope' record. If the Blendata task overwrote only "
              "some partitions (sinkOption.partitions not empty), TRUNCATE "
              "deletes every other partition permanently -- appendix/C case 26. "
              "Confirm at Q14 and record the answer here before rebuilding.")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 1 if (report["errors"] or sql_errors) else 0

    if sql_errors:
        print(f"\nRefusing to write: {len(sql_errors)} SQL error(s) stand. "
              "These import cleanly and fail at run time (appendix/C cases "
              "18-19), so they are not overridable at any flag. Fix the SQL "
              "and run again.")
        return 1

    if report["fatal"]:
        print(f"\nRefusing to write: {len(report['fatal'])} structural error(s) "
              "stand. These are not overridable at any flag -- the document "
              "itself would be wrong. Fix them and run again.")
        return 1
    if report["errors"] and not args.force:
        print("\nRefusing to write output while errors stand "
              "(--force overrides the bind-prefix check only).")
        return 1
    if report["errors"]:
        print(f"\n--force: writing anyway, overriding {len(report['errors'])} "
              "bind-prefix error(s) listed above.")

    out = spec["output"]
    xml_path, zip_path = doc.write_zip(
        _resolve(spec_dir, out["xml"]),
        _resolve(spec_dir, out["zip"]),
        xml_name=out.get("xml_name_in_zip", "SmartExport.xml"))
    print(f"\nWrote {xml_path}")
    print(f"Wrote {zip_path}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError) as exc:
        # The builder's guards speak in full sentences and name the fix; a
        # traceback on top of that only hides the message.
        print(f"\nBuild stopped: {exc}", file=sys.stderr)
        sys.exit(2)
