#!/usr/bin/env python3
"""check_sql.py -- static checks on translated Oracle SQL, no database needed.

Enforces the rules in knowledge/reference/spark-to-oracle-sql.md of knowledge/reference/migration-rules.md. D-R1 and
D-R2 came from a package that imported cleanly and then failed at RUN time;
D-R3 and the name checks were added in v10 after this very script was found to
both miss real faults and block valid SQL.

  D-R1  every INSERT carries an explicit column list, and the number of names in
        that list equals the number of top-level expressions in its SELECT.
        This covers the INSERT branch of MERGE and every branch of INSERT ALL,
        not only a bare INSERT INTO.
        (knowledge/lessons-learned.md cases 18 and 22 -- ORA-00947 / ORA-00913, and the silent
        variant where the counts happen to match but the ORDER does not)

  D-R2  every table reference is schema-qualified.
        (knowledge/lessons-learned.md case 19 -- ORA-00942, and the silent variant where a
        same-named table exists in the connecting user's own schema)

  D-R3  one statement per file, no trailing semicolon, never empty.
        (knowledge/lessons-learned.md cases 24 and 29 -- ORA-00911, and the command line that
        imports cleanly and does nothing)

  names every name in a column list must be usable as an unquoted Oracle
        identifier: not a reserved word, not over-long, not double-quoted.
        (knowledge/lessons-learned.md case 25 -- the hazards the v9 guess mode introduced)

  D-R4  every self-chosen alias (table alias, subquery alias, CTE name) is not
        an Oracle reserved word. This is a different fault from the "names"
        check above: that one is about a GUESSED COLUMN name, which the DDL
        can prove wrong or right; an alias never comes from DDL at all, so it
        can collide with a reserved word (RAW is the one that actually hit
        this project) even when the column list and DDL are both correct.
        Needs no DDL -- always checked.
        (knowledge/lessons-learned.md case 34 -- ORA-00936/ORA-00903)

  D-R5  every UNION / UNION ALL compares its branches position by position
        (that is how Oracle actually does it, not by column name) and flags
        any position where the branches' DDL datatypes disagree -- most
        urgently a CLOB/BLOB/NCLOB/LONG side mixed with a non-LOB side.
        Only the plain, single-table-per-branch shape is checked; a branch
        with a JOIN, a comma-joined table list, or a FROM-subquery is left
        alone with a WARN rather than guessed at. Needs --ddl with a
        DATA_TYPE column.
        (knowledge/lessons-learned.md case 35 -- ORA-01790)

  D-R6  TO_DATE / TO_TIMESTAMP is never called with just one argument. With no
        format mask both parse a string using the *agent's* session NLS
        setting (NLS_DATE_FORMAT / NLS_TIMESTAMP_FORMAT), which is not a
        property of the SQL text -- the same statement can raise ORA-01858 on
        one agent and silently parse the wrong date on another. Pure syntax
        check (argument count), needs no DDL, always checked. A single-
        argument TO_CHAR/TO_NUMBER is handled separately, see "also" below --
        it is not folded into D-R6 itself.

        v1.5.0 added a second, DDL-dependent half of this rule: a
        TO_DATE/TO_TIMESTAMP call -- WITH OR WITHOUT a format mask -- that
        wraps a column the --ddl file lists as already DATE/TIMESTAMP is now
        an ERROR. A present-but-wrong mask is exactly how TEST_AI_GEN_13
        broke: effective_date/expired_date were already TIMESTAMP, and
        TO_DATE(effective_date, 'YYYY-MM-DD') forced an implicit
        TIMESTAMP->VARCHAR2->TO_DATE round-trip through the session's
        NLS_TIMESTAMP_FORMAT instead of a no-op -- ORA-01858 on one agent,
        nothing on another. The argument-count check above could not have
        caught it: a mask was present. This half matches by bare column name
        only, not by join/alias resolution, so a name collision across
        unrelated tables in the same --ddl file can false-positive; every
        finding names the matching table(s) so that is easy to spot. Needs
        --ddl; silently skipped without it, same as D-R5.

        v1.6.0 adds a third, also DDL-dependent half: a DATE/TIMESTAMP
        column (per --ddl) compared directly to a string literal with NO
        TO_DATE/TO_TIMESTAMP wrapper on either side (=, <>, !=, <, <=, >,
        >=, or BETWEEN) is also an ERROR -- same NLS fallback as the wrapped
        case, just with no function call to anchor on. This is the other
        half of what checklist item 43 and knowledge/lessons-learned.md case 28 already named
        in prose ("do not compare a string to a DATE column directly") but
        that v1.5.0 did not implement: v1.5.0 only looked inside
        TO_DATE/TO_TIMESTAMP calls, so a bare WHERE effective_date =
        '20250101' with no TO_DATE at all was never examined. Same name-
        only matching caveat as the other DDL-dependent halves. Needs --ddl;
        silently skipped without it.
        (checklist item 43, knowledge/reference/spark-to-oracle-sql.md rule C12)

  D-R8  (v1.7.0) a TO_DATE/TO_TIMESTAMP call that parses text with a numeric
        mask (YYYYMMDD...) but with no REGEXP_LIKE shape guard anywhere in the
        statement is a WARN. Oracle parses leniently: TO_TIMESTAMP('20260827',
        'YYYYMMDDHH24MISS' DEFAULT NULL ON CONVERSION ERROR) returns
        2026-08-27 00:00:00 instead of NULL, while Spark's to_timestamp returns
        NULL for an input shorter than the pattern. DEFAULT NULL ON CONVERSION
        ERROR does NOT make parsing strict. Guard with REGEXP_LIKE(x, '^[0-9]{N}$')
        or an FX mask. WARN only -- never ERROR (knowledge/lessons-learned.md case 37).

  D-R7  (v1.6.0) a TRUNCATE TABLE is cross-checked against a --partitions
        file built from the Q14 answers: if sinkOption.partitions was
        non-empty for that table, TRUNCATE TABLE is an ERROR, because the
        source job only ever overwrote specific partitions and a blind
        TRUNCATE deletes every other partition's history permanently, with
        no Oracle error, and a row-count check at validation level 1
        (knowledge/reference/validation-and-cutover.md E1) still looks correct afterwards because it only
        compares the rows just loaded. This is knowledge/lessons-learned.md's own
        highest-rated risk (case 26, checklist item 41) and had no automated
        backstop at all before v1.6.0. Unlike D-R5 and the rest of D-R6,
        this one is never silent: without --partitions every TRUNCATE TABLE
        still gets a WARN to confirm by hand, because the cost of one extra
        line to read is far lower than the cost of a silent, irreversible
        delete.
        (checklist item 41, knowledge/lessons-learned.md case 26)

  also  a single-argument TO_CHAR/TO_NUMBER call (no format mask) gets a
        WARN -- not folded into D-R6 because TO_CHAR/TO_NUMBER are used for
        far more than dates, so a missing mask there cannot be escalated to
        ERROR the way a known-DATE column can; it only flags the gap for a
        human to judge. Needs no DDL, always checked.
        (checklist item 43)

What it does NOT do: it never connects to a database, so it cannot know how many
columns the target table really has. Checklist item 32 -- comparing the column
list against all_tab_columns -- still needs DDL from the user.

With --ddl it also closes ORA-00904 and ORA-01400: it then knows the real
columns of every target table, so it can say that a listed name does not exist,
and that a NOT NULL column with no DEFAULT was left out of the list. Which of
those two checks is actually live depends on the columns present in the DDL
file, and the run prints which ones are on -- a missing NULLABLE column silently
disables the ORA-01400 check, so it is never left unsaid. A DATA_TYPE column
turns on the D-R5 UNION datatype check (checklist item 51) the same way.

Usage
    python check_sql.py <file-or-folder> [...]          check everything
    python check_sql.py <dir> --schema myschema         also require that prefix
    python check_sql.py <dir> --ddl target_columns.csv  check names against the
                                                        real table structure
    python check_sql.py <dir> --partitions q14.csv      cross-check TRUNCATE
                                                        against Q14 answers
    python check_sql.py <dir> --allow-unqualified a,b   tolerate these names
    python check_sql.py --selftest                      run the built-in tests

--ddl takes the output of the query in knowledge/lessons-learned.md case 18 -- CSV/TSV with a
header row, or JSON -- with at least TABLE_NAME and COLUMN_NAME. Add NULLABLE
and DATA_DEFAULT and the ORA-01400 check turns on too; add DATA_TYPE and the
D-R5 UNION check (ORA-01790, checklist 51) turns on. Column order in the file
does not matter; matching is by name.

--partitions takes a CSV/TSV/JSON file built from the Q14 answers: one row
per table with TABLE_NAME and PARTITIONS_EMPTY (Y/N) -- Y means
sinkOption.mode was Overwrite with an empty sinkOption.partitions array for
that table (a blind TRUNCATE TABLE is correct), N means partitions was
non-empty (TRUNCATE TABLE is an ERROR; only the named partitions may be
cleared). A table that never appears in the file gets a WARN, not silence --
TRUNCATE TABLE always produces a finding, with or without --partitions
(checklist item 41, rule D-R7, knowledge/lessons-learned.md case 26).

Exit code is 1 when any [ERROR] was printed, 0 otherwise. [WARN] never fails
the run.  Python 3.8+, standard library only.
"""

import csv
import io
import json
import os
import re
import sys

__version__ = "1.7.0"

# Names that are legal without a schema prefix.
BUILTIN_UNQUALIFIED = {"dual"}

# Keywords that introduce a table reference.
_TABLE_INTRO = re.compile(
    r"\b(insert\s+into|merge\s+into|truncate\s+table|update|from|join)\s+",
    re.IGNORECASE,
)
_IDENT = re.compile(r"[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*")


def paren_table_start(masked, k):
    """K1 (SS_PAYMENT_3BB_VDO 2026-10-15): `FROM ( tb_x CROSS JOIN ...)` -- a parenthesised join, not a subquery.
    Return the index of the table name after '(' or None when the parenthesis opens a subquery (SELECT/WITH)."""
    j = k + 1
    while j < len(masked) and masked[j].isspace():
        j += 1
    im = _IDENT.match(masked, j)
    if not im or im.group(0).lower() in ("select", "with"):
        return None
    return j

# Functions whose argument list uses FROM as a separator, not as a table
# reference: EXTRACT(YEAR FROM d), TRIM(LEADING '0' FROM c), SUBSTRING(s FROM 1).
# Before v10 the word FROM inside these was read as "a table follows", and every
# such expression produced a bogus D-R2 error that blocked the build.
_FUNC_FROM = re.compile(r"\b(extract|trim|substring|overlay)\s*\(", re.IGNORECASE)

# D-R6: called with exactly one argument, both of these parse a string using
# the agent's session NLS format -- not a property of the SQL text.
_DATE_FUNCS = re.compile(r"\b(TO_DATE|TO_TIMESTAMP)\s*\(", re.IGNORECASE)
# D-R6 part 2 (v1.5.0): first argument must be a simple (optionally
# alias-qualified) identifier before it is matched against --ddl by bare
# column name.
_DATE_ARG_IDENT_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*)?$")
_DATE_DDL_TYPES = ("date", "timestamp")

# D-R6 part 3 / the TO_CHAR,TO_NUMBER note (v1.6.0): a column (or a bare
# literal on the other side) compared directly against a string literal, no
# TO_DATE/TO_TIMESTAMP wrapper at all.
_CMP_OPS = r"(?:<=|>=|<>|!=|=|<|>)"
_CMP_IDENT = r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)?"
_DATE_CMP_LEFT_RE = re.compile(
    r"\b(" + _CMP_IDENT + r")\s*" + _CMP_OPS + r"\s*'")
_DATE_CMP_RIGHT_RE = re.compile(
    r"'[^']*'\s*" + _CMP_OPS + r"\s*\b(" + _CMP_IDENT + r")\b")
_DATE_BETWEEN_RE = re.compile(
    r"\b(" + _CMP_IDENT + r")\s+between\s+'[^']*'\s+and\s+'[^']*'",
    re.IGNORECASE)
_TO_CHAR_NUM_FUNCS = re.compile(r"\b(TO_CHAR|TO_NUMBER)\s*\(", re.IGNORECASE)

# D-R8 (v1.7.0): lenient text->date parsing without a shape guard.
_PARSE_FUNCS_RE = re.compile(r"\b(TO_TIMESTAMP|TO_DATE)\s*\(", re.IGNORECASE)
_REGEXP_GUARD_RE = re.compile(r"\bREGEXP_LIKE\s*\(", re.IGNORECASE)
_NUMERIC_MASK_RE = re.compile(r"'[^']*(?:YY|MM|DD|HH|MI|SS)[^']*'", re.IGNORECASE)

