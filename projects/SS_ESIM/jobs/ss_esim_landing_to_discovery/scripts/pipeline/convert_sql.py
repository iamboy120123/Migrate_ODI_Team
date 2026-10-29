"""
convert_sql.py
---------------
Runbook Phase 1-3 (Step 3: Conversion) + Phase 4 (สร้าง status/REVIEW_FLAGS.md)

หน้าที่:
    แปลง SQL จาก output/sql/raw/*.sql (Spark SQL) เป็น Oracle 19c
    ตาม Dialect Map ใน CLAUDE.md ข้อ 5 แบบ regex/rule-based
    จุดที่ไม่สามารถแปลงอัตโนมัติได้อย่างปลอดภัย จะถูกบันทึกลง status/REVIEW_FLAGS.md
    เพื่อให้ agent_reviewer.py (AI) หรือ SA (manual) แก้ไขต่อใน Phase 4

กฎการแปลง (CLAUDE.md ข้อ 5):
    now() / current_timestamp()     -> SYSDATE
    x = '' / x <> ''                -> x IS NULL / x IS NOT NULL
    TRY_CAST(expr AS type)          -> CAST(expr AS type DEFAULT NULL ON CONVERSION ERROR)
    date_sub(x, n)                  -> (TRUNC(x) - n)
    SELECT *, expr                  -> [CRITICAL FLAG] ต้องมี table alias, ไม่ auto-fix
    TO_DATE(...)                    -> [CRITICAL FLAG] ต้องตรวจ format mask, ไม่ auto-fix
    BOOLEAN True/False              -> [FLAG] เสี่ยง false-positive สูง ไม่ auto-fix

Usage:
    python scripts/pipeline/convert_sql.py [--config config/config.json]
"""

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Dialect Map: กฎที่ "ปลอดภัยพอจะ auto-fix" (deterministic, ไม่กำกวม)
# ---------------------------------------------------------------------------

def rule_now_to_sysdate(sql: str) -> str:
    return re.sub(r"\b(now|current_timestamp)\s*\(\s*\)", "SYSDATE", sql, flags=re.IGNORECASE)


def rule_empty_string_to_null(sql: str) -> str:
    # x = ''  -> x IS NULL   /   x <> ''  -> x IS NOT NULL
    sql = re.sub(r"(\b[\w\.\"]+\b)\s*<>\s*''", r"\1 IS NOT NULL", sql)
    sql = re.sub(r"(\b[\w\.\"]+\b)\s*=\s*''", r"\1 IS NULL", sql)
    return sql


def rule_try_cast(sql: str) -> str:
    # TRY_CAST(expr AS type) -> CAST(expr AS type DEFAULT NULL ON CONVERSION ERROR)
    pattern = re.compile(r"TRY_CAST\s*\(\s*(.+?)\s+AS\s+(\w+(\(\d+(,\d+)?\))?)\s*\)", re.IGNORECASE)
    return pattern.sub(r"CAST(\1 AS \2 DEFAULT NULL ON CONVERSION ERROR)", sql)


def rule_date_sub(sql: str) -> str:
    # date_sub(x, n) -> (TRUNC(x) - n)
    pattern = re.compile(r"date_sub\s*\(\s*([^,\)]+)\s*,\s*([^\)]+)\)", re.IGNORECASE)
    return pattern.sub(r"(TRUNC(\1) - \2)", sql)


def rule_add_from_dual(sql: str) -> str:
    """Spark SQL อนุญาต SELECT ที่ไม่มี FROM เลย (เช่น SELECT constant ล้วนๆ สำหรับ
    workflow-status task) แต่ Oracle บังคับต้องมี FROM เสมอ - ถ้าไม่มีตารางจริงต้องใช้
    FROM DUAL ไม่งั้นจะได้ ORA-00923: FROM keyword not found where expected
    ตรวจแบบ whole-statement: ถ้าทั้งไฟล์เป็น SELECT เดียวและไม่มีคำว่า FROM เลย -> เติมต่อท้าย"""
    if not re.search(r"\bselect\b", sql, flags=re.IGNORECASE):
        return sql
    if re.search(r"\bfrom\b", sql, flags=re.IGNORECASE):
        return sql
    return sql.rstrip() + " FROM DUAL"