# D-R7 (v1.6.0): TRUNCATE TABLE vs the Q14 answer for sinkOption.partitions.
_TRUNCATE_TABLE_RE = re.compile(r"\btruncate\s+table\s+", re.IGNORECASE)

# Words that can follow a table-introducing keyword but are never a table name.
# "set" is the one that matters: MERGE ... WHEN MATCHED THEN UPDATE SET c = v
# used to be read as "UPDATE <table SET>" and reported as unqualified.
_NOT_A_TABLE = {
    "set", "select", "values", "where", "from", "join", "on", "using", "when",
    "then", "and", "or", "not", "case", "null", "table", "into", "distinct",
    "all", "exists", "by", "order", "group", "having", "union", "with",
}

_MERGE_INTO = re.compile(r"\bmerge\s+into\s+", re.IGNORECASE)
_MERGE_INSERT = re.compile(
    r"\bwhen\s+not\s+matched\s+(?:by\s+target\s+)?then\s+insert\b", re.IGNORECASE)
_MERGE_UPDATE = re.compile(
    r"\bwhen\s+matched\s+then\s+update\s+set\b", re.IGNORECASE)
_INSERT_ALL = re.compile(r"\binsert\s+(?:all|first)\b", re.IGNORECASE)
_ALL_BRANCH = re.compile(r"\binto\s+", re.IGNORECASE)
_PLSQL_START = re.compile(r"\s*(begin|declare)\b", re.IGNORECASE)

# Oracle reserved words: they cannot be used as unquoted identifiers at all.
# A guessed column list that copies a Spark field name straight across lands on
# one of these more often than it sounds -- date, level, number, comment, uid
# are ordinary column names in a Spark schema.
ORACLE_RESERVED = {
    "access", "add", "all", "alter", "and", "any", "as", "asc", "audit",
    "between", "by", "char", "check", "cluster", "column", "comment",
    "compress", "connect", "create", "current", "date", "decimal", "default",
    "delete", "desc", "distinct", "drop", "else", "exclusive", "exists",
    "file", "float", "for", "from", "grant", "group", "having", "identified",
    "immediate", "in", "increment", "index", "initial", "insert", "integer",
    "intersect", "into", "is", "level", "like", "lock", "long", "maxextents",
    "minus", "mlslabel", "mode", "modify", "noaudit", "nocompress", "not",
    "nowait", "null", "number", "of", "offline", "on", "online", "option",
    "or", "order", "pctfree", "prior", "public", "raw", "rename", "resource",
    "revoke", "row", "rowid", "rownum", "rows", "select", "session", "set",
    "share", "size", "smallint", "start", "successful", "synonym", "sysdate",
    "table", "then", "to", "trigger", "uid", "union", "unique", "update",
    "user", "validate", "values", "varchar", "varchar2", "view", "whenever",
    "where", "with",
}

# Set by load_ddl() so the caller can report which DDL-backed checks are live.
LAST_DDL_META = {}

# --------------------------------------------------------------------------- #
# D-R4: alias (table / subquery / CTE) must not collide with a reserved word
# --------------------------------------------------------------------------- #
# Keywords that introduce a table or subquery an alias can follow. Separate
# from _TABLE_INTRO (which drives D-R2 and must not change): this one also
# covers UPDATE's own target and MERGE's USING clause, both of which commonly
# carry an alias in this project's house style.
_ALIAS_INTRO = re.compile(
    r"\b(from|join|update|using|merge\s+into)\s+", re.IGNORECASE)

# Words that can legally sit right after a table/subquery reference without
# being an alias -- a clause keyword, not a self-chosen name. Getting this
# list wrong only costs a missed check, never a false ERROR: flag() below
# still requires the word to also be in ORACLE_RESERVED, and none of these
# ordinary clause keywords collide with a real ETL alias by accident.
_ALIAS_STOPWORDS = _NOT_A_TABLE | {
    "on", "inner", "outer", "left", "right", "full", "cross", "natural",
    "connect", "start", "loop", "end", "for", "partition", "pivot",
    "unpivot", "sample", "lateral",
}
_AS_ALIAS = re.compile(r"\s*\bas\b\s*([A-Za-z_][\w$#]*)", re.IGNORECASE)
_BARE_ALIAS = re.compile(r"\s*([A-Za-z_][\w$#]*)")

# --------------------------------------------------------------------------- #
# D-R5: UNION / UNION ALL branches must agree on datatype, position by position
# --------------------------------------------------------------------------- #
_UNION_SPLIT = re.compile(r"\bunion\b(?:\s+all\b)?", re.IGNORECASE)
_UNION_BRANCH_STOP = re.compile(
    r"\bwhere\b|\bgroup\b|\border\b|\bconnect\b|\bstart\b|\bhaving\b",
    re.IGNORECASE)
_SIMPLE_FROM = re.compile(
    r"\bfrom\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*)", re.IGNORECASE)
_JOIN_KW = re.compile(r"\bjoin\b", re.IGNORECASE)
_SIMPLE_COL = re.compile(
    r"^([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)"
    r"(?:\s+(?:as\s+)?[A-Za-z_][\w$]*)?$",
    re.IGNORECASE)
_LOB_TYPES = {"clob", "blob", "nclob", "long", "long raw"}