# Oracle reserved words (V$RESERVED_WORDS RESERVED='Y') - ใช้เป็น alias/identifier ไม่ได้
# Spark ยอมให้ใช้ (เช่น 040000 ใช้ `) raw CROSS JOIN` แล้วอ้าง raw.cdr_id) แต่ Oracle -> ORA-00933/ORA-00936
ORACLE_RESERVED = {
    "ACCESS", "ADD", "ALL", "ALTER", "AND", "ANY", "AS", "ASC", "AUDIT", "BETWEEN", "BY", "CHAR", "CHECK",
    "CLUSTER", "COLUMN", "COMMENT", "COMPRESS", "CONNECT", "CREATE", "CURRENT", "DATE", "DECIMAL", "DEFAULT",
    "DELETE", "DESC", "DISTINCT", "DROP", "ELSE", "EXCLUSIVE", "EXISTS", "FILE", "FLOAT", "FOR", "FROM",
    "GRANT", "GROUP", "HAVING", "IDENTIFIED", "IMMEDIATE", "IN", "INCREMENT", "INDEX", "INITIAL", "INSERT",
    "INTEGER", "INTERSECT", "INTO", "IS", "LEVEL", "LIKE", "LOCK", "LONG", "MAXEXTENTS", "MINUS", "MLSLABEL",
    "MODE", "MODIFY", "NOAUDIT", "NOCOMPRESS", "NOT", "NOWAIT", "NULL", "NUMBER", "OF", "OFFLINE", "ON",
    "ONLINE", "OPTION", "OR", "ORDER", "PCTFREE", "PRIOR", "PUBLIC", "RAW", "RENAME", "RESOURCE", "REVOKE",
    "ROW", "ROWID", "ROWNUM", "ROWS", "SELECT", "SESSION", "SET", "SHARE", "SIZE", "SMALLINT", "START",
    "SUCCESSFUL", "SYNONYM", "SYSDATE", "TABLE", "THEN", "TO", "TRIGGER", "UID", "UNION", "UNIQUE", "UPDATE",
    "USER", "VALIDATE", "VALUES", "VARCHAR", "VARCHAR2", "VIEW", "WHENEVER", "WHERE", "WITH",
}
_STR_LIT = re.compile(r"'(?:[^']|'')*'")
# ตำแหน่งที่เป็นการ "ตั้ง" alias: หลัง ) ของ subquery, หลังชื่อตารางใน FROM/JOIN, หลัง AS
_ALIAS_DEF = [
    re.compile(r"\)\s+([A-Za-z_]\w*)\b"),
    re.compile(r"\b(?:FROM|JOIN)\s+[A-Za-z_][\w.$#]*\s+([A-Za-z_]\w*)\b", re.I),
    re.compile(r"\bAS\s+([A-Za-z_]\w*)\b", re.I),
]


def _split_literals(sql: str):
    """คืน [(is_literal, text)] - ห้ามแก้ข้อความใน string literal (เช่น '(Raw=' ต้องตรงกับ Blendata)"""
    parts, pos = [], 0
    for m in _STR_LIT.finditer(sql):
        parts.append((False, sql[pos:m.start()])); parts.append((True, m.group(0))); pos = m.end()
    parts.append((False, sql[pos:]))
    return parts


def reserved_aliases(sql: str) -> set:
    code = " ".join(t for lit, t in _split_literals(sql) if not lit)
    found = set()
    for rx in _ALIAS_DEF:
        for m in rx.finditer(code):
            w = m.group(1).upper()
            if w in ORACLE_RESERVED:
                found.add(w)
    # alias ที่ถูกใช้เป็น qualifier (raw.cdr_id) นับด้วย - ยืนยันว่าเป็น alias ไม่ใช่ keyword ปกติ
    return {w for w in found if re.search(rf"\b{w}\s*\.", code, flags=re.I)}


def rule_reserved_alias(sql: str) -> str:
    """alias ที่เป็น Oracle reserved word -> เติม '_' ท้าย (raw -> raw_)
    แก้เฉพาะนอก string literal: ตำแหน่งที่ตั้ง alias + ตำแหน่งที่ใช้เป็น qualifier (alias.col)"""
    words = reserved_aliases(sql)
    if not words:
        return sql
    out = []
    for lit, t in _split_literals(sql):
        if not lit:
            for w in words:
                t = re.sub(rf"\b({w})(\s*\.)", r"\1_\2", t, flags=re.I)             # qualifier
                t = re.sub(rf"(\)\s+)({w})\b(?!\s*\.)", r"\1\2_", t, flags=re.I)    # ) raw
                t = re.sub(rf"(\bAS\s+)({w})\b(?!\s*\.)", r"\1\2_", t, flags=re.I)  # AS raw
                t = re.sub(rf"(\b(?:FROM|JOIN)\s+[A-Za-z_][\w.$#]*\s+)({w})\b(?!\s*\.)", r"\1\2_", t, flags=re.I)
        out.append(t)
    return "".join(out)


# ---------------------------------------------------------------------------
# v18: schema qualification (D-R2) + date rules ตาม md15 (D-R6 / D-R8)
# ค่าตั้งต้นของทั้งสองกฎมาจาก main() ผ่าน CTX - ไม่ฝังค่า schema ในโค้ด
# ---------------------------------------------------------------------------
CTX = {"prefix": "", "schema_mode": "literal", "logical_schema": "", "coltypes": {}}

_CHECKS_DIR = str(Path(__file__).resolve().parent.parent / "checks")


def _check_sql():
    if _CHECKS_DIR not in sys.path:
        sys.path.insert(0, _CHECKS_DIR)
    import check_sql  # noqa: E402  (ใช้ตัว mask / parser ชุดเดียวกับที่ตรวจ D-R2 เพื่อให้ผลตรงกัน)
    return check_sql


def schema_prefix_text() -> str:
    """ข้อความที่ใส่หน้าชื่อตาราง ตาม schema_mode:
    literal -> 'dssdev.'                                   (ตรงกับที่ md15 ใช้และ import ผ่านจริง)
    odiref  -> '<%=odiRef.getSchemaName("DSSDEV","D")%>.'  (ODI แปลงเป็น schema จริงจาก Topology ตอนรัน)"""
    if CTX["schema_mode"] == "odiref":
        return '<%=odiRef.getSchemaName("' + CTX["logical_schema"] + '","D")%>.'
    return CTX["prefix"] if CTX["prefix"].endswith(".") else CTX["prefix"] + "."


def rule_qualify_tables(sql: str) -> str:
    """D-R2: ODI ไม่เติม schema ให้ SQL ใน Procedure -> ชื่อตารางที่ไม่มี schema ต้องเติมเอง
    ไม่แตะ: ชื่อที่มี schema อยู่แล้ว, CTE, DUAL, subquery, FROM ใน EXTRACT/TRIM"""
    if not (CTX["prefix"] or CTX["schema_mode"] == "odiref"):
        return sql
    cs = _check_sql()
    masked = cs.mask_func_from(cs.mask(sql))
    ctes = cs.collect_ctes(masked)
    allowed = cs.BUILTIN_UNQUALIFIED | ctes
    spots = []
    for m in cs._TABLE_INTRO.finditer(masked):
        if re.sub(r"\s+", " ", m.group(1).lower()) == "truncate table":
            continue
        k = m.end()
        if k < len(masked) and masked[k] == "(":
            k = cs.paren_table_start(masked, k)   # K1: FROM ( tb_x CROSS JOIN ...) ต้อง qualify ด้วย
            if k is None:
                continue
        im = cs._IDENT.match(masked, k)
        if not im:
            continue
        name = sql[im.start():im.end()]
        low = name.lower()
        if "." in name or low in allowed or low in cs._NOT_A_TABLE:
            continue
        spots.append(im.start())
    pre = schema_prefix_text()
    for pos in sorted(set(spots), reverse=True):
        sql = sql[:pos] + pre + sql[pos:]
    return sql


_DATE_TOKENS = [("yyyy", "YYYY"), ("MM", "MM"), ("dd", "DD"), ("HH", "HH24"), ("mm", "MI"), ("ss", "SS")]


def spark_mask_to_oracle(mask: str):
    """แปลง mask ของ Spark เป็นของ Oracle เฉพาะ mask ที่เป็นตัวเลขล้วน (ไม่มีตัวคั่น)
    คืน (oracle_mask, ความยาวของข้อความที่คาดหวัง) หรือ None ถ้าไม่ใช่รูปที่รู้จัก"""
    out, i, n = [], 0, 0
    while i < len(mask):
        for spark, ora in _DATE_TOKENS:
            if mask.startswith(spark, i):
                out.append(ora)
                i += len(spark)
                n += len(spark)
                break
        else:
            return None
    return ("".join(out), n) if out else None


_COL = r"[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?"
_TO_TS_2ARG = re.compile(
    r"\bto_timestamp\s*\(\s*(?:left\s*\(\s*(?P<lx>" + _COL + r")\s*,\s*(?P<ln>\d+)\s*\)|(?P<x>" + _COL + r"))"
    r"\s*,\s*'(?P<mask>[^']*)'\s*\)", re.IGNORECASE)


def rule_to_timestamp_shape_guard(sql: str) -> str:
    """md15 C9 / D-R8: to_timestamp(text, 'yyyyMMddHHmmss') ของ Spark คืน NULL ถ้า parse ไม่ได้ แต่ Oracle
    โยน ORA-01858 ทั้ง statement -> ต้องมี REGEXP_LIKE shape guard + DEFAULT NULL ON CONVERSION ERROR
    ทำเฉพาะ mask ตัวเลขล้วนที่รู้จัก (ตัวอื่นปล่อยให้ถูก flag) - Spark to_timestamp พร้อม mask รับได้เฉพาะ text"""
    def repl(m):
        conv = spark_mask_to_oracle(m.group("mask"))
        if not conv:
            return m.group(0)
        ora_mask, length = conv
        if m.group("lx"):
            n = int(m.group("ln"))
            if n != length:      # left(x,N) ที่ N ไม่เท่าความยาว mask -> ไม่เดา
                return m.group(0)
            x = "SUBSTR(%s, 1, %d)" % (m.group("lx"), n)
        else:
            x = m.group("x")
        return ("CASE WHEN REGEXP_LIKE(%s, '^[0-9]{%d}$') THEN TO_TIMESTAMP(%s DEFAULT NULL ON CONVERSION ERROR, '%s') END"
                % (x, length, x, ora_mask))
    return _TO_TS_2ARG.sub(repl, sql)


_TO_DATE_1ARG = re.compile(r"\bto_date\s*\(\s*(" + _COL + r")\s*\)", re.IGNORECASE)