# --------------------------------------------------------------------------- #
# masking: blank out comments and string bodies, preserving every offset
# --------------------------------------------------------------------------- #
def mask(sql):
    """Return sql with comments and string contents replaced by spaces/'x'.

    Length and every character offset are preserved, so positions found in the
    masked text point at the same place in the original.
    """
    out = list(sql)
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                out[i] = " "
                i += 1
        elif c == "/" and i + 1 < n and sql[i + 1] == "*":
            out[i] = out[i + 1] = " "
            i += 2
            while i < n and not (sql[i] == "*" and i + 1 < n and sql[i + 1] == "/"):
                if sql[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                if i + 1 < n:
                    out[i + 1] = " "
                i += 2
        elif c == "'":
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":   # escaped quote
                        out[i] = out[i + 1] = "x"
                        i += 2
                        continue
                    break
                out[i] = "x" if sql[i] != "\n" else "\n"
                i += 1
            i += 1
        elif c == '"':
            i += 1
            while i < n and sql[i] != '"':
                out[i] = "x" if sql[i] != "\n" else "\n"
                i += 1
            i += 1
        else:
            i += 1
    return "".join(out)


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def match_paren(masked, open_pos):
    """Index just past the ')' that closes the '(' at open_pos, or -1."""
    depth = 0
    for i in range(open_pos, len(masked)):
        if masked[i] == "(":
            depth += 1
        elif masked[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def split_top(masked, start, end):
    """Split masked[start:end] on commas that sit at paren depth 0."""
    parts, depth, last = [], 0, start
    for i in range(start, end):
        ch = masked[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append((last, i))
            last = i + 1
    parts.append((last, end))
    return [p for p in parts if masked[p[0]:p[1]].strip()]


def select_list_span(masked, start):
    """Span of the top-level SELECT list that begins at/after start.

    Returns (list_start, list_end, select_pos) or None. list_end is the offset
    of the FROM that closes the list, or the end of the statement for a
    FROM-less SELECT.
    """
    m = re.compile(r"\bselect\b", re.IGNORECASE).search(masked, start)
    if not m:
        return None
    i = m.end()
    # optional DISTINCT / ALL / UNIQUE right after SELECT
    m2 = re.compile(r"\s*\b(distinct|unique|all)\b", re.IGNORECASE).match(masked, i)
    if m2:
        i = m2.end()
    depth, j = 0, i
    while j < len(masked):
        ch = masked[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                return (i, j, m.start())       # SELECT inside a wrapper
            depth -= 1
        elif depth == 0 and (ch in "Ff") and re.match(r"from\b", masked[j:j + 5], re.I):
            if j == 0 or not (masked[j - 1].isalnum() or masked[j - 1] == "_"):
                return (i, j, m.start())
        j += 1
    return (i, len(masked), m.start())


def mask_func_from(masked):
    """Blank out the word FROM where it separates function arguments.

    EXTRACT(YEAR FROM d) and TRIM(LEADING '0' FROM code) are expressions, not
    table references. Length and offsets are preserved.
    """
    out = list(masked)
    for m in _FUNC_FROM.finditer(masked):
        open_pos = m.end() - 1
        close = match_paren(masked, open_pos)
        if close < 0:
            continue
        for fm in re.finditer(r"\bfrom\b", masked[open_pos:close], re.IGNORECASE):
            for i in range(open_pos + fm.start(), open_pos + fm.end()):
                out[i] = " "
    return "".join(out)


_CTE_NAME = re.compile(r"\s*([A-Za-z_][\w$]*)")
_CTE_AS = re.compile(r"\s*\bas\b", re.IGNORECASE)
_CTE_OPEN = re.compile(r"\s*\(")
_CTE_COMMA = re.compile(r"\s*,")
_CTE_WITH = re.compile(r"\s*\bwith\b", re.IGNORECASE)


def parse_with(masked, pos):
    """Parse a WITH block starting at/after pos.

    Returns (names, end, positions). end is the offset just past the last
    CTE body, or pos when there is no WITH block here. positions maps
    each lower-cased name to (raw spelling, offset of the name token) -- used
    by D-R4 to report a reserved-word CTE name at the right line. Handles
    both name AS (...) and name (col, col) AS (...), and any number of
    comma-separated CTEs.
    """
    m = _CTE_WITH.match(masked, pos)
    if not m:
        return set(), pos, {}
    names, i, positions = set(), m.end(), {}
    while True:
        nm = _CTE_NAME.match(masked, i)
        if not nm:
            return names, pos, positions
        raw_name = masked[nm.start(1):nm.end(1)]
        name, name_pos, i = raw_name.lower(), nm.start(1), nm.end()
        am = _CTE_AS.match(masked, i)
        if not am:
            cm = _CTE_OPEN.match(masked, i)       # WITH name (col, col) AS (...)
            if not cm:
                return names, pos, positions
            close = match_paren(masked, cm.end() - 1)
            if close < 0:
                return names, pos, positions
            i = close
            am = _CTE_AS.match(masked, i)
            if not am:
                return names, pos, positions
        i = am.end()
        om = _CTE_OPEN.match(masked, i)
        if not om:
            return names, pos, positions
        close = match_paren(masked, om.end() - 1)
        if close < 0:
            return names, pos, positions
        names.add(name)
        positions.setdefault(name, (raw_name, name_pos))
        i = close
        nxt = _CTE_COMMA.match(masked, i)
        if not nxt:
            return names, i, positions
        i = nxt.end()


def skip_ctes(masked, pos):
    """Offset just past a WITH block that starts at/after pos, else pos.

    INSERT INTO t (a, b, c) WITH base AS (SELECT x FROM s) SELECT x, 1, 2 ...
    Before v10 the arity check read the SELECT inside the CTE instead of the
    outer one and reported a bogus ORA-00947 that blocked the build.
    """
    return parse_with(masked, pos)[1]


# --------------------------------------------------------------------------- #
# DDL: the real column structure of the target tables
# --------------------------------------------------------------------------- #
def _norm_key(k):
    return re.sub(r"[^a-z_]", "", (k or "").strip().lower())


def _rows_from_json(text):
    data = json.loads(text)
    if isinstance(data, dict):
        for key in ("rows", "items", "data", "results"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise ValueError("JSON DDL must be a list of row objects")
    return [{_norm_key(k): v for k, v in row.items()} for row in data]


def _rows_from_delimited(text):
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    rdr = csv.DictReader(io.StringIO(text), dialect=dialect)
    return [{_norm_key(k): v for k, v in row.items() if k} for row in rdr]


def load_ddl(path):
    """table name (lower, no schema) -> list of column dicts.

    Each column dict: name, nullable (bool), has_default (bool), data_type.
    """
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        text = fh.read()
    stripped = text.lstrip()
    rows = (_rows_from_json(text) if stripped[:1] in "[{"
            else _rows_from_delimited(text))
    if not rows:
        raise ValueError("no rows found in %s" % path)

    keys = set()
    for row in rows:
        keys.update(row)
    LAST_DDL_META.clear()
    LAST_DDL_META.update({
        "has_nullable": bool(keys & {"nullable"}),
        "has_default": bool(keys & {"data_default", "default"}),
        "has_data_type": bool(keys & {"data_type"}),
    })

    tables = {}
    for row in rows:
        tname = (row.get("table_name") or row.get("table") or "").strip()
        cname = (row.get("column_name") or row.get("column") or "").strip()
        if not tname or not cname:
            continue
        nullable = str(row.get("nullable", "Y")).strip().upper()
        default = row.get("data_default", row.get("default", ""))
        default = "" if default is None else str(default).strip()
        has_default = default not in ("", "null", "NULL", "(null)")
        tables.setdefault(tname.lower(), []).append({
            "name": cname.lower(),
            "raw": cname,
            "nullable": nullable not in ("N", "NO", "0", "FALSE"),
            "has_default": has_default,
            "data_type": (row.get("data_type") or "").strip(),
        })
    if not tables:
        raise ValueError(
            "%s has no TABLE_NAME/COLUMN_NAME columns -- see knowledge/lessons-learned.md case 18 "
            "for the query that produces the expected shape" % path)
    return tables


def load_partitions(path):
    """table name (lower, no schema) -> True/False.

    True  = Q14 confirmed sinkOption.partitions was EMPTY for this table
            (a blind TRUNCATE TABLE is the correct translation of Overwrite).
    False = Q14 confirmed sinkOption.partitions was NON-empty (TRUNCATE
            TABLE must never be used; only the named partitions may be
            cleared).

    Source: CSV/TSV/JSON with at least TABLE_NAME and PARTITIONS_EMPTY (Y/N),
    one row per table whose sinkOption.mode was Overwrite in the DAG
    (knowledge/reference/blendata-json-schema.md, knowledge/reference/delivery-checklist.md case 26, checklist item 41, rule D-R7).
    """
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        text = fh.read()
    stripped = text.lstrip()
    rows = (_rows_from_json(text) if stripped[:1] in "[{"
            else _rows_from_delimited(text))
    if not rows:
        raise ValueError("no rows found in %s" % path)
    out = {}
    for row in rows:
        tname = (row.get("table_name") or row.get("table") or "").strip()
        if not tname:
            continue
        flag = str(row.get("partitions_empty")
                    or row.get("empty") or "").strip().upper()
        out[_bare(tname)] = flag in ("Y", "YES", "TRUE", "1")
    if not out:
        raise ValueError(
            "%s has no TABLE_NAME/PARTITIONS_EMPTY columns" % path)
    return out


def _bare(table):
    return table.split(".")[-1].lower()


def check_against_ddl(table, cols, ddl, label, ln, findings):
    """Compare one INSERT's column list against the real table structure."""
    known = ddl.get(_bare(table))
    if known is None:
        findings.append(("WARN", label, ln,
                         "no DDL for %s -- checklist items 32-34 not checked "
                         "for this table" % table))
        return
    have = {c["name"] for c in known}
    listed = [c.lower() for c in cols]

    dupes = sorted({c for c in listed if listed.count(c) > 1})
    if dupes:
        findings.append(("ERROR", label, ln,
                         "%s: column listed twice: %s"
                         % (table, ", ".join(dupes))))

    missing = [c for c in listed if c not in have]
    if missing:
        findings.append(("ERROR", label, ln,
                         "%s: %s -- no such column in the table. Oracle raises "
                         "ORA-00904. Names must come from the DDL (Q3), not "
                         "from the SELECT aliases."
                         % (table, ", ".join(missing))))

    omitted = [c for c in known if c["name"] not in set(listed)]
    required = [c["raw"] for c in omitted
                if not c["nullable"] and not c["has_default"]]
    if required:
        findings.append(("ERROR", label, ln,
                         "%s: NOT NULL column(s) left out of the list with no "
                         "DEFAULT: %s -- Oracle raises ORA-01400 at run time"
                         % (table, ", ".join(required))))

    optional = [c["raw"] for c in omitted
                if c["nullable"] or c["has_default"]]
    if optional:
        findings.append(("WARN", label, ln,
                         "%s: %d column(s) not in the list will take NULL or "
                         "their DEFAULT: %s -- confirm this is intended"
                         % (table, len(optional), ", ".join(optional))))


def check_column_names(table, raw_names, ddl, label, ln, findings):
    """Every listed name must work as a plain unquoted Oracle identifier.

    The v9 guess mode copies source field names straight across, which is how a
    Spark column called date, level or comment ends up in a column list,
    and how a name longer than 30 bytes reaches an 11g database.
    """
    known = set()
    if ddl is not None:
        known = {c["name"] for c in ddl.get(_bare(table), [])}
    for raw in raw_names:
        name = raw.strip()
        if not name:
            continue
        bare = name.split(".")[-1].strip()
        if bare.startswith('"') and bare.endswith('"') and len(bare) > 1:
            findings.append((
                "WARN", label, ln,
                "%s: %s is written as a quoted identifier, which makes it "
                "case-sensitive -- it only matches a column that was CREATEd "
                "quoted with exactly this spelling. Never quote a guessed name."
                % (table, bare)))
            continue
        low = bare.lower()
        if low in ORACLE_RESERVED:
            if low in known:
                level = "WARN"
                tail = (" -- the DDL says this column does exist, so it was "
                        'created as a quoted identifier and must be written "%s" '
                        "here, spelling and case included" % bare.upper())
            else:
                level = "ERROR"
                tail = (". Oracle raises ORA-00904/ORA-00936. If this name came "
                        "from the guess mode at Q3, the guess is wrong.")
            findings.append((
                level, label, ln,
                "%s: %s is an Oracle reserved word and cannot be used as an "
                "unquoted column name%s" % (table, bare, tail)))
        nbytes = len(bare.encode("utf-8"))
        if nbytes > 128:
            findings.append(("ERROR", label, ln,
                             "%s: column name %s is %d bytes -- over Oracle's "
                             "128-byte identifier limit (ORA-00972)"
                             % (table, bare, nbytes)))
        elif nbytes > 30:
            findings.append(("WARN", label, ln,
                             "%s: column name %s is %d bytes -- fine on 12.2+ "
                             "but ORA-00972 on 11g and older. Confirm the "
                             "target database version."
                             % (table, bare, nbytes)))


# --------------------------------------------------------------------------- #
# the three checks
# --------------------------------------------------------------------------- #
def check_inserts(sql, masked, label, findings, ddl=None):
    """D-R1: column list present, and its arity matches the SELECT list."""
    for m in re.finditer(r"\binsert\s+into\s+", masked, re.IGNORECASE):
        after = m.end()
        im = _IDENT.match(masked, after)
        if not im:
            continue
        table = sql[im.start():im.end()]
        ln = line_of(sql, m.start())
        k = im.end()
        while k < len(masked) and masked[k] in " \t\r\n":
            k += 1
        if k >= len(masked) or masked[k] != "(":
            extra = ""
            if ddl is not None:
                known = ddl.get(_bare(table))
                span0 = select_list_span(masked, skip_ctes(masked, im.end()))
                if known is not None and span0:
                    got = len(split_top(masked, span0[0], span0[1]))
                    if got != len(known):
                        extra = (" The table has %d columns and the SELECT "
                                 "returns %d, so this would raise %s."
                                 % (len(known), got,
                                    "ORA-00947" if len(known) > got
                                    else "ORA-00913"))
            findings.append(
                ("ERROR", label, ln,
                 "INSERT INTO %s has no column list -- positional insert. "
                 "Add the explicit column list (rule D-R1).%s" % (table, extra)))
            continue
        close = match_paren(masked, k)
        if close < 0:
            findings.append(("ERROR", label, ln,
                             "INSERT INTO %s: unbalanced column list" % table))
            continue
        cols = split_top(masked, k + 1, close - 1)
        check_column_names(table, [sql[a:b] for a, b in cols],
                           ddl, label, ln, findings)
        vm = re.compile(r"\s*\bvalues\b\s*\(", re.IGNORECASE).match(masked, close)
        if vm:
            vclose = match_paren(masked, vm.end() - 1)
            if vclose > 0:
                vals = split_top(masked, vm.end(), vclose - 1)
                _report_arity(table, len(cols), len(vals), "VALUES",
                              label, ln, findings)
                if ddl is not None:
                    names = [masked[a:b].strip().split(".")[-1] for a, b in cols]
                    check_against_ddl(table, names, ddl, label, ln, findings)
                continue
        span = select_list_span(masked, skip_ctes(masked, close))
        if not span:
            findings.append(("WARN", label, ln,
                             "INSERT INTO %s: no SELECT and no VALUES found "
                             "after the column list -- arity not checked" % table))
            continue
        exprs = split_top(masked, span[0], span[1])
        _report_arity(table, len(cols), len(exprs), "SELECT", label, ln, findings)
        if ddl is not None:
            names = [masked[a:b].strip().split(".")[-1] for a, b in cols]
            check_against_ddl(table, names, ddl, label, ln, findings)


def check_merges(sql, masked, label, findings, ddl=None):
    """D-R1 for MERGE, which check_sql missed entirely before v10.

    House style writes every upsert as MERGE, so WHEN NOT MATCHED THEN INSERT
    VALUES (...) without a column list is the same positional-insert fault as
    knowledge/lessons-learned.md case 18, in the shape this project uses most.
    """
    for m in _MERGE_INTO.finditer(masked):
        im = _IDENT.match(masked, m.end())
        if not im:
            continue
        table = sql[im.start():im.end()]
        end = len(masked)
        nxt = _MERGE_INTO.search(masked, im.end())
        if nxt:
            end = nxt.start()

        ins = _MERGE_INSERT.search(masked, im.end(), end)
        if ins:
            ln = line_of(sql, ins.start())
            k = ins.end()
            while k < len(masked) and masked[k] in " \t\r\n":
                k += 1
            if k >= len(masked) or masked[k] != "(":
                findings.append((
                    "ERROR", label, ln,
                    "MERGE INTO %s: the WHEN NOT MATCHED INSERT has no column "
                    "list -- positional insert, same fault as a bare INSERT "
                    "INTO ... VALUES (rule D-R1)." % table))
            else:
                close = match_paren(masked, k)
                if close < 0:
                    findings.append(("ERROR", label, ln,
                                     "MERGE INTO %s: unbalanced column list"
                                     % table))
                else:
                    cols = split_top(masked, k + 1, close - 1)
                    check_column_names(table, [sql[a:b] for a, b in cols],
                                       ddl, label, ln, findings)
                    vm = re.compile(r"\s*\bvalues\b\s*\(",
                                    re.IGNORECASE).match(masked, close)
                    if not vm:
                        findings.append((
                            "WARN", label, ln,
                            "MERGE INTO %s: no VALUES after the INSERT column "
                            "list -- arity not checked" % table))
                    else:
                        vclose = match_paren(masked, vm.end() - 1)
                        if vclose < 0:
                            findings.append(("ERROR", label, ln,
                                             "MERGE INTO %s: unbalanced VALUES"
                                             % table))
                        else:
                            vals = split_top(masked, vm.end(), vclose - 1)
                            _report_arity(table, len(cols), len(vals), "VALUES",
                                          label, ln, findings, verb="MERGE INTO")
                            if ddl is not None:
                                names = [masked[a:b].strip().split(".")[-1]
                                         for a, b in cols]
                                check_against_ddl(table, names, ddl, label, ln,
                                                  findings)

        upd = _MERGE_UPDATE.search(masked, im.end(), end)
        if upd and ddl is not None and _bare(table) in ddl:
            ln = line_of(sql, upd.start())
            stop = re.compile(r"\bwhen\b|\bwhere\b|\bdelete\b",
                              re.IGNORECASE).search(masked, upd.end(), end)
            tail = stop.start() if stop else end
            have = {c["name"] for c in ddl[_bare(table)]}
            bad = []
            for a, b in split_top(masked, upd.end(), tail):
                eq = masked.find("=", a, b)
                if eq < 0:
                    continue
                target = sql[a:eq].strip().split(".")[-1].strip().lower()
                if target and target not in have:
                    bad.append(target)
            if bad:
                findings.append((
                    "ERROR", label, ln,
                    "MERGE INTO %s: UPDATE SET assigns to %s -- no such column "
                    "in the table, Oracle raises ORA-00904"
                    % (table, ", ".join(sorted(set(bad))))))


def check_insert_all(sql, masked, label, findings, ddl=None, schema=None):
    """D-R1 for multi-table INSERT ALL / INSERT FIRST.

    insert\\s+into never matched these, so every branch used to ship
    unchecked, column list or not.
    """
    for m in _INSERT_ALL.finditer(masked):
        end = len(masked)
        sel = re.compile(r"\bselect\b", re.IGNORECASE).search(masked, m.end())
        if sel:
            end = sel.start()
        for bm in _ALL_BRANCH.finditer(masked, m.end(), end):
            im = _IDENT.match(masked, bm.end())
            if not im:
                continue
            table = sql[im.start():im.end()]
            ln = line_of(sql, bm.start())
            if "." not in table:
                findings.append((
                    "ERROR", label, ln,
                    "table %s is not schema-qualified -- ODI does not add the "
                    "schema to raw Procedure SQL (rule D-R2)" % table))
            k = im.end()
            while k < len(masked) and masked[k] in " \t\r\n":
                k += 1
            if k >= len(masked) or masked[k] != "(":
                findings.append((
                    "ERROR", label, ln,
                    "INSERT ALL: the branch INTO %s has no column list -- "
                    "positional insert (rule D-R1)." % table))
                continue
            close = match_paren(masked, k)
            if close < 0:
                findings.append(("ERROR", label, ln,
                                 "INSERT ALL: branch INTO %s has an unbalanced "
                                 "column list" % table))
                continue
            cols = split_top(masked, k + 1, close - 1)
            check_column_names(table, [sql[a:b] for a, b in cols],
                               ddl, label, ln, findings)
            vm = re.compile(r"\s*\bvalues\b\s*\(",
                            re.IGNORECASE).match(masked, close)
            if not vm:
                findings.append(("WARN", label, ln,
                                 "INSERT ALL: branch INTO %s has no VALUES -- "
                                 "arity not checked" % table))
                continue
            vclose = match_paren(masked, vm.end() - 1)
            if vclose < 0:
                continue
            vals = split_top(masked, vm.end(), vclose - 1)
            _report_arity(table, len(cols), len(vals), "VALUES", label, ln,
                          findings, verb="INSERT ALL INTO")
            if ddl is not None:
                names = [masked[a:b].strip().split(".")[-1] for a, b in cols]
                check_against_ddl(table, names, ddl, label, ln, findings)


def check_statement_shape(sql, masked, label, findings):
    """D-R3: one statement per file, no trailing ';', never empty."""
    if not masked.strip():
        findings.append(("ERROR", label, 1,
                         "file is empty -- an empty command line imports "
                         "cleanly and then does nothing at run time "
                         "(knowledge/lessons-learned.md case 29)"))
        return
    if _PLSQL_START.match(masked):
        return                      # a PL/SQL block owns its own semicolons
    body = masked.rstrip()
    trailing = body.endswith(";")
    if trailing:
        findings.append((
            "ERROR", label, line_of(sql, len(body) - 1),
            "statement ends with ';' -- ODI hands the command line straight to "
            "JDBC, which has no statement terminator, and Oracle raises "
            "ORA-00911: invalid character (rule D-R3)"))
        body = body[:-1]
    for i, ch in enumerate(body):
        if ch == ";":
            findings.append((
                "ERROR", label, line_of(sql, i),
                "';' in the middle of the file -- build_from_spec expects one "
                "command line per .sql file (rule D-R3). Split the file."))
            break


def _report_arity(table, ncols, nvals, source, label, ln, findings,
                  verb="INSERT INTO"):
    if ncols != nvals:
        findings.append((
            "ERROR", label, ln,
            "%s %s: %d columns listed but %s supplies %d -- Oracle will raise %s"
            % (verb, table, ncols, source, nvals,
               "ORA-00947" if ncols > nvals else "ORA-00913")))
    else:
        findings.append(("OK", label, ln,
                         "%s %s: %d columns = %d %s expressions"
                         % (verb, table, ncols, nvals, source)))


def collect_ctes(masked):
    """Every CTE name in the statement, at any nesting level.

    v10 routes this through the same parser as skip_ctes, so the
    WITH name (col, col) AS (...) form is recognised too -- the old regex
    missed it and then reported the CTE as an unqualified table.
    """
    names = set()
    for m in re.finditer(r"\bwith\b", masked, re.IGNORECASE):
        names |= parse_with(masked, m.start())[0]
    return names


def collect_cte_positions(masked):
    """name (lower) -> (raw spelling, offset) for every top-level CTE name.

    Companion to collect_ctes(), kept separate so the existing callers of
    collect_ctes() (check_qualified's "allowed" set) are untouched.
    """
    positions = {}
    for m in re.finditer(r"\bwith\b", masked, re.IGNORECASE):
        _, _, pos = parse_with(masked, m.start())
        for name, val in pos.items():
            positions.setdefault(name, val)
    return positions


def check_qualified(sql, masked, label, findings, schema=None, allow=()):
    """D-R2: every table reference carries a schema prefix."""
    ctes = collect_ctes(masked)
    allowed = BUILTIN_UNQUALIFIED | ctes | {a.strip().lower() for a in allow if a.strip()}
    seen = set()
    for m in _TABLE_INTRO.finditer(masked):
        k = m.end()
        if k < len(masked) and masked[k] == "(":
            k = paren_table_start(masked, k)           # inline view / subquery -> skip; parenthesised join -> check (K1)
            if k is None:
                continue
        im = _IDENT.match(masked, k)
        if not im:
            continue
        name = sql[im.start():im.end()]
        low = name.lower()
        if low in allowed or low in _NOT_A_TABLE:
            continue
        ln = line_of(sql, im.start())
        if "." not in name:
            key = (label, low)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                ("ERROR", label, ln,
                 "table %s is not schema-qualified -- ODI does not add the "
                 "schema to raw Procedure SQL (rule D-R2)" % name))
        elif schema and not low.startswith(schema.lower() + "."):
            key = (label, low)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                ("WARN", label, ln,
                 "table %s uses a schema other than %s -- confirm at Q4"
                 % (name, schema)))


def _alias_after(masked, pos):
    """(alias_text, alias_pos) right after pos, or None if there is none.

    Honors an explicit AS. Without AS, a bare identifier counts as an alias
    only when it is not itself a clause keyword (WHERE, GROUP BY, JOIN, a
    second comma-joined table, ...) -- those are not self-chosen names and
    must never be checked against ORACLE_RESERVED.
    """
    m = _AS_ALIAS.match(masked, pos)
    if m:
        return masked[m.start(1):m.end(1)], m.start(1)
    m = _BARE_ALIAS.match(masked, pos)
    if not m:
        return None
    word = masked[m.start(1):m.end(1)]
    if word.lower() in _ALIAS_STOPWORDS:
        return None
    return word, m.start(1)


def check_aliases(sql, masked, label, findings):
    """D-R4: self-chosen table/subquery/CTE aliases must not be reserved words.

    A GUESSED COLUMN name that collides with a reserved word is already
    caught by check_column_names, and that check can be cleared by real DDL.
    This is the different, knowledge/lessons-learned.md case 34 fault: an alias the author
    typed themselves never comes from a DDL export, so it can collide with a
    reserved word (RAW is the one that actually hit this project) even when
    every column name and the DDL are completely correct. Needs no DDL.
    """
    reported = set()

    def flag(word, pos):
        low = word.lower()
        if low not in ORACLE_RESERVED:
            return
        key = (label, low)
        if key in reported:
            return
        reported.add(key)
        findings.append((
            "ERROR", label, line_of(sql, pos),
            "alias \"%s\" is an Oracle reserved word -- Oracle raises "
            "ORA-00936/ORA-00903 at parse time even with a correct column "
            "list and correct DDL, because this is a self-chosen table/"
            "subquery/CTE alias, not a guessed column name (that is rule "
            "D-R4, not the \"names\" check). Rename it, e.g. \"%s\" -> "
            "\"landing_%s\" (knowledge/lessons-learned.md case 34)."
            % (word, low, low)))

    for m in _ALIAS_INTRO.finditer(masked):
        k = m.end()
        if k < len(masked) and masked[k] == "(":
            close = match_paren(masked, k)
            if close < 0:
                continue
            got = _alias_after(masked, close)          # subquery alias
        else:
            im = _IDENT.match(masked, k)
            if not im:
                continue
            if masked[im.start():im.end()].lower() == "set":
                continue          # MERGE's "WHEN MATCHED THEN UPDATE SET ..."
            got = _alias_after(masked, im.end())        # table alias
        if got:
            flag(*got)

    for name, (raw, pos) in collect_cte_positions(masked).items():
        flag(raw, pos)


def split_union_branches(masked):
    """Top-level UNION / UNION ALL branches of one masked SQL text.

    Returns a list of (start, end) spans covering the whole text; a single
    one-item list when there is no top-level UNION. Only splits at paren
    depth 0, so a UNION inside a subquery is left alone.
    """
    depth, i, n, cuts = 0, 0, len(masked), []
    while i < n:
        ch = masked[i]
        if ch == "(":
            depth += 1
            i += 1
        elif ch == ")":
            depth -= 1
            i += 1
        elif depth == 0:
            m = _UNION_SPLIT.match(masked, i)
            if m:
                cuts.append((i, m.end()))
                i = m.end()
            else:
                i += 1
        else:
            i += 1
    if not cuts:
        return [(0, n)]
    spans, last = [], 0
    for start, end in cuts:
        spans.append((last, start))
        last = end
    spans.append((last, n))
    return spans


def branch_source_table(branch_masked, from_pos):
    """The single table a UNION branch selects from, or None.

    D-R5 only trusts the plain FROM schema.table [alias] shape starting at
    from_pos; a JOIN, a comma-joined second table, or a FROM-subquery makes
    the source ambiguous, so this returns None and the caller skips the
    branch with a WARN rather than guessing which table a mismatch belongs to.
    """
    m = _SIMPLE_FROM.match(branch_masked, from_pos)
    if not m:
        return None
    stop = _UNION_BRANCH_STOP.search(branch_masked, m.end())
    tail_end = stop.start() if stop else len(branch_masked)
    tail = branch_masked[m.end():tail_end]
    if "," in tail or _JOIN_KW.search(tail):
        return None
    return m.group(1)


def _base_type(data_type):
    """DATA_TYPE reduced to its bare type word: 'VARCHAR2(4000)' -> 'varchar2'."""
    if not data_type:
        return None
    word = data_type.strip().split("(")[0].strip().lower()
    return word or None


def _branch_expr_label(text):
    """The bare column name of a UNION branch SELECT-list item, or None.

    Only a plain [alias.]column[ [AS] alias] reference resolves to a DDL
    column; a function call, a literal, or a CASE expression can't be looked
    up, so that position is left out of the comparison rather than guessed.
    """
    m = _SIMPLE_COL.match(text.strip())
    if not m:
        return None
    return m.group(1).split(".")[-1]


def _paren_scopes(masked):
    """(start, end) of the whole text, plus every parenthesized region's
    inner span, innermost first is not required -- order does not matter.

    A UNION combining a target table with a row from a derived ("dup") table
    is nested inside that derived table's own parens, not at the top of the
    statement (knowledge/lessons-learned.md case 35 happened exactly this way). Each scope is
    searched independently for a top-level-within-it UNION split, so a UNION
    at any nesting depth is found the same way a top-level one would be.
    """
    scopes = [(0, len(masked))]
    stack = []
    for i, ch in enumerate(masked):
        if ch == "(":
            stack.append(i)
        elif ch == ")" and stack:
            scopes.append((stack.pop() + 1, i))
    return scopes


def check_unions(sql, masked, label, findings, ddl=None):
    """D-R5: same-position columns across UNION/UNION ALL branches must agree
    on datatype -- positional, because that is how Oracle actually compares a
    set operation's branches, not by the column names the author reused.
    Needs --ddl with a DATA_TYPE column; silent without it, same as the other
    DDL-only checks (see checklist items 32-34).
    """
    if not ddl:
        return
    seen = set()
    for s, e in _paren_scopes(masked):
        rel = split_union_branches(masked[s:e])
        if len(rel) < 2:
            continue
        spans = tuple((s + a, s + b) for a, b in rel)
        if spans in seen:
            continue
        seen.add(spans)
        _check_union_group(sql, masked, label, findings, ddl, list(spans))


def _check_union_group(sql, masked, label, findings, ddl, spans):
    ln = line_of(sql, spans[0][0])

    branches = []
    for bstart, bend in spans:
        seg = masked[bstart:bend]
        span = select_list_span(seg, skip_ctes(seg, 0))
        if not span:
            branches.append(None)
            continue
        table = branch_source_table(seg, span[1])
        cols = [_branch_expr_label(seg[a:b]) for a, b in split_top(seg, span[0], span[1])]
        branches.append({"table": table, "cols": cols})

    if any(b is None for b in branches):
        findings.append(("WARN", label, ln,
                         "UNION: could not parse every branch's SELECT list -- "
                         "datatype check skipped for this statement (rule D-R5)"))
        return
    if any(b["table"] is None for b in branches):
        findings.append((
            "WARN", label, ln,
            "UNION: at least one branch is not a plain single-table FROM (a "
            "JOIN, a comma-joined table list, or a FROM-subquery) -- "
            "datatype check skipped, verify the datatypes manually "
            "(rule D-R5)"))
        return

    known = {}
    missing = []
    for b in branches:
        t = ddl.get(_bare(b["table"]))
        if t is None:
            missing.append(b["table"])
        known[b["table"]] = t
    if missing:
        findings.append((
            "WARN", label, ln,
            "UNION: no DDL for %s -- datatype check skipped for this "
            "statement (rule D-R5)" % ", ".join(sorted(set(missing)))))
        return

    ncols = min(len(b["cols"]) for b in branches)
    for pos in range(ncols):
        entries = []
        for b in branches:
            col = b["cols"][pos]
            dtype = None
            if col:
                for c in known[b["table"]]:
                    if c["name"] == col.lower():
                        dtype = c["data_type"]
                        break
            entries.append((b["table"], col, _base_type(dtype)))
        found = {e[2] for e in entries if e[2]}
        if len(found) > 1:
            detail = "; ".join(
                "%s.%s=%s" % (t, c or "?", dt or "unknown") for t, c, dt in entries)
            if found & _LOB_TYPES:
                findings.append((
                    "ERROR", label, ln,
                    "UNION position %d: %s -- mismatched datatypes across "
                    "branches, Oracle raises ORA-01790 (expression must have "
                    "same datatype as corresponding expression). Cast the LOB "
                    "side with TO_CHAR() before the UNION (rule D-R5, "
                    "knowledge/lessons-learned.md case 35)." % (pos + 1, detail)))
            else:
                findings.append((
                    "ERROR", label, ln,
                    "UNION position %d: %s -- mismatched datatypes across "
                    "branches; Oracle may raise ORA-01790 or silently apply "
                    "an implicit conversion. Cast both sides to the same "
                    "explicit type before the UNION (rule D-R5)."
                    % (pos + 1, detail)))


def check_date_format_masks(sql, masked, label, findings, ddl=None):
    """D-R6: TO_DATE / TO_TIMESTAMP must always carry an explicit format mask,
    AND must never wrap a column DDL confirms is already DATE/TIMESTAMP.

    Part 1 (v1.4.0, needs no DDL, always checked): called with exactly one
    argument, both functions parse a string using the session's
    NLS_DATE_FORMAT / NLS_TIMESTAMP_FORMAT -- a setting that varies by
    agent/session, not a property of the SQL text. The same statement can
    raise ORA-01858 on one agent and silently parse the wrong date on
    another. Pure syntax check (argument count).

    Only TO_DATE/TO_TIMESTAMP are checked: a single-argument TO_CHAR/TO_NUMBER
    is extremely common and safe on a NUMBER, and telling that apart from a
    genuinely risky TO_CHAR(date_col) needs a real column type this script
    does not try to infer -- checklist item 43 still needs those two read by
    eye (see knowledge/lessons-learned.md and README.md).

    Part 2 (v1.5.0, needs --ddl, silently skipped without it): a mask being
    PRESENT is not proof it is correct. TEST_AI_GEN_13 shipped
    TO_DATE(effective_date, 'YYYY-MM-DD') against a column DDL later
    confirmed was already TIMESTAMP -- Part 1 never flags this, because an
    argument count of 2 looks exactly like a normal, correct call. When
    --ddl is given, the first argument of every TO_DATE/TO_TIMESTAMP call
    (mask or no mask) is matched by bare column name against every table in
    the DDL; a match whose DATA_TYPE already starts with DATE or TIMESTAMP is
    an ERROR regardless of whether a mask is present. The match is by column
    name only, not by join/alias resolution, so a name collision across
    unrelated tables can false-positive -- the finding names the matching
    table(s) so a false positive is easy to recognize and ignore.
    (checklist item 43, rule D-R6, knowledge/reference/spark-to-oracle-sql.md rule C12)
    """
    for m in _DATE_FUNCS.finditer(masked):
        fname = m.group(1).upper()
        open_pos = m.end() - 1
        close = match_paren(masked, open_pos)
        if close == -1:
            continue
        args = split_top(masked, open_pos + 1, close - 1)
        if not args:
            continue
        ln = line_of(sql, m.start())
        arg_text = sql[args[0][0]:args[0][1]].strip()

        if len(args) == 1:
            findings.append((
                "WARN", label, ln,
                "%s(%s) has no format mask -- parses using the agent's "
                "NLS_DATE_FORMAT/NLS_TIMESTAMP_FORMAT, which is not a "
                "property of this SQL text and can differ by agent/session: "
                "risk of ORA-01858 or a silently wrong date. Add an explicit "
                "format mask, e.g. %s(%s, 'YYYY-MM-DD') -- but only after "
                "confirming the real column type (see below): if it is "
                "already DATE/TIMESTAMP, do not wrap it at all (rule D-R6, "
                "checklist item 43)." % (fname, arg_text, fname, arg_text)))

        if ddl and _DATE_ARG_IDENT_RE.match(arg_text):
            bare_col = arg_text.split(".")[-1].lower()
            hits = []
            for tname, cols in ddl.items():
                for c in cols:
                    if c["name"] == bare_col:
                        base = _base_type(c["data_type"])
                        if base and base.startswith(_DATE_DDL_TYPES):
                            hits.append("%s.%s (%s)"
                                        % (tname, c["raw"], c["data_type"]))
            if hits:
                findings.append((
                    "ERROR", label, ln,
                    "%s(%s) wraps a column the provided DDL lists as already "
                    "DATE/TIMESTAMP: %s -- wrapping it in %s at all risks the "
                    "same implicit TIMESTAMP->VARCHAR2->TO_DATE round-trip "
                    "that raised ORA-01858 in TEST_AI_GEN_13; use the column "
                    "as-is instead (rule D-R6, checklist item 43, knowledge/reference/spark-to-oracle-sql.md "
                    "rule C12). Matched by column name only, not by "
                    "join/alias resolution -- verify %s really comes from "
                    "one of those tables in this statement before treating "
                    "this as a false positive."
                    % (fname, arg_text, "; ".join(hits), fname, arg_text)))


def _date_ddl_hits(ddl, bare_col):
    """table.COL (TYPE) for every DDL column named bare_col whose data type
    is DATE/TIMESTAMP. Name-only match -- same caveat as D-R6 part 2.
    """
    hits = []
    for tname, cols in ddl.items():
        for c in cols:
            if c["name"] == bare_col:
                base = _base_type(c["data_type"])
                if base and base.startswith(_DATE_DDL_TYPES):
                    hits.append("%s.%s (%s)" % (tname, c["raw"], c["data_type"]))
    return hits


def check_date_literal_comparisons(sql, masked, label, findings, ddl=None):
    """D-R6 part 3 (v1.6.0): a column already typed DATE/TIMESTAMP compared
    directly to a string literal -- no TO_DATE/TO_TIMESTAMP wrapper on either
    side -- falls back to the session's implicit NLS_DATE_FORMAT /
    NLS_TIMESTAMP_FORMAT exactly like the wrapped-but-wrong case D-R6 part 2
    catches, just with no function call to anchor on (knowledge/lessons-learned.md case 28,
    checklist item 43). Needs --ddl; silently skipped without it, same as
    the rest of D-R6's DDL-dependent halves.
    """
    if not ddl:
        return
    seen = set()
    for rx in (_DATE_CMP_LEFT_RE, _DATE_CMP_RIGHT_RE, _DATE_BETWEEN_RE):
        for m in rx.finditer(masked):
            ident = m.group(1)
            bare_col = ident.split(".")[-1].lower()
            hits = _date_ddl_hits(ddl, bare_col)
            if not hits:
                continue
            ln = line_of(sql, m.start())
            key = (ln, bare_col)
            if key in seen:
                continue
            seen.add(key)
            findings.append((
                "ERROR", label, ln,
                "'%s' is compared directly to a string literal with no "
                "TO_DATE()/TO_TIMESTAMP() wrapper, but --ddl lists it as "
                "already DATE/TIMESTAMP: %s -- relies on the session's "
                "implicit NLS_DATE_FORMAT the same way a wrapped-but-wrong "
                "TO_DATE() call does (knowledge/reference/delivery-checklist.md case 28, checklist item 43). "
                "Matched by column name only, not by join/alias resolution."
                % (ident, ", ".join(hits))))


def check_to_char_number_masks(sql, masked, label, findings):
    """checklist item 43, the TO_CHAR/TO_NUMBER half -- not part of D-R6
    itself (knowledge/reference/spark-to-oracle-sql.md keeps D-R6 to TO_DATE/TO_TIMESTAMP only) because
    TO_CHAR/TO_NUMBER are used for far more than dates: a single-argument
    call still falls back to session NLS settings, but telling a genuine
    date-formatting risk apart from an ordinary, harmless numeric cast needs
    a real column type this check does not act on, so this stays a WARN,
    never an ERROR, with or without --ddl.
    """
    for m in _TO_CHAR_NUM_FUNCS.finditer(masked):
        fname = m.group(1).upper()
        open_pos = m.end() - 1
        close = match_paren(masked, open_pos)
        if close == -1:
            continue
        args = split_top(masked, open_pos + 1, close - 1)
        if not args:
            continue
        if len(args) == 1:
            ln = line_of(sql, m.start())
            arg_text = sql[args[0][0]:args[0][1]].strip()
            findings.append((
                "WARN", label, ln,
                "%s(%s) has no explicit format mask -- falls back to the "
                "session's NLS settings; confirm this is intentional or add "
                "an explicit mask (checklist item 43)." % (fname, arg_text)))


def check_lenient_date_parse(sql, masked, label, findings):
    """D-R8 (v1.7.0) / knowledge/lessons-learned.md case 37. Oracle's TO_TIMESTAMP/TO_DATE accept
    an input shorter than the format and fill the rest with zeros, even with
    DEFAULT NULL ON CONVERSION ERROR; Spark returns NULL. Spark-side NULL is
    what routes a row to the type-error branch, so the lenient Oracle result
    silently moves a bad row into the good set. A REGEXP_LIKE anywhere in the
    statement, or an FX mask, counts as a guard. WARN only: whether a given
    call needs a guard depends on the source data, which this check cannot see.
    """
    if _REGEXP_GUARD_RE.search(masked):
        return
    for m in _PARSE_FUNCS_RE.finditer(masked):
        open_pos = m.end() - 1
        close = match_paren(masked, open_pos)
        if close == -1:
            continue
        args = split_top(masked, open_pos + 1, close - 1)
        if len(args) < 2:
            continue
        mask_text = sql[args[1][0]:args[1][1]].strip()
        if not _NUMERIC_MASK_RE.fullmatch(mask_text):
            continue
        if mask_text.strip("'").upper().startswith("FX"):
            continue
        findings.append((
            "WARN", label, line_of(sql, m.start()),
            "%s(..., %s) parses text leniently: an input shorter than the "
            "format is zero-filled, not NULL, even with DEFAULT NULL ON "
            "CONVERSION ERROR (Spark returns NULL). Add a REGEXP_LIKE shape "
            "guard such as REGEXP_LIKE(x, '^[0-9]{N}$') or use an FX mask, "
            "unless the input is already a DATE/TIMESTAMP column "
            "(D-R8, knowledge/lessons-learned.md case 37)." % (m.group(1).upper(), mask_text)))


def check_truncate_against_partitions(sql, masked, label, findings,
                                      partitions=None):
    """D-R7 (v1.6.0) / checklist item 41 / knowledge/lessons-learned.md case 26 -- knowledge/lessons-learned.md's
    own highest-rated risk: a TRUNCATE TABLE standing in for an Overwrite
    task whose sinkOption.partitions was non-empty deletes every other
    partition's history permanently, with no Oracle error, and a row-count
    check at validation level 1 (knowledge/reference/validation-and-cutover.md E1) still looks correct afterwards
    because it only compares the rows just loaded. Unlike D-R5 and the rest
    of D-R6, this one is never silent: without a --partitions file built
    from the Q14 answers it still WARNs on every TRUNCATE TABLE to confirm
    by hand, because the cost of one extra line to read is far lower than
    the cost of a silent, irreversible delete.
    """
    for m in _TRUNCATE_TABLE_RE.finditer(masked):
        im = _IDENT.match(masked, m.end())
        if not im:
            continue
        name = sql[im.start():im.end()]
        ln = line_of(sql, m.start())
        if partitions is None:
            findings.append((
                "WARN", label, ln,
                "TRUNCATE TABLE %s -- no --partitions file given, so this "
                "cannot be checked against the Q14 answer for "
                "sinkOption.partitions. Confirm by hand that the partitions "
                "array was empty (checklist item 41, knowledge/lessons-learned.md case 26) "
                "before shipping." % name))
            continue
        bare = name.split(".")[-1].lower()
        if bare not in partitions:
            findings.append((
                "WARN", label, ln,
                "TRUNCATE TABLE %s -- not listed in the --partitions file, "
                "so this is unverified against the Q14 answer for "
                "sinkOption.partitions. Confirm by hand (checklist item 41, "
                "knowledge/lessons-learned.md case 26) before shipping." % name))
        elif partitions[bare] is False:
            findings.append((
                "ERROR", label, ln,
                "TRUNCATE TABLE %s -- the --partitions file records "
                "sinkOption.partitions as NON-empty for this table at Q14: "
                "the source job only overwrote specific partitions. "
                "TRUNCATE deletes every other partition's history silently "
                "and irreversibly, and a row-count check at validation "
                "level 1 (knowledge/reference/validation-and-cutover.md E1) will still look correct afterwards "
                "(checklist item 41, knowledge/lessons-learned.md case 26)." % name))
        else:
            findings.append((
                "OK", label, ln,
                "TRUNCATE TABLE %s -- --partitions file confirms "
                "sinkOption.partitions was empty at Q14 (checklist item 41)."
                % name))


def check_leftovers(sql, label, findings):
    """Build artefacts and internal notes that should not ship."""
    for i, line in enumerate(sql.split("\n"), 1):
        if re.match(r"\s*--\s*ord\s*=", line, re.IGNORECASE):
            findings.append(("WARN", label, i,
                             "build artefact left in the SQL: %s" % line.strip()))


def check_text(sql, label, schema=None, allow=(), ddl=None, partitions=None):
    findings = []
    masked = mask_func_from(mask(sql))
    check_inserts(sql, masked, label, findings, ddl)
    check_merges(sql, masked, label, findings, ddl)
    check_insert_all(sql, masked, label, findings, ddl, schema)
    check_qualified(sql, masked, label, findings, schema, allow)
    check_aliases(sql, masked, label, findings)
    check_unions(sql, masked, label, findings, ddl)
    check_date_format_masks(sql, masked, label, findings, ddl)
    check_date_literal_comparisons(sql, masked, label, findings, ddl)
    check_to_char_number_masks(sql, masked, label, findings)
    check_lenient_date_parse(sql, masked, label, findings)
    check_truncate_against_partitions(sql, masked, label, findings, partitions)
    check_statement_shape(sql, masked, label, findings)
    check_leftovers(sql, label, findings)
    return findings


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def gather(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _d, fs in os.walk(p):
                for f in sorted(fs):
                    if f.lower().endswith(".sql"):
                        files.append(os.path.join(root, f))
        elif os.path.isfile(p):
            files.append(p)
        else:
            print("no such file or folder: %s" % p, file=sys.stderr)
            return None
    return files


def main(argv):
    if "--selftest" in argv:
        return selftest()
    paths, schema, allow, ddl_path, partitions_path = [], None, [], None, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--schema":
            i += 1
            schema = argv[i] if i < len(argv) else None
        elif a == "--ddl":
            i += 1
            ddl_path = argv[i] if i < len(argv) else None
        elif a == "--partitions":
            i += 1
            partitions_path = argv[i] if i < len(argv) else None
        elif a == "--allow-unqualified":
            i += 1
            allow = (argv[i] if i < len(argv) else "").split(",")
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            paths.append(a)
        i += 1
    if not paths:
        print(__doc__)
        return 2
    files = gather(paths)
    if files is None:
        return 2
    if not files:
        print("no .sql files found")
        return 2

    ddl = None
    if ddl_path:
        try:
            ddl = load_ddl(ddl_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print("cannot read --ddl %s: %s" % (ddl_path, exc), file=sys.stderr)
            return 2
        print("DDL loaded: %d table(s) -- %s"
              % (len(ddl), ", ".join(sorted(ddl))))
        print("  checklist 32 (ORA-00904, names exist): ON")
        if LAST_DDL_META.get("has_nullable"):
            print("  checklist 33 (ORA-01400, NOT NULL covered): ON")
        else:
            print("  checklist 33 (ORA-01400, NOT NULL covered): OFF -- the DDL "
                  "file has no NULLABLE column, so every column is being "
                  "treated as nullable. Report this table as UNCHECKED, not as "
                  "passed. Re-export with NULLABLE and DATA_DEFAULT.")
        if not LAST_DDL_META.get("has_default"):
            print("  note: no DATA_DEFAULT column either -- a NOT NULL column "
                  "that does have a DEFAULT may be reported as a false "
                  "ORA-01400.")
        if LAST_DDL_META.get("has_data_type"):
            print("  checklist 51 (ORA-01790, UNION datatypes match): ON")
        else:
            print("  checklist 51 (ORA-01790, UNION datatypes match): OFF -- "
                  "the DDL file has no DATA_TYPE column, so UNION branches "
                  "cannot be compared. Re-export with DATA_TYPE to close this.")
        print("")
    else:
        print("no --ddl given: checking rules D-R1, D-R2, D-R3, D-R4 and the "
              "column name rules only. D-R4 (alias vs reserved word) needs no "
              "DDL and is always on. Checklist items 32-34 (names exist, NOT "
              "NULL columns covered) and 51 (UNION datatypes match, rule "
              "D-R5) stay UNCHECKED -- pass the DDL from Q3 to close them. "
              "D-R6 parts 2 and 3 (a DATE/TIMESTAMP column wrapped or "
              "compared with no conversion) also stay UNCHECKED without it.")
        print("")

    partitions = None
    if partitions_path:
        try:
            partitions = load_partitions(partitions_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print("cannot read --partitions %s: %s" % (partitions_path, exc),
                  file=sys.stderr)
            return 2
        print("partitions file loaded: %d table(s) -- %s"
              % (len(partitions), ", ".join(sorted(partitions))))
        print("  checklist item 41 (D-R7, TRUNCATE vs sinkOption.partitions): ON")
        print("")
    else:
        print("no --partitions given: every TRUNCATE TABLE still gets a WARN "
              "to confirm by hand -- checklist item 41 / D-R7 (knowledge/lessons-learned.md's "
              "own highest-rated risk, case 26) cannot be fully closed "
              "without it. Build the file from the Q14 answers (TABLE_NAME, "
              "PARTITIONS_EMPTY) and re-run with --partitions.")
        print("")

    errors = warns = oks = 0
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            sql = fh.read()
        label = os.path.relpath(f)
        for level, lab, ln, msg in check_text(sql, label, schema, allow, ddl,
                                              partitions):
            if level == "OK":
                oks += 1
                continue
            if level == "ERROR":
                errors += 1
            else:
                warns += 1
            print("[%s] %s:%d  %s" % (level, lab, ln, msg))

    print("")
    print("checked %d file(s): %d INSERT(s) OK, %d error(s), %d warning(s)"
          % (len(files), oks, errors, warns))
    if errors:
        print("")
        print("ERRORS BLOCK DELIVERY -- see knowledge/reference/spark-to-oracle-sql.md rules D-R1 / D-R2 and")
        print("knowledge/lessons-learned.md cases 18-19 before changing anything.")
    return 1 if errors else 0


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #
def _tmp_ddl(text, suffix=".csv"):
    import tempfile
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def selftest():
    def run(sql, **kw):
        return check_text(sql, "t.sql", **kw)

    def levels(fs):
        return [f[0] for f in fs]

    n = 0

    # 1. positional insert is an error
    f = run("INSERT INTO myschema.t SELECT a, b FROM myschema.s")
    assert "ERROR" in levels(f) and "no column list" in f[0][3], f
    n += 1

    # 2. matching arity passes
    f = run("INSERT INTO myschema.t (a, b) SELECT x, y FROM myschema.s")
    assert levels(f) == ["OK"], f
    n += 1

    # 3. too few expressions -> ORA-00947
    f = run("INSERT INTO myschema.t (a, b, c) SELECT x, y FROM myschema.s")
    assert any("ORA-00947" in x[3] for x in f), f
    n += 1

    # 4. too many expressions -> ORA-00913
    f = run("INSERT INTO myschema.t (a) SELECT x, y FROM myschema.s")
    assert any("ORA-00913" in x[3] for x in f), f
    n += 1

    # 5. commas inside functions and strings do not inflate the count
    f = run("INSERT INTO myschema.t (a, b) "
            "SELECT NVL(x, 0), TO_CHAR(d, 'YYYY,MM') FROM myschema.s")
    assert levels(f) == ["OK"], f
    n += 1

    # 6. scalar subquery in the select list counts as one expression
    f = run("INSERT INTO myschema.t (a, b) "
            "SELECT x, (SELECT MAX(v) FROM myschema.u) FROM myschema.s")
    assert levels(f) == ["OK"], f
    n += 1

    # 7. commas inside a comment are ignored
    f = run("INSERT INTO myschema.t (a, b)\nSELECT x,  -- note, with, commas\n"
            "       y\nFROM myschema.s")
    assert levels(f) == ["OK"], f
    n += 1

    # 8. unqualified table is an error
    f = run("INSERT INTO t (a) SELECT x FROM myschema.s")
    assert any("not schema-qualified" in x[3] for x in f), f
    n += 1

    # 9. DUAL needs no prefix
    f = run("INSERT INTO myschema.t (a) SELECT 'TRUE' FROM DUAL")
    assert levels(f) == ["OK"], f
    n += 1

    # 10. inline view is not a table name
    f = run("INSERT INTO myschema.t (a) SELECT x FROM (SELECT 1 AS x FROM DUAL)")
    assert levels(f) == ["OK"], f
    n += 1

    # 11. CTE name declared with WITH is not an unqualified table
    f = run("INSERT INTO myschema.t (a) WITH c AS (SELECT 1 AS x FROM DUAL) "
            "SELECT x FROM c")
    assert not any(x[0] == "ERROR" for x in f), f
    n += 1

    # 12. wrong schema is a warning, not an error
    f = run("INSERT INTO other.t (a) SELECT x FROM other.s", schema="myschema")
    assert any(x[0] == "WARN" and "schema other than" in x[3] for x in f), f
    assert not any(x[0] == "ERROR" for x in f), f
    n += 1

    # 13. --allow-unqualified suppresses the error for that name
    f = run("INSERT INTO myschema.t (a) SELECT x FROM scratch", allow=["scratch"])
    assert levels(f) == ["OK"], f
    n += 1

    # 14. leftover build artefact is reported
    f = run("-- ord=10\nINSERT INTO myschema.t (a) SELECT x FROM DUAL")
    assert any("build artefact" in x[3] for x in f), f
    n += 1

    # 15. TRUNCATE of an unqualified table is caught too
    f = run("TRUNCATE TABLE t")
    assert any("not schema-qualified" in x[3] for x in f), f
    n += 1

    # 16. a real multi-line shape with window functions and CASE
    sql = ("INSERT INTO myschema.tgt (partition_date, id, rnk)\n"
           "SELECT\n"
           "    CAST(TO_CHAR(d, 'YYYYMMDD') AS NUMBER) AS partition_date,\n"
           "    id,\n"
           "    CASE WHEN a IN (1, 2) THEN 1 ELSE\n"
           "         ROW_NUMBER() OVER (PARTITION BY a, b ORDER BY c) END AS rnk\n"
           "FROM myschema.src\n")
    f = run(sql)
    assert levels(f) == ["OK"], f
    n += 1

    # 17. FROM-less SELECT still counts
    f = run("INSERT INTO myschema.t (a, b) SELECT 1, 2")
    assert levels(f) == ["OK"], f
    n += 1

    # ---- DDL-aware checks ----------------------------------------------- #
    csv_text = (
        "TABLE_NAME,COLUMN_ID,COLUMN_NAME,DATA_TYPE,NULLABLE,DATA_DEFAULT\n"
        "TGT,1,A,NUMBER,N,\n"
        "TGT,2,B,VARCHAR2,Y,\n"
        "TGT,3,C,VARCHAR2,N,'x'\n"
        "TGT,4,D,DATE,N,\n"
    )
    ddl_path = _tmp_ddl(csv_text)
    ddl = load_ddl(ddl_path)
    os.remove(ddl_path)

    # 18. DDL parsed the way we expect
    assert set(ddl) == {"tgt"} and len(ddl["tgt"]) == 4, ddl
    assert ddl["tgt"][0]["nullable"] is False, ddl
    assert ddl["tgt"][2]["has_default"] is True, ddl
    n += 1

    # 19. listing every column leaves nothing to report
    f = run("INSERT INTO myschema.tgt (a, b, c, d) SELECT 1, 2, 3, 4 FROM DUAL",
            ddl=ddl)
    assert levels(f) == ["OK"], f
    n += 1

    # 20. a name that is not a real column -> ORA-00904
    f = run("INSERT INTO myschema.tgt (a, zz, d) SELECT 1, 2, 3 FROM DUAL", ddl=ddl)
    assert any("ORA-00904" in x[3] and "zz" in x[3] for x in f), f
    n += 1

    # 21. a NOT NULL column with no DEFAULT left out -> ORA-01400
    f = run("INSERT INTO myschema.tgt (a, b) SELECT 1, 2 FROM DUAL", ddl=ddl)
    assert any("ORA-01400" in x[3] and "D" in x[3] for x in f), f
    n += 1

    # 22. a NOT NULL column WITH a DEFAULT left out is fine
    f = run("INSERT INTO myschema.tgt (a, d) SELECT 1, 2 FROM DUAL", ddl=ddl)
    assert not any(x[0] == "ERROR" for x in f), f
    n += 1

    # 23. omitted nullable columns are reported as a warning, not an error
    f = run("INSERT INTO myschema.tgt (a, c, d) SELECT 1, 2, 3 FROM DUAL", ddl=ddl)
    assert any(x[0] == "WARN" and "take NULL" in x[3] for x in f), f
    assert not any(x[0] == "ERROR" for x in f), f
    n += 1

    # 24. a duplicate name in the list is caught
    f = run("INSERT INTO myschema.tgt (a, a, d) SELECT 1, 2, 3 FROM DUAL", ddl=ddl)
    assert any("listed twice" in x[3] for x in f), f
    n += 1

    # 25. a table with no DDL is reported as unchecked, never as passed
    f = run("INSERT INTO myschema.other (a) SELECT 1 FROM DUAL", ddl=ddl)
    assert any(x[0] == "WARN" and "no DDL" in x[3] for x in f), f
    n += 1

    # 26. with DDL, a positional insert also predicts the exact ORA code
    f = run("INSERT INTO myschema.tgt SELECT 1, 2 FROM DUAL", ddl=ddl)
    assert any("no column list" in x[3] and "ORA-00947" in x[3] for x in f), f
    n += 1

    # 27. JSON DDL is accepted too
    jpath = _tmp_ddl('[{"TABLE_NAME":"TGT","COLUMN_NAME":"A","NULLABLE":"N"}]',
                     ".json")
    j = load_ddl(jpath)
    os.remove(jpath)
    assert j["tgt"][0]["name"] == "a" and j["tgt"][0]["nullable"] is False, j
    n += 1

    # 28. a schema prefix on a listed column name does not break matching
    f = run("INSERT INTO myschema.tgt (tgt.a, b, d) SELECT 1, 2, 3 FROM DUAL",
            ddl=ddl)
    assert not any(x[0] == "ERROR" for x in f), f
    n += 1

    # ---- v10: the three false positives that used to block valid SQL ----- #

    # 29. EXTRACT(... FROM col) is an expression, not a table reference
    f = run("INSERT INTO myschema.t (a) SELECT EXTRACT(YEAR FROM d) "
            "FROM myschema.s")
    assert levels(f) == ["OK"], f
    n += 1

    # 30. TRIM(... FROM col) likewise, including the bare-column form
    f = run("INSERT INTO myschema.t (a, b) SELECT TRIM(LEADING '0' FROM code), "
            "TRIM(TRAILING ' ' FROM name) FROM myschema.s")
    assert levels(f) == ["OK"], f
    n += 1

    # 31. a CTE between the column list and the outer SELECT
    f = run("INSERT INTO myschema.t (a, b, c)\n"
            "WITH base AS (SELECT x FROM myschema.s)\n"
            "SELECT x, 1, 2 FROM base")
    assert levels(f) == ["OK"], f
    n += 1

    # 32. several CTEs, and one with an explicit column list
    f = run("INSERT INTO myschema.t (a)\n"
            "WITH b1 (c1, c2) AS (SELECT x, y FROM myschema.s),\n"
            "     b2 AS (SELECT c1 FROM b1)\n"
            "SELECT c1 FROM b2")
    assert levels(f) == ["OK"], f
    n += 1

    # 33. a CTE with a genuinely wrong outer arity is still caught
    f = run("INSERT INTO myschema.t (a, b)\n"
            "WITH base AS (SELECT x, y, z FROM myschema.s)\n"
            "SELECT x FROM base")
    assert any("ORA-00947" in x[3] for x in f), f
    n += 1

    # 34. MERGE ... WHEN MATCHED THEN UPDATE SET is not a table called SET
    merge_ok = ("MERGE INTO myschema.tgt t\n"
                "USING (SELECT id, v1 FROM myschema.s) s ON (t.id = s.id)\n"
                "WHEN MATCHED THEN UPDATE SET t.v1 = s.v1\n"
                "WHEN NOT MATCHED THEN INSERT (id, v1) VALUES (s.id, s.v1)")
    f = run(merge_ok)
    assert not any(x[0] == "ERROR" for x in f), f
    n += 1

    # ---- v10: the faults that used to ship unchecked --------------------- #

    # 35. MERGE with a positional INSERT branch -- knowledge/lessons-learned.md case 22
    f = run("MERGE INTO myschema.tgt t USING myschema.s s ON (t.id = s.id) "
            "WHEN NOT MATCHED THEN INSERT VALUES (s.id, s.v1)")
    assert any("WHEN NOT MATCHED INSERT has no column list" in x[3]
               for x in f), f
    n += 1

    # 36. MERGE INSERT arity mismatch is reported like any other
    f = run("MERGE INTO myschema.tgt t USING myschema.s s ON (t.id = s.id) "
            "WHEN NOT MATCHED THEN INSERT (a, b, c) VALUES (1, 2)")
    assert any("ORA-00947" in x[3] for x in f), f
    n += 1

    # 37. MERGE UPDATE SET against a column the table does not have
    f = run("MERGE INTO myschema.tgt t USING myschema.s s ON (t.a = s.a) "
            "WHEN MATCHED THEN UPDATE SET t.zz = s.v WHERE 1 = 1", ddl=ddl)
    assert any("ORA-00904" in x[3] and "zz" in x[3] for x in f), f
    n += 1

    # 38. a MERGE UPDATE SET on real columns stays quiet
    f = run("MERGE INTO myschema.tgt t USING myschema.s s ON (t.a = s.a) "
            "WHEN MATCHED THEN UPDATE SET t.b = s.v", ddl=ddl)
    assert not any(x[0] == "ERROR" for x in f), f
    n += 1

    # 39. INSERT ALL: a branch with no column list is an error
    f = run("INSERT ALL INTO myschema.t1 VALUES (a, b) "
            "INTO myschema.t2 (x, y) VALUES (a, b) SELECT a, b FROM myschema.s")
    assert any("branch INTO myschema.t1 has no column list" in x[3] for x in f), f
    assert not any("t2" in x[3] and x[0] == "ERROR" for x in f), f
    n += 1

    # 40. INSERT ALL: an unqualified branch target is caught too
    f = run("INSERT ALL INTO t1 (x) VALUES (a) SELECT a FROM myschema.s")
    assert any("t1 is not schema-qualified" in x[3] for x in f), f
    n += 1

    # 41. plain INSERT ... VALUES now has its arity checked, not skipped
    f = run("INSERT INTO myschema.t (a, b, c) VALUES (1, 2)")
    assert any("ORA-00947" in x[3] for x in f), f
    n += 1

    # ---- v10: D-R3 and the column name rules ----------------------------- #

    # 42. a trailing semicolon is ORA-00911 waiting to happen
    f = run("INSERT INTO myschema.t (a) SELECT x FROM myschema.s;")
    assert any("ORA-00911" in x[3] for x in f), f
    n += 1

    # 43. two statements in one file break the one-line-per-file contract
    f = run("TRUNCATE TABLE myschema.t;\nINSERT INTO myschema.t (a) "
            "SELECT x FROM myschema.s")
    assert any("one command line per .sql file" in x[3] for x in f), f
    n += 1

    # 44. a PL/SQL block owns its semicolons and is left alone
    f = run("BEGIN\n  UPDATE myschema.t SET a = 1;\n  COMMIT;\nEND;")
    assert not any("ORA-00911" in x[3] for x in f), f
    n += 1

    # 45. an empty file is an error, not a pass
    f = run("   \n\n")
    assert any("file is empty" in x[3] for x in f), f
    n += 1

    # 46. a reserved word in the column list, with no DDL to say otherwise
    f = run("INSERT INTO myschema.t (date, first_name) SELECT a, b FROM myschema.s")
    assert any(x[0] == "ERROR" and "reserved word" in x[3] and "date" in x[3]
               for x in f), f
    assert not any("first_name" in x[3] for x in f), f
    n += 1

    # 47. the same word, but the DDL proves the column really exists
    rw = load_ddl(_tmp_ddl("TABLE_NAME,COLUMN_NAME,NULLABLE\nT,DATE,Y\n"))
    f = run("INSERT INTO myschema.t (date) SELECT a FROM myschema.s", ddl=rw)
    assert any(x[0] == "WARN" and "reserved word" in x[3] for x in f), f
    assert not any(x[0] == "ERROR" for x in f), f
    n += 1

    # 48. a quoted identifier is flagged as case-sensitive
    f = run('INSERT INTO myschema.t ("firstName") SELECT a FROM myschema.s')
    assert any("case-sensitive" in x[3] for x in f), f
    n += 1

    # 49. an over-long name is ORA-00972 territory on an older database
    long_name = "c" * 40
    f = run("INSERT INTO myschema.t (%s) SELECT a FROM myschema.s" % long_name)
    assert any(x[0] == "WARN" and "ORA-00972" in x[3] for x in f), f
    n += 1

    # 50. load_ddl reports which DDL-backed checks it can actually run
    load_ddl(_tmp_ddl("TABLE_NAME,COLUMN_NAME\nT,A\n"))
    assert LAST_DDL_META == {"has_nullable": False, "has_default": False,
                             "has_data_type": False}, LAST_DDL_META
    load_ddl(_tmp_ddl("TABLE_NAME,COLUMN_NAME,NULLABLE,DATA_DEFAULT\nT,A,N,\n"))
    assert LAST_DDL_META == {"has_nullable": True, "has_default": True,
                             "has_data_type": False}, LAST_DDL_META
    load_ddl(_tmp_ddl("TABLE_NAME,COLUMN_NAME,DATA_TYPE\nT,A,NUMBER\n"))
    assert LAST_DDL_META == {"has_nullable": False, "has_default": False,
                             "has_data_type": True}, LAST_DDL_META
    n += 1

    # ---- v12: D-R4, alias vs reserved word -------------------------------- #

    # 51. a bare table alias that is a reserved word is an error
    f = run("INSERT INTO myschema.t (a) SELECT x FROM myschema.s raw WHERE raw.x=1")
    assert any(x[0] == "ERROR" and 'alias "raw"' in x[3] for x in f), f
    n += 1

    # 52. an ordinary bare table alias stays quiet
    f = run("INSERT INTO myschema.t (a) SELECT x.a FROM myschema.s x")
    assert not any(x[0] == "ERROR" and "alias" in x[3] for x in f), f
    n += 1

    # 53. an explicit AS alias that is a reserved word is caught too
    f = run("INSERT INTO myschema.t (a) SELECT x FROM myschema.s AS raw")
    assert any('alias "raw"' in x[3] for x in f), f
    n += 1

    # 54. a subquery alias that is a reserved word -- the real case 34 bug
    f = run("INSERT INTO myschema.t (a) "
            "SELECT a FROM (SELECT x AS a FROM myschema.s) raw")
    assert any(x[0] == "ERROR" and 'alias "raw"' in x[3] for x in f), f
    n += 1

    # 55. a subquery alias that is NOT reserved stays quiet
    f = run("INSERT INTO myschema.t (a) "
            "SELECT a FROM (SELECT x AS a FROM myschema.s) landing_raw")
    assert not any("alias" in x[3] for x in f), f
    n += 1

    # 56. a reserved-word CTE name is caught
    f = run("INSERT INTO myschema.t (a) "
            "WITH raw AS (SELECT x AS a FROM myschema.s) SELECT a FROM raw")
    assert any(x[0] == "ERROR" and 'alias "raw"' in x[3] for x in f), f
    n += 1

    # 57. an ordinary CTE name stays quiet
    f = run("INSERT INTO myschema.t (a) "
            "WITH base AS (SELECT x AS a FROM myschema.s) SELECT a FROM base")
    assert not any("alias" in x[3] for x in f), f
    n += 1

    # 58. a MERGE target/USING alias that is reserved is caught too
    f = run("MERGE INTO myschema.tgt raw "
            "USING myschema.s s ON (raw.id = s.id) "
            "WHEN MATCHED THEN UPDATE SET raw.v1 = s.v1")
    assert any(x[0] == "ERROR" and 'alias "raw"' in x[3] for x in f), f
    n += 1

    # 59. an unaliased table (no alias at all) never trips D-R4
    f = run("INSERT INTO myschema.t (a) SELECT x FROM myschema.s WHERE x > 1 "
            "GROUP BY x ORDER BY x")
    assert not any("alias" in x[3] for x in f), f
    n += 1

    # 60. the WHERE/GROUP/ORDER/CONNECT/START keywords right after a table
    #     reference are never mistaken for an alias, reserved or not
    f = run("INSERT INTO myschema.t (a) SELECT x FROM myschema.s "
            "CONNECT BY PRIOR x = x START WITH x = 1")
    assert not any("alias" in x[3] for x in f), f
    n += 1

    # ---- v12: D-R5, UNION datatype mismatch -------------------------------- #

    union_ddl_csv = (
        "TABLE_NAME,COLUMN_NAME,DATA_TYPE\n"
        "VALID,CHK_DUPLICATE,CLOB\n"
        "TEMP,CHK_DUPLICATE,VARCHAR2\n"
        "TEMP,ID,NUMBER\n"
        "REJECT,ID,VARCHAR2\n"
    )
    union_ddl_path = _tmp_ddl(union_ddl_csv)
    union_ddl = load_ddl(union_ddl_path)
    os.remove(union_ddl_path)

    # 61. the real case 35 bug: CLOB vs VARCHAR2 across a UNION -> ORA-01790
    f = run("SELECT chk_duplicate FROM myschema.valid\n"
            "UNION\n"
            "SELECT chk_duplicate FROM myschema.temp", ddl=union_ddl)
    assert any(x[0] == "ERROR" and "ORA-01790" in x[3] and "position 1" in x[3]
               for x in f), f
    n += 1

    # 62. the same UNION, fixed with TO_CHAR() on the CLOB side, stays quiet
    f = run("SELECT TO_CHAR(chk_duplicate) AS chk_duplicate FROM myschema.valid\n"
            "UNION\n"
            "SELECT chk_duplicate FROM myschema.temp", ddl=union_ddl)
    assert not any(x[0] == "ERROR" and "UNION" in x[3] for x in f), f
    n += 1

    # 63. matching datatypes across a UNION stay quiet
    f = run("SELECT id FROM myschema.temp UNION ALL SELECT id FROM myschema.temp",
            ddl=union_ddl)
    assert not any("UNION" in x[3] for x in f), f
    n += 1

    # 64. a non-LOB mismatch (NUMBER vs VARCHAR2) is still an error
    f = run("SELECT id FROM myschema.temp UNION SELECT id FROM myschema.reject",
            ddl=union_ddl)
    assert any(x[0] == "ERROR" and "UNION position 1" in x[3] for x in f), f
    n += 1

    # 65. without --ddl, D-R5 says nothing at all (same policy as items 32-34)
    f = run("SELECT chk_duplicate FROM myschema.valid\n"
            "UNION\n"
            "SELECT chk_duplicate FROM myschema.temp")
    assert not any("UNION" in x[3] for x in f), f
    n += 1

    # 66. a UNION branch with a JOIN is skipped with a WARN, never guessed at
    f = run("SELECT t.id FROM myschema.temp t JOIN myschema.valid v ON t.id = v.id\n"
            "UNION\n"
            "SELECT id FROM myschema.reject", ddl=union_ddl)
    assert any(x[0] == "WARN" and "not a plain single-table FROM" in x[3]
               for x in f), f
    assert not any(x[0] == "ERROR" and "UNION" in x[3] for x in f), f
    n += 1

    # 67. a non-UNION statement is never touched by D-R5
    f = run("INSERT INTO myschema.t (a) SELECT chk_duplicate FROM myschema.valid",
            ddl=union_ddl)
    assert not any("UNION" in x[3] for x in f), f
    n += 1

    # 68. TO_DATE with one argument is flagged (rule D-R6)
    f = run("INSERT INTO myschema.t (a) SELECT TO_DATE(x) FROM myschema.s")
    assert any(x[0] == "WARN" and "TO_DATE(x)" in x[3] for x in f), f
    n += 1

    # 69. TO_DATE with a format mask is not flagged
    f = run("INSERT INTO myschema.t (a) SELECT TO_DATE(x, 'YYYYMMDD') FROM myschema.s")
    assert not any("format mask" in x[3] for x in f), f
    n += 1

    # 70. TO_TIMESTAMP with one argument is flagged too (rule D-R6)
    f = run("INSERT INTO myschema.t (a) SELECT TO_TIMESTAMP(x) FROM myschema.s")
    assert any(x[0] == "WARN" and "TO_TIMESTAMP(x)" in x[3] for x in f), f
    n += 1

    # 71. a single-argument TO_CHAR/TO_NUMBER is never flagged by rule D-R6
    #     itself (cannot tell a safe numeric call from a risky date one
    #     without a real column type) -- but IS flagged WARN by the separate
    #     checklist-item-43 check added in v1.6.0, see tests 81-82
    f = run("INSERT INTO myschema.t (a, b) SELECT TO_CHAR(n), TO_NUMBER(s) FROM myschema.s")
    assert not any(x[0] == "ERROR" and "format mask" in x[3] for x in f), f
    n += 1

    # ---- v1.5.0: D-R6 part 2, mask-present-but-wrong-type -------------------

    date_ddl_csv = (
        "TABLE_NAME,COLUMN_NAME,DATA_TYPE\n"
        "EXT_DSS_VW_SERVICE_MAPPING_BNO_KEY,EFFECTIVE_DATE,TIMESTAMP(6)\n"
        "EXT_DSS_VW_SERVICE_MAPPING_BNO_KEY,EXPIRED_DATE,TIMESTAMP(6)\n"
        "TB_LANDING_SS_ESIM,FIRST_INSTALLED,VARCHAR2(100)\n"
    )
    date_ddl_path = _tmp_ddl(date_ddl_csv)
    date_ddl = load_ddl(date_ddl_path)
    os.remove(date_ddl_path)

    # 72. the real TEST_AI_GEN_13 bug: a format mask IS present, but --ddl
    #     says the column is already TIMESTAMP -- rule D-R6 part 1 alone
    #     would stay silent on this (argument count is 2, looks normal)
    f = run("INSERT INTO myschema.t (a) SELECT TO_DATE(effective_date, "
            "'YYYY-MM-DD') FROM myschema.ext_dss_vw_service_mapping_bno_key",
            ddl=date_ddl)
    assert any(x[0] == "ERROR" and "already DATE/TIMESTAMP" in x[3]
               and "EFFECTIVE_DATE" in x[3] for x in f), f
    n += 1

    # 73. the same statement without --ddl: silently skipped, same as D-R5
    f = run("INSERT INTO myschema.t (a) SELECT TO_DATE(effective_date, "
            "'YYYY-MM-DD') FROM myschema.ext_dss_vw_service_mapping_bno_key")
    assert not any("already DATE/TIMESTAMP" in x[3] for x in f), f
    n += 1

    # 74. a column --ddl confirms is text (VARCHAR2) is not flagged by part 2
    #     -- wrapping genuinely text columns in TO_TIMESTAMP with a mask is
    #     the correct, unflagged shape
    f = run("INSERT INTO myschema.t (a) SELECT TO_TIMESTAMP(SUBSTR("
            "first_installed, 1, 14), 'YYYYMMDDHH24MISS') FROM "
            "myschema.tb_landing_ss_esim", ddl=date_ddl)
    assert not any("already DATE/TIMESTAMP" in x[3] for x in f), f
    n += 1

    # 75. when --ddl is given AND the mask is missing entirely, both halves
    #     of D-R6 fire independently: the no-mask WARN (part 1) and the
    #     already-a-date ERROR (part 2)
    f = run("INSERT INTO myschema.t (a) SELECT TO_DATE(effective_date) FROM "
            "myschema.ext_dss_vw_service_mapping_bno_key", ddl=date_ddl)
    assert any(x[0] == "WARN" and "has no format mask" in x[3] for x in f), f
    assert any(x[0] == "ERROR" and "already DATE/TIMESTAMP" in x[3]
               for x in f), f
    n += 1

    # 76. D-R6 part 3: a DATE/TIMESTAMP column (per --ddl) compared directly
    #     to a string literal, no TO_DATE() wrapper at all -- the other half
    #     of what case 28 / checklist item 43 named but v1.5.0 did not catch
    f = run("INSERT INTO myschema.t (a) SELECT 1 FROM "
            "myschema.ext_dss_vw_service_mapping_bno_key WHERE effective_date "
            "= '20250101'", ddl=date_ddl)
    assert any(x[0] == "ERROR" and "no TO_DATE()" in x[3] for x in f), f
    n += 1

    # 77. same statement without --ddl: silently skipped
    f = run("INSERT INTO myschema.t (a) SELECT 1 FROM "
            "myschema.ext_dss_vw_service_mapping_bno_key WHERE effective_date "
            "= '20250101'")
    assert not any("no TO_DATE()" in x[3] for x in f), f
    n += 1

    # 78. a text column (per --ddl) compared to a literal is not flagged
    f = run("INSERT INTO myschema.t (a) SELECT 1 FROM "
            "myschema.tb_landing_ss_esim WHERE first_installed = '20250101'",
            ddl=date_ddl)
    assert not any("no TO_DATE()" in x[3] for x in f), f
    n += 1

    # 79. BETWEEN with two literals on a DATE column is caught the same way
    f = run("INSERT INTO myschema.t (a) SELECT 1 FROM "
            "myschema.ext_dss_vw_service_mapping_bno_key WHERE effective_date "
            "BETWEEN '20250101' AND '20250131'", ddl=date_ddl)
    assert any(x[0] == "ERROR" and "no TO_DATE()" in x[3] for x in f), f
    n += 1

    # 80. literal-first order ('lit' = col) is caught too
    f = run("INSERT INTO myschema.t (a) SELECT 1 FROM "
            "myschema.ext_dss_vw_service_mapping_bno_key WHERE '20250101' = "
            "effective_date", ddl=date_ddl)
    assert any(x[0] == "ERROR" and "no TO_DATE()" in x[3] for x in f), f
    n += 1

    # 81. TO_CHAR/TO_NUMBER with one argument gets a WARN, never an ERROR --
    #     needs no --ddl, and is not part of D-R6 itself
    f = run("INSERT INTO myschema.t (a) SELECT TO_CHAR(some_num) FROM myschema.s")
    assert any(x[0] == "WARN" and "TO_CHAR(some_num)" in x[3] for x in f), f
    n += 1

    f = run("INSERT INTO myschema.t (a) SELECT TO_NUMBER(some_txt) FROM "
            "myschema.s")
    assert any(x[0] == "WARN" and "TO_NUMBER(some_txt)" in x[3] for x in f), f
    n += 1

    # 82. TO_CHAR with an explicit mask is not flagged
    f = run("INSERT INTO myschema.t (a) SELECT TO_CHAR(some_num, '999999') "
            "FROM myschema.s")
    assert not any("TO_CHAR(some_num" in x[3] and x[0] == "WARN" for x in f), f
    n += 1

    # 83. D-R7: TRUNCATE with no --partitions file still WARNs, never silent
    f = run("TRUNCATE TABLE myschema.tb_unsafe")
    assert any(x[0] == "WARN" and "no --partitions file" in x[3] for x in f), f
    n += 1

    part_csv = ("TABLE_NAME,PARTITIONS_EMPTY\n"
                "myschema.tb_safe,Y\n"
                "myschema.tb_unsafe,N\n")
    partitions = load_partitions(_tmp_ddl(part_csv))

    # 84. TRUNCATE on a table the --partitions file marks non-empty -> ERROR
    f = run("TRUNCATE TABLE myschema.tb_unsafe", partitions=partitions)
    assert any(x[0] == "ERROR" and "NON-empty" in x[3] for x in f), f
    n += 1

    # 85. TRUNCATE on a table the --partitions file confirms empty -> OK,
    #     never an ERROR
    f = run("TRUNCATE TABLE myschema.tb_safe", partitions=partitions)
    assert any(x[0] == "OK" and "confirms" in x[3] for x in f), f
    assert not any(x[0] == "ERROR" for x in f), f
    n += 1

    # 86. TRUNCATE on a table missing from the --partitions file -> WARN
    f = run("TRUNCATE TABLE myschema.tb_other", partitions=partitions)
    assert any(x[0] == "WARN" and "not listed" in x[3] for x in f), f
    n += 1

    # 87. D-R8: lenient numeric-mask parse with no REGEXP_LIKE guard -> WARN
    #     (this is the exact shape that let '20260827' through as MAP)
    f = run("INSERT INTO myschema.t (a) SELECT TO_TIMESTAMP(SUBSTR(x, 1, 14) "
            "DEFAULT NULL ON CONVERSION ERROR, 'YYYYMMDDHH24MISS') "
            "FROM myschema.s")
    assert any(x[0] == "WARN" and "D-R8" in x[3] for x in f), f
    assert not any(x[0] == "ERROR" and "D-R8" in x[3] for x in f), f
    n += 1

    # 88. D-R8: a REGEXP_LIKE shape guard in the statement clears the WARN
    f = run("INSERT INTO myschema.t (a) SELECT CASE WHEN REGEXP_LIKE("
            "SUBSTR(x, 1, 14), '^[0-9]{14}$') THEN TO_TIMESTAMP(SUBSTR(x, 1, "
            "14) DEFAULT NULL ON CONVERSION ERROR, 'YYYYMMDDHH24MISS') END "
            "FROM myschema.s")
    assert not any("D-R8" in x[3] for x in f), f
    n += 1

    # 89. D-R8: an FX mask is strict, so no WARN
    f = run("INSERT INTO myschema.t (a) SELECT TO_TIMESTAMP(x DEFAULT NULL ON "
            "CONVERSION ERROR, 'FXYYYYMMDDHH24MISS') FROM myschema.s")
    assert not any("D-R8" in x[3] for x in f), f
    n += 1

    print("check_sql selftest: %d assertions passed" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