def rule_to_date_on_date_column(sql: str) -> str:
    """md15 D-R6 / C12: to_date(x) แบบไม่มี mask
    - DDL บอกว่า x เป็น DATE/TIMESTAMP อยู่แล้ว (ทุกตารางที่มีคอลัมน์ชื่อนี้) -> TRUNC(x)  (ห้ามห่อ TO_DATE)
    - ไม่มีใน DDL หรือชนิดไม่ชัด/ขัดกัน -> ไม่แตะ ถูก flag ให้ไประบุชนิดจริง (ห้ามเดา)"""
    def repl(m):
        col = m.group(1).split(".")[-1].lower()
        types = CTX["coltypes"].get(col)
        if types and all(t.startswith(("DATE", "TIMESTAMP")) for t in types):
            return "TRUNC(%s)" % m.group(1)
        return m.group(0)
    return _TO_DATE_1ARG.sub(repl, sql)


def load_coltypes(ddl_dir: Path) -> dict:
    """column name (lower) -> {ชนิดข้อมูลที่พบทุกตาราง} จาก input/oracle_ddl/*.csv"""
    types: dict = {}
    if not ddl_dir.is_dir():
        return types
    cs = _check_sql()
    for f in sorted(ddl_dir.glob("*.csv")):
        try:
            tables = cs.load_ddl(str(f))
        except (ValueError, OSError) as e:
            print(f"[WARN] อ่าน DDL {f.name} ไม่ได้: {e}")
            continue
        for cols in tables.values():
            for c in cols:
                types.setdefault(c["name"], set()).add((c["data_type"] or "").upper())
    return types



# ---------------------------------------------------------------------------
# v18: กฎแปลงเชิงกลไก (ไม่มีความกำกวมเรื่องความหมาย) ที่ผู้ใช้เลือกเปิด/ปิดได้ใน config:
#   "convert_rules": {"date_format": "auto" | "flag", ...}
#   auto = แปลงให้เลย · flag = ไม่แตะ ปล่อยให้ถูก flag ใน REVIEW_FLAGS ให้คน/AI แก้ตาม md15 appendix D
# ส่วนที่ md15 ระบุว่า "ต้องให้คนตัดสิน" (concat 3+ arg, split/reverse, regexp_extract, TRUE/FALSE, \d \s) ไม่มีกฎ auto - flag เสมอ
# ---------------------------------------------------------------------------
RULE_DEFAULTS = {
    "get_user": "auto",        # get_user() -> USER                         (md15 group B)
    "format_string": "auto",   # format_string('%09d', n) -> LPAD(TO_CHAR(n), 9, '0')   (C3)
    "date_format": "auto",     # date_format(x,'yyyyMMdd') -> TO_CHAR(x,'YYYYMMDD') เฉพาะ mask ที่รู้จัก
    "order_by_const": "auto",  # over(order by 1) -> over(ORDER BY NULL)    (C4)
    "like_escape": "auto",     # LIKE '%\_x%' -> ... ESCAPE '\'              (C8)
    "cast_types": "auto",      # CAST(x AS long/string/int/...) -> ชนิด Oracle (md15 group B)
    "interval": "auto",        # INTERVAL 5 MINUTE -> INTERVAL '5' MINUTE   (md15 group B)
    "bigint_ctor": "auto",     # bigint(x) -> TO_NUMBER(x)                  (md15 group B)
    "nullif_empty": "auto",    # nullif(x,'') -> x  (ผลข้างเคียง: ' ' เว้นวรรคยังไม่เป็น NULL - C11)
}
RULE_MODE = dict(RULE_DEFAULTS)


def _calls(sql: str, fname: str):
    """หาการเรียก fname(...) ตัวแรกที่ยังไม่ถูกแปลง คืน (start, end, [ข้อความ arg ...]) หรือ None (ข้าม string/comment)"""
    cs = _check_sql()
    masked = cs.mask(sql)
    for m in re.finditer(r"\b" + fname + r"\s*\(", masked, flags=re.IGNORECASE):
        end = cs.match_paren(masked, m.end() - 1)
        if end < 0:
            continue
        parts = cs.split_top(masked, m.end(), end - 1)
        return m.start(), end, [sql[a:b].strip() for a, b in parts]
    return None


def _replace_calls(sql: str, fname: str, build) -> str:
    """แทนที่ทุกการเรียก fname(...) ด้วย build(args) (คืน None = ปล่อยไว้) - ทำทีละตัวจากซ้ายไปขวา"""
    out, pos = "", 0
    for _ in range(5000):
        hit = _calls(sql[pos:], fname)
        if not hit:
            break
        a, b, args = hit
        new = build(args)
        if new is None:
            out += sql[pos:pos + b]          # ข้ามตัวนี้ (แปลงไม่ได้) ไปหาตัวถัดไป
            pos += b
            continue
        out += sql[pos:pos + a] + new
        pos += b
    return out + sql[pos:]


def rule_get_user(sql: str) -> str:
    return re.sub(r"\bget_user\s*\(\s*\)", "USER", sql, flags=re.IGNORECASE)


def rule_format_string(sql: str) -> str:
    def build(args):
        m = re.fullmatch(r"'%0(\d+)d'", args[0]) if len(args) == 2 else None
        return "LPAD(TO_CHAR(%s), %s, '0')" % (args[1], m.group(1)) if m else None
    return _replace_calls(sql, "format_string", build)


_FMT_OK = re.compile(r"(?:yyyy|MM|dd|HH|mm|ss|[-/: ])+")


def rule_date_format(sql: str) -> str:
    def build(args):
        if len(args) != 2:
            return None
        m = re.fullmatch(r"'([^']*)'", args[1])
        if not m or not _FMT_OK.fullmatch(m.group(1)):
            return None
        ora, i, mask = [], 0, m.group(1)
        while i < len(mask):
            for spark, o in _DATE_TOKENS:
                if mask.startswith(spark, i):
                    ora.append(o)
                    i += len(spark)
                    break
            else:
                ora.append(mask[i])
                i += 1
        return "TO_CHAR(%s, '%s')" % (args[0], "".join(ora))
    return _replace_calls(sql, "date_format", build)


def rule_order_by_const(sql: str) -> str:
    return re.sub(r"(\bover\s*\(\s*(?:partition\s+by[^()]*?)?)order\s+by\s+\d+\s*\)", r"\1ORDER BY NULL)", sql, flags=re.IGNORECASE)


def rule_like_escape(sql: str) -> str:
    return re.sub(r"(\blike\s+'[^']*\\[^']*')(?!\s+escape)", r"\1 ESCAPE '\\'", sql, flags=re.IGNORECASE)


_CAST_MAP = {"long": "NUMBER", "bigint": "NUMBER(19)", "int": "NUMBER(10)", "integer": "NUMBER(10)",
             "string": "VARCHAR2(4000)", "double": "NUMBER", "float": "NUMBER"}


def rule_cast_types(sql: str) -> str:
    return re.sub(r"(\bAS\s+)(long|bigint|integer|int|string|double|float)(\s*\))",
                  lambda m: m.group(1) + _CAST_MAP[m.group(2).lower()] + m.group(3), sql, flags=re.IGNORECASE)


def rule_interval(sql: str) -> str:
    return re.sub(r"\binterval\s+(\d+)\s+(day|hour|minute|second|month|year)s?\b",
                  lambda m: "INTERVAL '%s' %s" % (m.group(1), m.group(2).upper()), sql, flags=re.IGNORECASE)


def rule_bigint_ctor(sql: str) -> str:
    return re.sub(r"\bbigint\s*\(", "TO_NUMBER(", sql, flags=re.IGNORECASE)


def rule_nullif_empty(sql: str) -> str:
    return _replace_calls(sql, "nullif", lambda a: a[0] if len(a) == 2 and a[1] == "''" else None)


MECHANICAL_RULES = [
    ("get_user", rule_get_user), ("format_string", rule_format_string), ("date_format", rule_date_format),
    ("order_by_const", rule_order_by_const), ("like_escape", rule_like_escape), ("cast_types", rule_cast_types),
    ("interval", rule_interval), ("bigint_ctor", rule_bigint_ctor), ("nullif_empty", rule_nullif_empty),
]


def rule_mechanical(sql: str) -> str:
    for name, fn in MECHANICAL_RULES:
        if RULE_MODE.get(name) == "auto":
            sql = fn(sql)
    return sql



# ---------------------------------------------------------------------------
# v18: concat() - นโยบายเดียวต่อโปรเจกต์ ผู้ใช้เป็นคนเลือก (md15 C1/C2; ไม่มีค่าตั้งต้น ไม่ตั้ง = ติด flag ให้คนตัดสิน)
#   "concat_policy": "spark_null"   -> คง semantic ของ Spark: ถ้ามี arg ใด NULL ผลเป็น NULL
#                                       CASE WHEN a IS NULL OR b IS NULL THEN NULL ELSE a || b END
#                    "plain_concat" -> a || b (Oracle มอง NULL เป็นค่าว่าง ผลต่างจาก Spark เมื่อ arg เป็น NULL)
# ---------------------------------------------------------------------------
CONCAT_POLICY = {"mode": ""}


def _is_atom(arg: str) -> bool:
    """arg ที่ใช้กับ || ได้โดยไม่ต้องครอบวงเล็บ: ชื่อคอลัมน์, string literal, หรือการเรียกฟังก์ชันที่วงเล็บปิดท้ายพอดี"""
    if re.fullmatch(r"[\w.$]+|'(?:[^']|'')*'", arg):
        return True
    m = re.match(r"[\w.$]+\s*\(", arg)
    if m:
        cs = _check_sql()
        return cs.match_paren(cs.mask(arg), m.end() - 1) == len(arg)
    return False


def rule_concat_policy(sql: str) -> str:
    mode = CONCAT_POLICY["mode"]
    if mode not in ("spark_null", "plain_concat"):
        return sql

    def build(args):
        if len(args) == 1:                    # concat(x) = x (md15 C1: argument เดียวให้ตัดทิ้ง)
            return args[0] if _is_atom(args[0]) else "(" + args[0] + ")"
        if len(args) < 2:
            return None
        parts = [a if _is_atom(a) else "(" + a + ")" for a in args]
        joined = " || ".join(parts)
        if mode == "plain_concat":
            return "(" + joined + ")"
        nullable = [a for a in parts if not a.startswith("'")]
        if not nullable:
            return "(" + joined + ")"
        cond = " OR ".join(a + " IS NULL" for a in nullable)
        return "CASE WHEN " + cond + " THEN NULL ELSE " + joined + " END"
    out = sql
    for _ in range(50):                       # concat ซ้อน concat: แปลงจากในออกนอกทีละชั้น
        new = _replace_calls(out, "concat", build)
        if new == out:
            break
        out = new
    return out


AUTO_FIX_RULES = [
    ("now()/current_timestamp() -> SYSDATE", rule_now_to_sysdate),
    ("empty string -> IS [NOT] NULL", rule_empty_string_to_null),
    ("TRY_CAST -> CAST ... DEFAULT NULL ON CONVERSION ERROR", rule_try_cast),
    ("date_sub(x,n) -> (TRUNC(x) - n)", rule_date_sub),
    ("SELECT ไม่มี FROM -> เติม FROM DUAL (Oracle ต้องมี FROM เสมอ, ORA-00923 ถ้าไม่มี)", rule_add_from_dual),
    ("alias เป็น Oracle reserved word -> เติม _ (raw -> raw_) ไม่แตะ string literal", rule_reserved_alias),
    ("to_timestamp(text,'yyyyMMddHHmmss') -> REGEXP_LIKE shape guard + DEFAULT NULL ON CONVERSION ERROR (md15 C9 / D-R8)", rule_to_timestamp_shape_guard),
    ("to_date(col) เมื่อ DDL ระบุว่าเป็น DATE/TIMESTAMP แล้ว -> TRUNC(col) (md15 D-R6)", rule_to_date_on_date_column),
    ("กฎเชิงกลไก (get_user/format_string/date_format/...) ตาม convert_rules ใน config", rule_mechanical),
    ("concat() -> || ตาม concat_policy ใน config (spark_null | plain_concat; ไม่ตั้ง = flag)", rule_concat_policy),
    ("ใส่ schema หน้าตารางที่ไม่มี schema (D-R2) ตาม schema_mode", rule_qualify_tables),
]

# ---------------------------------------------------------------------------
# กฎที่ "ต้อง flag" เพราะแก้อัตโนมัติแบบปลอดภัยไม่ได้ (ตาม CLAUDE.md [CRITICAL FLAG])
# ---------------------------------------------------------------------------

def find_select_star_with_expr(sql: str) -> list[str]:
    """SELECT *, expr ที่ไม่มี table alias -> Oracle ปฏิเสธ ต้องแก้มือ/AI review"""
    hits = []
    for m in re.finditer(r"SELECT\s+\*\s*,", sql, flags=re.IGNORECASE):
        hits.append(m.group(0))
    return hits


def find_to_date_calls(sql: str) -> list[str]:
    """ทุก TO_DATE(...) ต้องตรวจ format mask ให้ตรง Oracle - ไม่ auto-fix"""
    return re.findall(r"TO_DATE\s*\([^)]*\)", sql, flags=re.IGNORECASE)


def find_boolean_literals(sql: str) -> list[str]:
    """BOOLEAN True/False -> ต้องแปลงเป็น 'TRUE'/'FALSE' string แต่เสี่ยง false-positive
    (เช่น True อาจเป็นชื่อ column) จึงให้คน/AI ตัดสินใจแทนการ auto-fix"""
    return [m.group(0) for m in re.finditer(r"(?<![\w'])(true|false)(?![\w'])", sql, flags=re.IGNORECASE)]



# ---------------------------------------------------------------------------
# Dialect gap: Spark-ism ที่ Oracle 19c ไม่มี/ต่างความหมาย - flag อย่างเดียว ไม่ auto-fix
# (เพิ่มหลังพบว่า export จริงของ ss_esim ใช้ construct เหล่านี้หนาแน่น)
# ---------------------------------------------------------------------------

def _finds(pattern):
    def fn(sql: str) -> list[str]:
        return [m.group(0) for m in re.finditer(pattern, sql, flags=re.IGNORECASE)]
    return fn


find_date_format = _finds(r"date_format\s*\([^()]*\)")
find_spark_cast_types = _finds(r"\bAS\s+(long|string|int|bigint|double|boolean|timestamp)\b")
find_type_ctor = _finds(r"\b(bigint|smallint|tinyint|double|float|string)\s*\(")
find_interval_literal = _finds(r"\binterval\s+\d+\s+\w+")
find_split_array = _finds(r"\b(split|reverse|element_at|explode)\s*\(|\]\s*\[|\)\s*\[\s*\d+\s*\]")
find_regexp_extract = _finds(r"\bregexp_(extract|replace)\s*\([^;]{0,120}?\)")
find_format_string = _finds(r"\bformat_string\s*\([^()]*\)")
find_get_user = _finds(r"\bget_user\s*\(\s*\)")
find_left_right = _finds(r"\b(left|right)\s*\(")
def find_to_timestamp(sql: str) -> list[str]:
    """to_timestamp ที่ยังไม่มี shape guard / DEFAULT NULL ON CONVERSION ERROR (ตัวที่แปลงแล้วไม่ flag ซ้ำ)"""
    hits = []
    for m in re.finditer(r"\bto_timestamp\s*\([^()]*(\([^()]*\))?[^()]*\)", sql, flags=re.IGNORECASE):
        if "DEFAULT NULL ON CONVERSION ERROR" in m.group(0).upper():
            continue
        hits.append(m.group(0))
    return hits
find_nullif_empty = _finds(r"\bnullif\s*\([^,]+,\s*''\s*\)")
find_like_escape = _finds(r"like\s+'[^']*\\[^']*'(?!\s+escape)")
find_order_by_const = _finds(r"over\s*\(\s*order\s+by\s+\d+\s*\)")


def find_concat_multi(sql: str) -> list[str]:
    """concat() ของ Spark รับหลาย arg และคืน NULL ถ้ามี arg ใดเป็น NULL
    Oracle CONCAT รับ 2 arg และ || มองว่า NULL = '' -> ความหมายต่างกัน"""
    hits = []
    for m in re.finditer(r"\bconcat\s*\(", sql, flags=re.IGNORECASE):
        depth, i = 0, m.end() - 1
        while i < len(sql):
            if sql[i] == "(":
                depth += 1
            elif sql[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        hits.append(sql[m.start():min(i + 1, m.start() + 80)])
    return hits


FLAG_CHECKS = [
    ("[CRITICAL] SELECT *, expr ไม่มี table alias", find_select_star_with_expr),
    ("[CRITICAL] TO_DATE(...) ต้องตรวจ format mask", find_to_date_calls),
    ("[FLAG] BOOLEAN literal true/false - Oracle 19c ไม่มี BOOLEAN ใน SQL ต้อง map เป็น NUMBER(1)", find_boolean_literals),
    ("[CRITICAL] date_format(x,mask) -> TO_CHAR(x,mask) และ mask ของ Spark/Oracle ไม่ตรงกัน", find_date_format),
    ("[CRITICAL] Spark type ใน CAST (long/string/int/...) ไม่มีใน Oracle", find_spark_cast_types),
    ("[CRITICAL] type constructor แบบ bigint(x)/string(x) ไม่มีใน Oracle", find_type_ctor),
    ("[CRITICAL] INTERVAL n unit ต้องเป็น INTERVAL 'n' UNIT ใน Oracle", find_interval_literal),
    ("[CRITICAL] split/reverse/array index ไม่มีใน Oracle ต้องใช้ REGEXP_SUBSTR", find_split_array),
    ("[CRITICAL] regexp_extract -> REGEXP_SUBSTR(...,1,1,NULL,n); regexp_replace semantics ต่างกัน", find_regexp_extract),
    ("[CRITICAL] format_string('%0Nd',x) -> LPAD(TO_CHAR(x),N,'0')", find_format_string),
    ("[CRITICAL] get_user() -> USER", find_get_user),
    ("[CRITICAL] left()/right() ไม่มีใน Oracle ต้องใช้ SUBSTR", find_left_right),
    ("[CRITICAL] to_timestamp/to_date ของ Spark คืน NULL เมื่อแปลงไม่ได้ Oracle จะ error ต้องใส่ DEFAULT NULL ON CONVERSION ERROR", find_to_timestamp),
    ("[FLAG] nullif(x,'') ไม่มีความหมายใน Oracle (''=NULL อยู่แล้ว)", find_nullif_empty),
    ("[CRITICAL] LIKE ที่มี backslash escape ต้องมี ESCAPE clause ใน Oracle", find_like_escape),
    ("[CRITICAL] OVER(ORDER BY <constant>) ใช้ไม่ได้ใน Oracle ต้องเป็น ORDER BY NULL", find_order_by_const),
    ("[CRITICAL] concat() หลาย arg: Spark คืน NULL ถ้ามี arg เป็น NULL แต่ || ของ Oracle ไม่คืน", find_concat_multi),
]


def convert_one(sql: str) -> str:
    for _, fn in AUTO_FIX_RULES:
        sql = fn(sql)
    return sql


def collect_flags(task_id: str, sql: str) -> list[dict]:
    flags = []
    for reason, fn in FLAG_CHECKS:
        hits = fn(sql)
        for h in hits:
            flags.append({
                "task_id": task_id,
                "reason": reason,
                "snippet": h.strip(),
                "status": "PENDING",
            })
    return flags


def write_review_flags_md(path: Path, flags: list[dict], ai_mode: str):
    lines = [
        "# status/REVIEW_FLAGS.md",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"AI Mode: `{ai_mode}`",
        "",
        "SQL ที่ถูกแปลงอัตโนมัติแล้วแต่ยังต้องผ่านการตรวจทาน (โดย AI ถ้า auto, โดย SA ถ้า manual)",
        "ก่อนเข้า Phase 5 (gen_dml.py) ทุกแถวต้องมี status = RESOLVED",
        "",
        "| Task ID | Reason | Snippet | Status |",
        "|---|---|---|---|",
    ]
    if not flags:
        lines.append("| - | ไม่มีรายการค้าง | - | - |")
    else:
        for f in flags:
            snippet = f["snippet"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {f['task_id']} | {f['reason']} | `{snippet}` | {f['status']} |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.json")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))

    raw_dir = Path(config["paths"]["output_raw_sql"])
    converted_dir = Path(config["paths"]["output_converted_sql"])
    review_flags_path = Path(config["paths"]["review_flags"])
    converted_dir.mkdir(parents=True, exist_ok=True)

    mode = (config.get("schema_mode") or "literal").strip().lower()   # ไม่ตั้ง = literal
    if mode not in ("literal", "odiref"):
        sys.exit("[ERROR] schema_mode ต้องเป็น literal หรือ odiref (ได้: %r)" % mode)
    CTX["schema_mode"] = mode
    CTX["prefix"] = (config.get("target_table_prefix") or "").strip()
    CTX["logical_schema"] = ((config.get("odi") or {}).get("logical_schema") or "").strip()
    if mode == "literal" and not CTX["prefix"]:
        sys.exit("[ERROR] schema_mode=literal ต้องมี target_table_prefix ใน config (เช่น \"dssdev.\") "
                 "- ไม่มี schema จะไม่ใส่ให้ และ SQL จะพังตอนรัน (D-R2)")
    if mode == "odiref" and not CTX["logical_schema"]:
        sys.exit("[ERROR] schema_mode=odiref ต้องมี odi.logical_schema ใน config")
    cp = (config.get("concat_policy") or "").strip().lower()
    if cp not in ("", "spark_null", "plain_concat"):
        sys.exit("[ERROR] concat_policy ต้องเป็น spark_null หรือ plain_concat (หรือไม่ตั้ง = flag ให้คนตัดสิน) ได้: %r" % cp)
    CONCAT_POLICY["mode"] = cp
    print("[INFO] concat_policy=" + (cp or "(ไม่ตั้ง: concat ติด flag ให้คนตัดสิน)"))
    user_rules = config.get("convert_rules") or {}
    bad = [k for k in user_rules if k not in RULE_DEFAULTS] + [k for k, v in user_rules.items() if v not in ("auto", "flag")]
    if bad:
        sys.exit("[ERROR] convert_rules ไม่ถูกต้อง: %s (ชื่อที่ใช้ได้: %s ; ค่าต้องเป็น auto หรือ flag)"
                 % (", ".join(map(str, bad)), ", ".join(RULE_DEFAULTS)))
    RULE_MODE.update(user_rules)
    print("[INFO] convert_rules: " + " ".join(f"{k}={v}" for k, v in RULE_MODE.items()))
    CTX["coltypes"] = load_coltypes(Path("input/oracle_ddl"))
    print(f"[INFO] schema_mode={mode} · DDL: {len(CTX['coltypes'])} คอลัมน์"
          + ("" if CTX["coltypes"] else " (ไม่มี DDL: to_date(col) จะไม่ถูกแก้อัตโนมัติ ต้องระบุชนิดจริงก่อน)"))

    sql_files = sorted(raw_dir.glob("*.sql"))
    if not sql_files:
        sys.exit(f"[ERROR] ไม่พบไฟล์ .sql ใน {raw_dir} - รัน extract_workflow.py ก่อน")

    all_flags = []
    for f in sql_files:
        task_id = f.stem
        original = f.read_text(encoding="utf-8")

        converted = convert_one(original)
        flags = collect_flags(task_id, converted)
        all_flags.extend(flags)

        out_path = converted_dir / f.name
        out_path.write_text(converted, encoding="utf-8")

        status = "FLAGGED" if flags else "OK"
        print(f"[{status}] {task_id} -> {out_path}")

    write_review_flags_md(review_flags_path, all_flags, config.get("ai_mode", "manual"))

    print(f"\n[SUMMARY] แปลงแล้ว {len(sql_files)} ไฟล์, พบ {len(all_flags)} จุดที่ต้องรีวิว")
    print(f"[SUMMARY] status/REVIEW_FLAGS.md: {review_flags_path}")

    if all_flags:
        if config.get("ai_mode") == "auto":
            print("\nขั้นตอนถัดไป: python scripts/pipeline/agent_reviewer.py  (AI Mode = auto)")
        else:
            print("\nขั้นตอนถัดไป: แก้ไข SQL ที่ถูก flag ด้วยตนเองใน output/sql/converted/")
            print("จากนั้นอัปเดต status ใน status/REVIEW_FLAGS.md เป็น RESOLVED แล้วค่อยรัน gen_dml.py")
    else:
        print("\nไม่มีรายการค้าง -> ขั้นตอนถัดไป: python scripts/pipeline/gen_dml.py")


if __name__ == "__main__":
    main()
