#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
odi_smartexport.py -- reusable builder for ODI 14c SmartExport XML
(Procedure-based architecture: SnpTrt / SnpLineTrt / SnpTxtHeader with raw SQL).

WHY THIS FILE EXISTS
--------------------
Hand-writing this XML from memory fails. Real ODI Studio imports rejected it
three separate times before this library existed:
  1. Package diagram showed no connecting arrows  -> OkExit wired wrong
  2. ODI-10113 "Logical Schema ... Broken Link"   -> topology referenced by
     FKXRef only, without embedding the full objects
  3. com.sunopsis.core.SnpsInexistantObjectException at
     SnpOrigTxt.getOrigTxtById()                  -> ITxtOrig ids invented
     instead of taken from the repository's own standing reference rows
and a parallel effort on the same repository hit two more (ORA-01400 on a
NOT NULL column defaulted to null; a NullPointerException from a field typed
DbInt that is really java.lang.String). appendix/C-failure-catalog.md has
them all; this library encodes a guard for each.

CORE PRINCIPLE: NOTHING IS INVENTED.
Every repository-specific value is READ OUT OF A REAL REFERENCE SmartExport
exported from the target repository:

  * topology objects and their GlobalIds  -> clone_topology()
  * the seeded SnpOrigTxt ids             -> Reference.origtxt_ids()
  * field name/type layout                -> CANONICAL + verify_layouts()
  * NOT NULL columns                      -> Reference.required_fields()
  * flag conventions (owning user, TrtType, ExeChannel, AlwaysExe, ...)
                                          -> Reference.conventions()
  * SqlIndGrp per statement kind          -> Reference.sqlindgrp_rules()
  * <Admin> and <Encryption> headers      -> copied from the reference

Only genuinely-new objects (the new Project, Folder, Package, Procedures,
Variables, Steps) get freshly generated GlobalIds. Anything the reference
cannot settle is either derived, asked for, or reported as a warning naming
the built-in literal that stood in -- never silently assumed.

TYPICAL USE
-----------
    from odi_smartexport import Reference, Doc

    ref = Reference("ODI_REFERENCE_DEV.xml")     # from the TARGET repository
    doc = Doc(ref, project_name="ai_test_01", project_code="AI_TEST_01")
    doc.clone_topology()
    doc.add_project()
    doc.clone_seed_states()
    doc.add_variable("V_WORKFLOW_PROCESS_DATE", sql)      # SqlIndGrp derived
    doc.add_procedure("040000_x", [(None, None, truncate_sql),   # Ord 10
                                   (None, None, insert_sql)])    # Ord 20
    doc.add_steps([...])
    report = doc.validate()          # errors block the write; warnings do not
    doc.write_zip("out/SmartExport.xml", "out/pkg.zip")

OrdTrt is the command line's POSITION (first line = 10), and SqlIndGrp is a
property of the STATEMENT (TRUNCATE -> "0", INSERT/MERGE -> "2"). They are
independent; pass None for either and the builder fills it in from the
reference's own examples.
"""

import datetime
import os
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict

__version__ = "1.4.0"

# The encoding a real ODI export declares in its prolog. Both real exports
# inspected (a Smart Export and an Export Project of the same project) declare
# ISO-8859-1 and contain no byte above 0x7F at all -- so there is no observed
# example of how ODI writes a character this encoding cannot represent.
# Rather than guess an escape mechanism, the writer refuses such text.
FILE_ENCODING = "ISO-8859-1"

# ODI's own bind-variable namespace for global variables: #GLOBAL.MY_VAR.
# Project variables use #<PROJECT_CODE>.<VAR>.
GLOBAL_VAR_PREFIX = "GLOBAL"

# ---------------------------------------------------------------------------
# Field types as they appear in the SmartExport XML's type="" attribute.
# NOTE: many flag fields that LOOK numeric ("0"/"1"/"3") are declared
# java.lang.String in the ODI repository schema, not DbInt. Getting this wrong
# does not always fail loudly -- copy the canonical lists below, do not guess.
# ---------------------------------------------------------------------------
S = "java.lang.String"
I = "com.sunopsis.sql.DbInt"
T = "java.sql.Timestamp"

PKG = "com.sunopsis.dwg.dbobj."

# Topology objects cloned verbatim out of the reference export.
TOPOLOGY_CLASSES = [
    "SnpConnect", "SnpMtxt", "SnpConnectProp",
    "SnpContext", "SnpLschema", "SnpPschema", "SnpPschemaCont",
]

# RefKey prefixes belonging to topology (cloned verbatim from the reference).
TOPOLOGY_REFKEY_PREFIXES = (
    "SNP_TECHNO.", "SNP_MTXT.", "SNP_CONNECT.",
    "SNP_CONTEXT.", "SNP_LSCHEMA.", "SNP_PSCHEMA.",
)

# SnpOrigTxt is standing reference data seeded into the repository itself.
# Its ITxtOrig ids are NOT assignable -- they are read from the reference.
ORIGTXT_SLOTS = {
    "var_query":     ("SNP_VAR",      "I_TXT_VAR_IN"),
    "trt_edit_cmd":  ("SNP_TRT",      "I_TXT_TRT_TXT"),
    "linetrt_sql":   ("SNP_LINE_TRT", "DEF_I_TXT"),
}


# ---------------------------------------------------------------------------
# Conventions -- flag values are DERIVED, not hardcoded.
#
# Reference.conventions() reads them out of the target repository's own export:
# any field carrying the same non-null value in EVERY instance of its class is
# that repository's convention for that field. The literals below are used only
# when the reference cannot decide (fewer than two instances of the class, or
# the field genuinely varies), and every such fallback is reported as a build
# warning -- so the builder never silently substitutes one repository's habits
# for another's.
# ---------------------------------------------------------------------------
FALLBACK_CONVENTIONS = {
    "SnpProject":   {"FirstUser": "SUPERVISOR", "LastUser": "SUPERVISOR"},
    "SnpFolder":    {"FirstUser": "SUPERVISOR", "LastUser": "SUPERVISOR"},
    "SnpPackage":   {"FirstUser": "SUPERVISOR", "LastUser": "SUPERVISOR"},
    "SnpVar":       {"FirstUser": "SUPERVISOR", "LastUser": "SUPERVISOR",
                     "IndStore": "L", "VarDatatype": "T", "VarType": "P"},
    "SnpTrt":       {"FirstUser": "SUPERVISOR", "LastUser": "SUPERVISOR",
                     "CleanupOnError": "0", "IndGenerateLoad": "0",
                     "IndIsHidden": "0", "IsConcurrent": "0",
                     "KimMultiDserver": "1", "TrtType": "U"},
    "SnpLineTrt":   {"FirstUser": "SUPERVISOR", "LastUser": "SUPERVISOR",
                     "AlwaysExe": "1", "IndErr": "0", "IndLogFinalCmd": "0"},
    "SnpTxtHeader": {"Enc": "0"},
    "SnpStep":      {"FirstUser": "SUPERVISOR", "LastUser": "SUPERVISOR",
                     "IndLogMethod": "Y", "KoExit": "1", "OkExitCode": "0"},
}

# Fields the builder OWNS. A convention read out of the reference must never
# supply one of these: the reference's IProject/IFolder/IPackage and its
# LastDate are ITS values, not ours, and its IndChange is "U" (an object that
# has been edited) where a newly created object needs "I". SqlIndGrp and OrdTrt
# are excluded because they are derived per statement, not per class.
#
# This list is not a runtime filter -- conventions() only ever looks up the
# fields named in FALLBACK_CONVENTIONS, and the assertion below proves the two
# sets stay disjoint. It is the reason that whitelist may never grow into one
# of these names.
CONVENTION_BLOCKLIST = frozenset({
    "GlobalId", "IndChange", "IntVersion",
    "FirstDate", "LastDate", "VLastDate", "BegVersion", "PrvVersion",
    "IProject", "IFolder", "IPackage", "ITrt", "IVar", "IStep", "ILineTrt",
    "ITxt", "ITxtOrig", "ITxtVarIn", "ITxtTrtTxt", "DefITxt", "ITxtPack",
    "ProjectName", "ProjectCode", "FolderName", "PackName", "TrtName",
    "VarName", "StepName", "StepType", "Txt", "SqlIndGrp", "OrdTrt", "Nno",
    "PosX", "PosY", "OkExit", "OkNextStep", "KoNextStep", "VarOp",
    "OrdFolder", "IState",
})

_OVERLAP = {n for c in FALLBACK_CONVENTIONS.values() for n in c} & CONVENTION_BLOCKLIST
assert not _OVERLAP, (
    f"FALLBACK_CONVENTIONS names a field the builder owns: {sorted(_OVERLAP)}. "
    "Reading it from the reference would copy that repository's id, name or "
    "timestamp into our objects.")
del _OVERLAP


def guid():
    return str(uuid.uuid4())


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.0")


def _utc_offset():
    """This machine's current UTC offset as ODI writes it: ' +0700'."""
    off = datetime.datetime.now().astimezone().strftime("%z")
    return f" {off}" if off else " +0000"


# ---------------------------------------------------------------------------
# Canonical field layouts, captured field-by-field (name + type, in order)
# from a real ODI 14.1.2 SmartExport. Doc._fields() fills values against these;
# any field not supplied is rendered as null. Passing an unknown field name
# raises -- that is deliberate, it catches typos that would otherwise produce
# a silently malformed object.
# ---------------------------------------------------------------------------
CANONICAL = {
"SnpProject": [
    ("BegVersion", T), ("ExtVersion", S), ("FirstDate", T), ("FirstUser", S),
    ("GlobalId", S), ("IndChange", S), ("IntVersion", I), ("IProject", I),
    ("LastDate", T), ("LastUser", S), ("ProjectCode", S), ("ProjectName", S),
    ("PrvVersion", I), ("VLastDate", T),
],
"SnpFolder": [
    ("ExtVersion", S), ("FirstDate", T), ("FirstUser", S), ("FolderName", S),
    ("GlobalId", S), ("IndChange", S), ("IntVersion", I), ("IFolder", I),
    ("IProject", I), ("LastDate", T), ("LastUser", S), ("OrdFolder", I),
    ("ParIFolder", I), ("ReleaseTag", S), ("VLastDate", T),
],
"SnpPackage": [
    ("ExtVersion", S), ("FirstDate", T), ("FirstUser", S), ("GlobalId", S),
    ("IndChange", S), ("IntVersion", I), ("IFolder", I), ("IPackage", I),
    ("IScBasePackage", I), ("IScOrigPackage", I), ("IScPackage", I),
    ("IState", I), ("ITxtPack", I), ("LastDate", T), ("LastUser", S),
    ("OrdFolder", I), ("PackName", S), ("RepGuid", S), ("RepVersion", S),
    ("ScOrigPackageTag", S), ("VLastDate", T),
],
"SnpVar": [
    ("DefDate", T), ("DefN", I), ("DefV", S), ("ExtVersion", S),
    ("FirstDate", T), ("FirstUser", S), ("GlobalId", S), ("IndChange", S),
    ("IndStore", S), ("IntVersion", I), ("IProject", I), ("ITxtVar", I),
    ("ITxtVarIn", I), ("ITxtVarValTxt", I), ("IVar", I), ("LastDate", T),
    ("LastUser", S), ("LschemaName", S), ("VarDatatype", S), ("VarName", S),
    ("VarType", S), ("VLastDate", T),
],
"SnpTrt": [
    ("CleanupOnError", S), ("CompType", S), ("DelegateClass", S),
    ("DelegateScript", S), ("ExpectedAstClass", S), ("ExtVersion", S),
    ("FirstDate", T), ("FirstUser", S), ("GlobalId", S), ("IndChange", S),
    ("IndExcludeExUnitBegin", S), ("IndExcludeExUnitEnd", S),
    ("IndExcludeExUnitMain", S), ("IndExcludeMapBegin", S),
    ("IndExcludeMapCleanup", S), ("IndExcludeMapEnd", S),
    ("IndGenerateLoad", S), ("IndIsHidden", S), ("IndJrnMethod", S),
    ("IndSuppSetBased", S), ("IntgType", S), ("IntVersion", I),
    ("IsConcurrent", S), ("IsSeeded", S), ("IBaseCompKm", I), ("IFolder", I),
    ("IProject", I), ("IScBaseTrt", I), ("IScOrigTrt", I), ("IScTrt", I),
    ("ITrt", I), ("ITxtDelTxt", I), ("ITxtTrtTxt", I), ("KimMultiDserver", S),
    ("KmDefault", S), ("KmLang", S), ("KmSrcLang", S), ("KmSrcTechno", S),
    ("KmTechno", S), ("KmVersion", S), ("LastDate", T), ("LastUser", S),
    ("LkmType", S), ("LChecksum", I), ("LCode", S), ("OggJkm", S),
    ("OrdFolder", I), ("ProcType", S), ("ProdAstType", S), ("RepGuid", S),
    ("RepVersion", S), ("ScriptPath", S), ("ScOrigTrtTag", S), ("Subtype", S),
    ("TrtName", S), ("TrtType", S), ("VariableDefs", S), ("VLastDate", T),
],
"SnpLineTrt": [
    ("AlwaysExe", S), ("BrpId", I), ("ColConnectId", S), ("ColContextCode", S),
    ("ColIndCommit", S), ("ColIsolLevel", S), ("ColITxt", I),
    ("ColLanguage", S), ("ColLschemaName", S), ("ColTechno", S),
    ("DefConnectId", S), ("DefContextCode", S), ("DefIndCommit", S),
    ("DefIsolLevel", S), ("DefITxt", I), ("DefLanguage", S),
    ("DefLschemaName", S), ("DefTechno", S), ("ExeChannel", S),
    ("FirstDate", T), ("FirstUser", S), ("GlobalId", S), ("IndErr", S),
    ("IndLogFinalCmd", S), ("IndLogNb", S), ("ILineTrt", I),
    ("IRefLineTrt", I), ("IRefTrt", I), ("ITrt", I), ("KcmAk", S),
    ("KcmCond", S), ("KcmErrDel", S), ("KcmJoin", S), ("KcmNull", S),
    ("KcmPk", S), ("KimDrvdSel", S), ("KimIdx", S), ("KimJrn", S),
    ("KimJrnPop", S), ("KjmCreate", S), ("KjmDrop", S), ("KjmExtend", S),
    ("KjmInstall", S), ("KjmLock", S), ("KjmPurge", S), ("KjmSetInstall", S),
    ("KjmSetUninstall", S), ("KjmSubscribe", S), ("KjmTableOrder", S),
    ("KjmUninstall", S), ("KjmUnlock", S), ("KjmUnsubscribe", S),
    ("KlmAfterInt", S), ("KlmIdx", S), ("KlmJrn", S), ("LastDate", T),
    ("LastUser", S), ("LineType", S), ("LogLevDet", S), ("MapTaskType", S),
    ("OrdTrt", I), ("SqlName", S), ("SupportedSubtypes", S),
    ("VariableDefs", S),
],
"SnpTxtHeader": [
    ("Enc", S), ("EncKey", S), ("EncKeyVect", S), ("GlobalId", S),
    ("ITxt", I), ("ITxtOrig", I), ("SqlIndGrp", S), ("Txt", S),
],
"SnpOrigTxt": [
    ("GlobalId", S), ("ITxtOrig", I), ("OrigineName", S), ("SnpsCol", S),
    ("SnpsTable", S),
],
"SnpReferencedObject": [
    ("IObject", I), ("ObjectPKasString", S), ("ObjectAKasString", S),
    ("Description", S), ("GlobalId", S),
],
"SnpStep": [
    ("BrpId", I), ("Clean", S), ("ContextCode", S), ("CreateJournal", S),
    ("CreateSubcriber", S), ("DeleteErrors", S), ("DropJournal", S),
    ("DropSubscriber", S), ("ExtendJrn", S), ("ExtVersion", S),
    ("FirstDate", T), ("FirstUser", S), ("GlobalId", S), ("HeightVal", I),
    ("IndChange", S), ("IndLogMethod", S), ("IntVersion", I),
    ("IDeploySpec", I), ("IMapping", I), ("IMod", I), ("IPackage", I),
    ("IPop", I), ("IScMapping", I), ("IScPop", I), ("IScTable", I),
    ("IScTrt", I), ("ISmod", I), ("IStep", I), ("ITable", I), ("ITrt", I),
    ("ITxtAction", I), ("ITxtSubscribers", I), ("ITxtVarValue", I),
    ("IVar", I), ("KoExit", S), ("KoExitCode", S), ("KoNextStep", I),
    ("KoRetry", I), ("KoRetryInterv", I), ("LastDate", T), ("LastUser", S),
    ("LockJrn", S), ("ModCod", S), ("Nno", I), ("OkExit", S),
    ("OkExitCode", S), ("OkNextStep", I), ("PosX", I), ("PosY", I),
    ("PurgeJrn", S), ("RecurseSubmod", S), ("SetInstallJrn", S),
    ("SetUninstallJrn", S), ("SmodCod", S), ("StepName", S), ("StepType", S),
    ("TableName", S), ("UnlockJrn", S), ("VarIncr", I), ("VarOp", S),
    ("WidthVal", I),
],
}


class Seq:
    def __init__(self, start=1):
        self.n = start - 1

    def next(self):
        self.n += 1
        return self.n


# ---------------------------------------------------------------------------
# Reference -- the parsed, real SmartExport exported from the TARGET repository.
# This is the single source of truth for everything repo-specific.
# ---------------------------------------------------------------------------
class Reference:
    def __init__(self, path):
        self.path = path
        self.root = ET.parse(path).getroot()
        self.objects = []          # list of (short_class, [(name, type, value)])
        for node in self.root:
            if node.tag != "Object":
                continue
            cls = node.attrib.get("class", "").replace(PKG, "")
            fields = []
            for f in node:
                if f.tag == "Field":
                    v = f.text
                    if v == "null":
                        v = None
                    fields.append((f.attrib.get("name"), f.attrib.get("type"), v))
            self.objects.append((cls, fields))

    # -- helpers ------------------------------------------------------------
    def of_class(self, cls):
        return [f for c, f in self.objects if c == cls]

    @staticmethod
    def val(fields, name):
        for n, _t, v in fields:
            if n == name:
                return v
        return None

    def counts(self):
        return Counter(c for c, _ in self.objects)

    def field_layout(self, cls):
        """[(name, type)] of the FIRST instance of cls in the reference."""
        objs = self.of_class(cls)
        if not objs:
            return None
        return [(n, t) for n, t, _v in objs[0]]

    # -- topology -----------------------------------------------------------
    def topology_objects(self):
        """Full topology objects, verbatim, in reference file order."""
        out = []
        for cls, fields in self.objects:
            if cls in TOPOLOGY_CLASSES:
                out.append((cls, fields))
        return out

    def topology_descriptors(self):
        """SnpReferencedObject rows that sit in the topology block (before the
        first SnpProject). These describe Pschema/Context/Lschema for the UI."""
        out = []
        for cls, fields in self.objects:
            if cls == "SnpProject":
                break
            if cls == "SnpReferencedObject":
                out.append(fields)
        return out

    def topology_fkxrefs(self):
        """[(refkey, guid, fqname, fqtype, fqlens)] for topology RefKeys."""
        out = []
        for cls, fields in self.objects:
            if cls != "SnpFKXRef":
                continue
            key = self.val(fields, "RefKey") or ""
            if key.startswith(TOPOLOGY_REFKEY_PREFIXES):
                out.append((
                    key,
                    self.val(fields, "RefObjGlobalId"),
                    self.val(fields, "RefObjFQName"),
                    self.val(fields, "RefObjFQType"),
                    self.val(fields, "RefObjFQNameLengths"),
                ))
        return out

    # -- standing reference data -------------------------------------------
    def origtxt_ids(self):
        """{slot: (itxtorig_id, origine_name)} read out of the reference.

        These ids are seeded into the repository itself; inventing them throws
        SnpsInexistantObjectException at import. Always read, never assume.
        """
        found = {}
        for fields in self.of_class("SnpOrigTxt"):
            table = self.val(fields, "SnpsTable")
            col = self.val(fields, "SnpsCol")
            for slot, (t, c) in ORIGTXT_SLOTS.items():
                if table == t and col == c:
                    found[slot] = (int(self.val(fields, "ITxtOrig")),
                                   self.val(fields, "OrigineName"))
        return found

    # -- execution defaults --------------------------------------------------
    # A curated whitelist, read from the FIRST SnpLineTrt so that even a
    # reference with a single command line still supplies real values. Ids,
    # names and text pointers are deliberately absent -- those are ours.
    LINETRT_DEFAULT_FIELDS = (
        "DefContextCode", "DefLschemaName", "DefTechno", "ColTechno",
        "ColContextCode", "ColLschemaName",
        "ExeChannel", "MapTaskType", "LogLevDet", "SqlName",
        "AlwaysExe", "IndErr", "IndLogFinalCmd",
    )

    def linetrt_defaults(self):
        """Execution binding + flags taken from the reference's command lines."""
        rows = self.of_class("SnpLineTrt")
        if not rows:
            return {}
        return {k: self.val(rows[0], k) for k in self.LINETRT_DEFAULT_FIELDS}

    def var_lschema_name(self):
        rows = self.of_class("SnpVar")
        return self.val(rows[0], "LschemaName") if rows else None

    def default_folder_name(self):
        rows = self.of_class("SnpFolder")
        return self.val(rows[0], "FolderName") if rows else None

    def encryption_attrs(self):
        """The reference's own <Encryption> header attributes, or None.

        A real export writes this header even with containsCipherText="false".
        Its algorithm/keyLength/keyVect are repository-side values; copying them
        keeps this builder inside its own rule that nothing repo-specific is
        invented. (An earlier version hardcoded a keyVect taken from a
        completely different export.)
        """
        enc = self.root.find("Encryption")
        return dict(enc.attrib) if enc is not None else None

    # -- conventions ---------------------------------------------------------
    def conventions(self, cls):
        """{field: value} for this class's convention fields, as the target
        repository writes them.

        Only the fields named in FALLBACK_CONVENTIONS are looked up. Sweeping
        every field instead would be worse, not better: a reference holding
        exactly one Procedure would hand back ITS IProject and ITrt as though
        they were rules. CONVENTION_BLOCKLIST names the categories that must
        never be read this way; an assertion at import time keeps that
        whitelist from ever growing into one of them.

        A field that is **null in every instance** yields None, and that is an
        answer, not a gap: the reference's own SnpLineTrt rows leave FirstUser
        null, so ours must too. A value is only reported as missing when the
        class is absent from the reference altogether -- then Doc falls back to
        a built-in literal and validate() says which.
        """
        wanted = FALLBACK_CONVENTIONS.get(cls, {})
        objs = self.of_class(cls)
        if not objs:
            return {}
        out = {}
        for name in wanted:
            vals = {self.val(f, name) for f in objs}
            if len(vals) == 1:
                out[name] = vals.pop()
        return out

    # -- SqlIndGrp -----------------------------------------------------------
    @staticmethod
    def first_keyword(sql):
        """The statement keyword a SQL body opens with, ignoring leading blank
        lines and `--` / block comments: TRUNCATE, INSERT, MERGE, SELECT, ...
        An empty body yields '' (the Procedure editor's unused text slot)."""
        if not sql:
            return ""
        text = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("--"):
                continue
            m = re.match(r"[A-Za-z_]+", line)
            return m.group(0).upper() if m else ""
        return ""

    def sqlindgrp_rules(self):
        """{slot: {first_keyword: {SqlIndGrp value: how many times seen}}}

        SqlIndGrp tracks the KIND of statement, not its position in the
        procedure. In a real export TRUNCATE carries "0" while INSERT and MERGE
        carry "2" -- including an INSERT that is the FIRST command line
        (OrdTrt=10). Deriving the rule from the reference instead of from the
        command order is what lets this work against any repository.

        The counts matter as much as the values. More than one value for a
        keyword means the reference is ambiguous and the caller must choose.
        Exactly one value seen exactly ONCE is not a rule either -- it is a
        single observation, and a thin reference can teach a confident wrong
        answer that way: strip the esim export down to its one long Variable
        query and `SELECT … FROM DUAL` starts deriving "2", where the full
        export shows that shape as "0". The builder still uses it, and says so.
        """
        by_orig = {v[0]: slot for slot, v in self.origtxt_ids().items()}
        rules = {}
        for fields in self.of_class("SnpTxtHeader"):
            orig = self.val(fields, "ITxtOrig")
            slot = by_orig.get(int(orig)) if orig is not None else None
            grp = self.val(fields, "SqlIndGrp")
            if slot is None or grp is None:
                continue
            kw = self.first_keyword(self.val(fields, "Txt"))
            counts = rules.setdefault(slot, {}).setdefault(kw, {})
            counts[grp] = counts.get(grp, 0) + 1
        return rules

    def required_fields(self, cls, min_instances=2):
        """Field names that are non-null in EVERY instance of cls in the
        reference -- i.e. almost certainly NOT NULL columns in the repository.

        Credit: the distinction between "this field's value varies between
        instances" and "this field may be null" comes from a parallel
        migration effort on the same repository, which hit
        ORA-01400 ("cannot insert NULL into SNP_GRP_STATE.GRP_ORDER_DISP")
        by defaulting every varying field to null. Deriving the set from the
        reference at build time beats a hardcoded list: it adapts to whatever
        ODI version and repository this particular reference came from.

        Classes with fewer than `min_instances` samples are skipped entirely:
        with a single instance every non-null field looks required, including
        GlobalId and ProjectName, which would make the check meaningless.
        """
        objs = self.of_class(cls)
        if len(objs) < min_instances:
            return set()
        names = [n for n, _t, _v in objs[0]]
        return {n for n in names
                if all(self.val(f, n) is not None for f in objs)}

    def seed_state_objects(self):
        """The project's default marker/state metadata (Priorities / Progress /
        Smileys). ODI Studio creates these for every project and their
        repository columns are NOT NULL -- they are copied verbatim, never
        invented. Returns [(cls, fields)] in reference order."""
        # K6 (SS_PAYMENT_3BB_VDO 2026-10-15): a reference that holds TWO projects carries two
        # sets of Priorities/Progress/Smileys -> copying both into one project gave
        # ODI-17591 'Name "Priorities" is already used' on Smart Import. Keep ONE project's set.
        grps = [(c, f) for c, f in self.objects if c == "SnpGrpState"]
        if not grps:
            return []
        proj = self.val(grps[0][1], "IProject")
        keep = {self.val(f, "IGrpState") for c, f in grps if self.val(f, "IProject") == proj}
        return [(c, f) for c, f in self.objects
                if (c == "SnpGrpState" and self.val(f, "IProject") == proj)
                or (c == "SnpState2" and self.val(f, "IGrpState") in keep)]

    def verify_layouts(self):
        """Compare this module's CANONICAL layouts against the reference.
        Returns a list of human-readable warnings (empty == identical)."""
        warnings = []
        for cls, canon in CANONICAL.items():
            actual = self.field_layout(cls)
            if actual is None:
                warnings.append(f"{cls}: not present in reference (cannot verify)")
                continue
            canon_map = OrderedDict(canon)
            act_map = OrderedDict(actual)
            missing = [k for k in act_map if k not in canon_map]
            extra = [k for k in canon_map if k not in act_map]
            typediff = [f"{k}({canon_map[k]} != {act_map[k]})"
                        for k in canon_map if k in act_map and canon_map[k] != act_map[k]]
            if missing:
                warnings.append(f"{cls}: reference has fields this builder omits: {missing}")
            if extra:
                warnings.append(f"{cls}: builder has fields the reference lacks: {extra}")
            if typediff:
                warnings.append(f"{cls}: type mismatches: {typediff}")
        return warnings


# ---------------------------------------------------------------------------
# Doc -- the document being built
# ---------------------------------------------------------------------------
class Doc:
    def __init__(self, reference, project_name, project_code,
                 folder_name=None, package_name=None,
                 iproject=1, ifolder=1, ipackage=1):
        self.ref = reference
        self.project_name = project_name
        # ProjectCode is not a label: ODI substitutes #<CODE>.<VAR> at run time,
        # so a dot or a space inside it makes every bind reference unparseable.
        # The rule was written down in the intake questions long before anything
        # enforced it.
        bad = [c for c in project_code if c == "." or c.isspace()]
        if not project_code or bad:
            raise ValueError(
                f"ProjectCode {project_code!r} cannot be used: a code must be "
                "non-empty and contain no dot and no whitespace, because it is "
                "the prefix of the bind-variable syntax #CODE.VARIABLE that ODI "
                "resolves at run time. Use e.g. AI_TEST_01.")
        self.project_code = project_code
        self._code_warnings = []
        if project_code != project_code.upper():
            self._code_warnings.append(
                f"ProjectCode {project_code!r} is not upper case. Every code in "
                "the reference is, and #code.VAR reads as a typo to anyone "
                "maintaining the SQL later.")
        self.folder_name = (folder_name or reference.default_folder_name()
                            or "First Folder")
        self.package_name = package_name or project_name
        self.iproject = iproject
        self.ifolder = ifolder
        self.ipackage = ipackage

        self.objects = []      # [(cls, [(name, type, value)])]
        self.fkxrefs = []      # [(refkey, guid, fqname, fqtype, fqlens)]
        self._seen_refkeys = set()
        self._fq_parts = {}    # refkey -> [segment, ...] for rows we built

        self.seq_var = Seq()
        self.seq_trt = Seq()
        self.seq_step = Seq()
        self.seq_linetrt = Seq()
        self.seq_txt = Seq()

        self.vars = {}         # name -> ivar
        self.trts = {}         # name -> itrt
        self.steps = []        # [(istep, name, type, ref, ok_next)]

        self._origtxt = self.ref.origtxt_ids()
        missing = [s for s in ORIGTXT_SLOTS if s not in self._origtxt]
        if missing:
            raise ValueError(
                "Reference does not contain SnpOrigTxt rows for slots %s. "
                "Export a reference that includes a Procedure AND a Variable, "
                "otherwise these repository-seeded ids cannot be read and MUST "
                "NOT be guessed (see appendix/C-failure-catalog.md)." % missing)
        self._emitted_origtxt = set()
        # Fields the reference never leaves null -> treat as NOT NULL columns.
        self._required = {cls: self.ref.required_fields(cls) for cls in CANONICAL}
        # Per-class conventions read from the target repository's own export.
        self._conventions = {cls: self.ref.conventions(cls) for cls in CANONICAL}
        self._convention_fallbacks = {}          # (cls, field) -> literal used
        self._sqlgrp_rules = self.ref.sqlindgrp_rules()
        self._weak_sqlgrp = {}                   # (slot, keyword) -> value
        self._defaults = self.ref.linetrt_defaults()
        self._lschema_for_vars = self.ref.var_lschema_name()
        self.now = _now()
        # Fixed once per document so validate() and write_zip() render exactly
        # the same bytes -- otherwise the file that was checked is not the file
        # that was written, and two builds from one spec differ.
        self._export_salt = guid()
        self._created = (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                         + _utc_offset())

    # -- low level ----------------------------------------------------------
    def _resolve(self, cls, values):
        """Caller's value wins; otherwise the target repository's own
        convention for that field; otherwise a built-in literal, recorded so
        validate() can report that the reference could not decide it."""
        conv = self._conventions.get(cls, {})
        fallback = FALLBACK_CONVENTIONS.get(cls, {})
        out = {}
        for name, _typ in CANONICAL[cls]:
            if values.get(name) is not None:
                out[name] = values[name]
            elif name in conv:
                out[name] = conv[name]        # may be None -- an explicit null
            elif name in fallback:
                out[name] = fallback[name]
                self._convention_fallbacks[(cls, name)] = fallback[name]
            else:
                out[name] = None
        return out

    def _fields(self, cls, **values):
        layout = CANONICAL[cls]
        known = {n for n, _ in layout}
        unknown = set(values) - known
        if unknown:
            raise KeyError(f"{cls}: unknown field(s) {sorted(unknown)}")
        values = self._resolve(cls, values)
        missing = sorted(n for n in self._required.get(cls, ())
                         if values.get(n) is None)
        if missing:
            raise ValueError(
                f"{cls}: field(s) {missing} are never null in the reference "
                "export, so the repository columns behind them are very likely "
                "NOT NULL. Refusing to emit null -- supply a value, or prove "
                "from a reference that the field is nullable. (Emitting null "
                "here is what produces ORA-01400 halfway through someone's "
                "import.)")
        out = []
        for name, typ in layout:
            v = values.get(name)
            out.append((name, typ, None if v is None else str(v)))
        return out

    def add(self, cls, **values):
        self.objects.append((cls, self._fields(cls, **values)))

    def add_raw(self, cls, fields):
        """Append an object verbatim (used for cloned topology)."""
        self.objects.append((cls, fields))

    def fkxref(self, refkey, guid_, fqname=None, fqtype=None, fqlens=None,
               parts=None):
        """Register a cross-reference row.

        Pass `parts` (the fully-qualified name as a LIST of segments) rather
        than a pre-joined string wherever the segments are known. ODI does not
        split RefObjFQName on '.' -- it uses RefObjFQNameLengths, the character
        length of each segment, e.g.

            esim.First Folder.esim.020000_overwrite_...   ->  4.12.4.40

        so a segment that itself contains a dot is representable, but only if
        the lengths come from the real segment list. Deriving them by splitting
        the joined string silently produces a wrong segment count.
        """
        if refkey in self._seen_refkeys:
            return
        self._seen_refkeys.add(refkey)
        if parts is not None:
            parts = [str(p) for p in parts]
            fqname = ".".join(parts)
            fqlens = ".".join(str(len(p)) for p in parts)
            self._fq_parts[refkey] = parts
        self.fkxrefs.append((refkey, guid_, fqname, fqtype, fqlens))

    # -- topology -----------------------------------------------------------
    def clone_topology(self):
        """Embed the reference's topology objects VERBATIM plus their FKXRefs.

        Full objects, not FKXRef-only: an FKXRef with no object in the file
        produces ODI-10113 "Logical Schema ... Broken Link" on every dependent
        Procedure/Variable when the target repo does not already hold that
        GlobalId. Embedding the full object is what the real Studio export
        does, and it both matches an existing object and creates a missing one.
        """
        for cls, fields in self.ref.topology_objects():
            self.add_raw(cls, fields)
        for fields in self.ref.topology_descriptors():
            self.add_raw("SnpReferencedObject", fields)
        for row in self.ref.topology_fkxrefs():
            self.fkxref(*row)

    # -- project / folder / package -----------------------------------------
    def add_project(self):
        pg, fg, kg = guid(), guid(), guid()
        self.add("SnpProject", FirstDate=self.now,
                 GlobalId=pg, IndChange="I", IntVersion=1,
                 IProject=self.iproject, LastDate=self.now,
                 ProjectCode=self.project_code, ProjectName=self.project_name)
        self.fkxref(f"SNP_PROJECT.{self.iproject}", pg, fqtype="SNP_PROJECT",
                    parts=[self.project_name])

        self.add("SnpFolder", FirstDate=self.now,
                 FolderName=self.folder_name, GlobalId=fg, IndChange="I",
                 IntVersion=1, IFolder=self.ifolder, IProject=self.iproject,
                 LastDate=self.now)
        self.fkxref(f"SNP_FOLDER.{self.ifolder}", fg,
                    fqtype="SNP_PROJECT.SNP_FOLDER",
                    parts=[self.project_name, self.folder_name])

        self.add("SnpPackage", FirstDate=self.now,
                 GlobalId=kg, IndChange="I", IntVersion=1, IFolder=self.ifolder,
                 IPackage=self.ipackage, LastDate=self.now,
                 PackName=self.package_name)
        self.fkxref(f"SNP_PACKAGE.{self.ipackage}", kg,
                    fqtype="SNP_PROJECT.SNP_FOLDER.SNP_PACKAGE",
                    parts=[self.project_name, self.folder_name, self.package_name])

    def clone_seed_states(self):
        """Copy the project's default state groups (Priorities / Progress /
        Smileys: 3 SnpGrpState + 18 SnpState2) from the reference.

        These belong to the NEW project, unlike topology, so each gets a FRESH
        GlobalId and our IProject -- only the values are copied. Copying rather
        than authoring matters: fields like GrpOrderDisp, TreeDisplay,
        IndAutoIncrement and per-state IconRes ('/markers/taskprior_1.gif') are
        NOT NULL in the repository and none of them are guessable. A parallel
        effort that hand-wrote this block from memory got ORA-01400 on import.

        SnpState2 rows are deliberately NOT given SnpFKXRef entries -- the real
        export does not index them (only SnpGrpState is).
        """
        for cls, fields in self.ref.seed_state_objects():
            g = guid()
            new = []
            for n, t, v in fields:
                if n == "GlobalId":
                    v = g
                elif n == "IProject":
                    v = str(self.iproject)
                new.append((n, t, v))
            self.add_raw(cls, new)
            if cls == "SnpGrpState":
                self.fkxref(
                    f"SNP_GRPSTATE.{Reference.val(fields, 'IGrpState')}", g,
                    fqtype="SNP_PROJECT.SNP_GRPSTATE",
                    parts=[self.project_name,
                           Reference.val(fields, 'GrpStateName')])

    # -- shared SnpOrigTxt ---------------------------------------------------
    def _origtxt_once(self, slot):
        itxtorig, origine = self._origtxt[slot]
        if slot in self._emitted_origtxt:
            return itxtorig
        self._emitted_origtxt.add(slot)
        table, col = ORIGTXT_SLOTS[slot]
        self.add("SnpOrigTxt", ITxtOrig=itxtorig, OrigineName=origine,
                 SnpsCol=col, SnpsTable=table)
        self.fkxref(f"SNP_ORIGTXT.{itxtorig}", None)
        return itxtorig

    def _txt_header(self, itxtorig, txt, sql_ind_grp, itxt=None):
        itxt = self.seq_txt.next() if itxt is None else itxt
        g = guid()
        self.add("SnpTxtHeader", GlobalId=g, ITxt=itxt,
                 ITxtOrig=itxtorig, SqlIndGrp=sql_ind_grp, Txt=txt)
        self.fkxref(f"SNP_TXTHEADER.{itxt}", g)
        return itxt

    def sql_ind_grp_for(self, slot, sql, explicit=None):
        """SqlIndGrp for one SQL body, learned from the reference.

        The value tracks the statement KIND, not the command order: a real
        export carries "0" on TRUNCATE and "2" on INSERT/MERGE, including an
        INSERT that is the first command line. Deriving it from `OrdTrt` (an
        earlier version did) puts "0" on a large INSERT the moment a procedure
        has a single append line -- a combination that appears nowhere in a real
        export, on the very field whose wrong value once produced a
        NullPointerException at import.
        """
        if explicit is not None:
            return explicit
        kw = Reference.first_keyword(sql)
        observed = self._sqlgrp_rules.get(slot, {}).get(kw)
        if observed and len(observed) == 1:
            value, seen = next(iter(observed.items()))
            if seen < 2:
                # One observation is not a rule. Still used -- refusing here
                # would block every thin reference -- but never silently.
                self._weak_sqlgrp[(slot, kw)] = value
            return value
        known = {k or "(empty)": {g: n for g, n in sorted(v.items())}
                 for k, v in self._sqlgrp_rules.get(slot, {}).items()}
        raise ValueError(
            f"cannot derive SqlIndGrp for a {kw or '(empty)'} statement in slot "
            f"{slot!r}. The reference shows {known or 'no example at all'} "
            "(value: times seen), which is "
            + ("ambiguous" if observed else "no guidance") + " here. "
            "Pass sql_ind_grp explicitly, or use a reference that contains a "
            f"{kw or 'matching'} statement in that slot -- this value is never "
            "guessed.")

    def _descriptor(self, kind):
        """Re-emit the reference's descriptor row for its Context or Logical
        Schema next to a LineTrt/Var, exactly as the real export does.

        Matched by GlobalId, not by the IObject type code: a SnpReferencedObject
        carries the SAME GlobalId as the object it describes (verified across
        every such row in a real export), so this needs no magic numbers and
        works whatever type ids a given ODI build uses.

        That shared GlobalId identifies what the row DESCRIBES, not what it
        belongs to -- this class carries no owner reference at all. Position is
        the only visible link to the SnpVar/SnpLineTrt it accompanies, so these
        rows are emitted immediately after their owner, exactly as the reference
        lays them out. Inferred from the file's shape, not proven; see
        appendix/A-odi-object-reference.md.
        """
        cls = {"context": "SnpContext", "lschema": "SnpLschema"}[kind]
        rows = self.ref.of_class(cls)
        if not rows:
            raise ValueError(
                f"reference contains no {cls} -- it is not a Smart Export "
                "(see appendix/A-odi-object-reference.md)")
        want = Reference.val(rows[0], "GlobalId")
        for fields in self.ref.topology_descriptors():
            if Reference.val(fields, "GlobalId") == want:
                self.add_raw("SnpReferencedObject", fields)
                return
        raise ValueError(
            f"reference has no SnpReferencedObject describing its {cls} "
            f"(GlobalId {want}). Export a Smart Export of a Package that "
            "actually uses that schema.")

    # -- variables ----------------------------------------------------------
    def add_variable(self, name, sql, sql_ind_grp=None):
        """IndStore / VarDatatype / VarType and the owning user come from the
        target repository's own convention (Reference.conventions); only the
        identity, the schema and the refresh query are ours."""
        if name in self.vars:
            raise ValueError(
                f"a Variable named {name!r} was already added. Two Variables "
                "cannot share a name inside one project -- Studio does not "
                "allow it, and here the second would silently take over every "
                "step and bind reference aimed at the first.")
        grp = self.sql_ind_grp_for("var_query", sql, sql_ind_grp)
        ivar = self.seq_var.next()
        g = guid()
        itxtorig = self._origtxt_once("var_query")
        itxt = self.seq_txt.next()   # the variable's refresh-query text

        self.add("SnpVar", FirstDate=self.now,
                 GlobalId=g, IndChange="I", IntVersion=1,
                 IProject=self.iproject, ITxtVarIn=itxt,
                 IVar=ivar, LastDate=self.now,
                 LschemaName=self._lschema_for_vars, VarName=name)
        self._descriptor("lschema")
        self._txt_header(itxtorig, sql, grp, itxt=itxt)
        self.fkxref(f"SNP_VAR.{ivar}", g, fqtype="SNP_PROJECT.SNP_VAR",
                    parts=[self.project_name, name])
        self.vars[name] = ivar
        return ivar

    # -- procedures ---------------------------------------------------------
    def add_procedure(self, name, lines):
        """lines: [(ord_trt, sql_ind_grp, sql_text)].

        `ord_trt` is the command line's POSITION in the procedure, not a marker
        of what the statement does: a real export numbers the first line 10, the
        second 20, whether that first line is a TRUNCATE or an INSERT. Pass None
        to have it assigned by position.

        `sql_ind_grp` may also be None -- it is then derived from the statement
        kind using the reference's own examples (sql_ind_grp_for).
        """
        if name in self.trts:
            raise ValueError(
                f"a Procedure named {name!r} was already added. Two Procedures "
                "cannot share a name inside one folder -- Studio does not allow "
                "it, and here both objects would be written out while every "
                "step aimed at that name bound to the second, leaving the first "
                "unreachable.")
        prepared = []
        for idx, (ord_trt, grp, sql_text) in enumerate(lines):
            prepared.append((int(ord_trt) if ord_trt is not None else (idx + 1) * 10,
                             grp, sql_text))
        prepared.sort(key=lambda t: t[0])
        dupe = [o for o, _g, _s in prepared if [x[0] for x in prepared].count(o) > 1]
        if dupe:
            raise ValueError(f"procedure {name!r}: duplicate OrdTrt {sorted(set(dupe))} "
                             "-- each command line needs its own position")
        # Resolve every SqlIndGrp before emitting anything, so an underivable
        # one fails the build instead of leaving a half-written procedure.
        prepared = [(o, self.sql_ind_grp_for("linetrt_sql", s, g), s)
                    for o, g, s in prepared]

        itrt = self.seq_trt.next()
        g = guid()
        placeholder_orig = self._origtxt_once("trt_edit_cmd")
        placeholder_itxt = self._txt_header(
            placeholder_orig, None,
            self.sql_ind_grp_for("trt_edit_cmd", None))

        self.add("SnpTrt", FirstDate=self.now,
                 GlobalId=g, IndChange="I", IntVersion=1,
                 IFolder=self.ifolder, IProject=self.iproject,
                 ITrt=itrt, ITxtTrtTxt=placeholder_itxt,
                 KmSrcTechno=self._defaults.get("DefTechno"),
                 KmTechno=self._defaults.get("DefTechno"),
                 LastDate=self.now, TrtName=name)
        self.fkxref(f"SNP_TRT.{itrt}", g, fqtype="SNP_PROJECT.SNP_TRT",
                    parts=[self.project_name, name])

        body_orig = self._origtxt_once("linetrt_sql")
        for ord_trt, sql_ind_grp, sql_text in prepared:
            body_itxt = self.seq_txt.next()   # this command line's SQL text
            ilinetrt = self.seq_linetrt.next()
            lg = guid()
            self.add("SnpLineTrt",
                     AlwaysExe=self._defaults.get("AlwaysExe"),
                     IndErr=self._defaults.get("IndErr"),
                     IndLogFinalCmd=self._defaults.get("IndLogFinalCmd"),
                     ColTechno=self._defaults.get("ColTechno"),
                     ColContextCode=self._defaults.get("ColContextCode"),
                     ColLschemaName=self._defaults.get("ColLschemaName"),
                     DefContextCode=self._defaults.get("DefContextCode"),
                     DefITxt=body_itxt,
                     DefLschemaName=self._defaults.get("DefLschemaName"),
                     DefTechno=self._defaults.get("DefTechno"),
                     ExeChannel=self._defaults.get("ExeChannel"),
                     GlobalId=lg,
                     ILineTrt=ilinetrt, ITrt=itrt, LastDate=self.now,
                     LogLevDet=self._defaults.get("LogLevDet"),
                     MapTaskType=self._defaults.get("MapTaskType"),
                     OrdTrt=ord_trt,
                     SqlName=self._defaults.get("SqlName"))
            self._descriptor("context")
            self._descriptor("lschema")
            self._txt_header(body_orig, sql_text, sql_ind_grp, itxt=body_itxt)

        self.trts[name] = itrt
        return itrt

    # -- steps --------------------------------------------------------------
    @staticmethod
    def ok_exit(ok_next):
        """CONFIRMED against a real Studio-wired package: OkExit='0' on every
        step that continues, '1' ONLY on the terminal step. Hardcoding '1'
        everywhere makes Studio draw a package with no connecting arrows."""
        return "1" if ok_next is None else "0"

    def add_steps(self, plan, per_row=5, x0=70, dx=140, y0=100, dy=110):
        """plan: [{name, type: 'V'|'T', ref: <var or procedure name>,
                   pos: (x, y)}] in execution order.

        Call once: an ODI Package holds a single OkNextStep chain, so a second
        call would start a second, unreachable chain (and restart Nno).
        Steps without an explicit `pos` are laid out in rows of `per_row`,
        mirroring how the reference package wraps rather than running off to
        the right in one line.
        """
        if self.steps:
            raise ValueError(
                "add_steps() called twice. A Package has one step chain -- "
                "pass every step in a single call, in execution order.")
        if not plan:
            raise ValueError(
                "add_steps() was given an empty plan. A Package with no steps "
                "imports successfully and then does nothing -- if that is "
                "really what you want, do not call add_steps() at all and the "
                "validator will say so.")
        for item in plan:
            kind = "procedure" if item.get("type") == "T" else "variable"
            known = self.trts if item.get("type") == "T" else self.vars
            if item.get("ref") not in known:
                raise KeyError(
                    f"step {item.get('name')!r} references {kind} "
                    f"{item.get('ref')!r}, which was never added. Known "
                    f"{kind}s: {sorted(known)}")
        isteps = [self.seq_step.next() for _ in plan]
        for idx, item in enumerate(plan):
            ok_next = isteps[idx + 1] if idx + 1 < len(isteps) else None
            g = guid()
            steptype = item["type"]
            refname = item["ref"]
            if steptype == "T":
                itrt, ivar, varop = self.trts[refname], None, None
            elif steptype == "V":
                itrt, ivar, varop = None, self.vars[refname], "="
            else:
                raise ValueError(f"unsupported StepType {steptype!r} -- this "
                                 "builder covers 'T' (procedure) and 'V' "
                                 "(variable) only; anything else needs a real "
                                 "reference example first")
            x, y = item.get("pos",
                            (x0 + dx * (idx % per_row), y0 + dy * (idx // per_row)))
            self.add("SnpStep", FirstDate=self.now,
                     GlobalId=g, IndChange="I", IntVersion=1,
                     IPackage=self.ipackage, IStep=isteps[idx], ITrt=itrt,
                     IVar=ivar, LastDate=self.now, Nno=idx,
                     OkExit=self.ok_exit(ok_next),
                     OkNextStep=ok_next, PosX=x, PosY=y,
                     StepName=item["name"], StepType=steptype, VarOp=varop)
            self.fkxref(f"SNP_STEP.{isteps[idx]}", g,
                        fqtype="SNP_PROJECT.SNP_FOLDER.SNP_PACKAGE.SNP_STEP",
                        parts=[self.project_name, self.folder_name,
                               self.package_name, item["name"]])
            self.steps.append((isteps[idx], item["name"], steptype,
                               refname, ok_next))

    # -- render -------------------------------------------------------------
    def render(self):
        def field(name, typ, value):
            if value is None:
                return f'\t<Field name="{name}" type="{typ}">null</Field>'
            return f'\t<Field name="{name}" type="{typ}"><![CDATA[{value}]]></Field>'

        doc = ['<?xml version="1.0" encoding="ISO-8859-1"?>', "<SunopsisExport>"]
        # <Admin> carries the target repository's version and ids, and must
        # match how the file will be imported -- always copied, never written
        # by hand. Only Created is ours.
        admin = self.ref.root.find("Admin")
        if admin is None:
            raise ValueError(
                "reference has no <Admin> header -- it is not an ODI export. "
                "Its RepositoryVersion/OdiVersion/OriginWorkRepositoryID "
                "identify the target repository and cannot be invented.")
        a = dict(admin.attrib)
        a["Created"] = self._created
        doc.append("<Admin " + " ".join(f'{k}="{v}"' for k, v in a.items()) + " />")

        # <Encryption> likewise comes from the reference (algorithm, keyLength
        # and keyVect are repository-side); only the per-export salt is fresh,
        # and it is fixed for this document so two renders agree byte for byte.
        enc = self.ref.encryption_attrs()
        if enc is None:
            raise ValueError(
                "reference has no <Encryption> header -- every real ODI export "
                "writes one, even with containsCipherText=\"false\". Use a "
                "genuine Smart Export as the reference.")
        enc = dict(enc)
        enc["exportKeySalt"] = self._export_salt
        doc.append("<Encryption "
                   + " ".join(f'{k}="{v}"' for k, v in enc.items()) + "/>")
        doc.append('<SmartExportList materializeShortcut="false">')
        doc.append("</SmartExportList>")

        for cls, fields in self.objects:
            doc.append(f'<Object class="{PKG}{cls}">')
            doc += [field(n, t, v) for n, t, v in fields]
            doc.append("</Object>")

        for refkey, g, fqname, fqtype, fqlens in self.fkxrefs:
            doc.append(f'<Object class="{PKG}SnpFKXRef">')
            doc.append(field("RefKey", S, refkey))
            doc.append(field("RefObjGlobalId", S, g))
            if fqname is not None:
                if fqlens is None:
                    # Deriving the lengths by splitting the joined name is the
                    # bug in gotcha #12: the lengths array IS the separator, so
                    # a segment containing a dot would be mis-split. There is no
                    # safe fallback -- the caller must pass `parts`.
                    raise ValueError(
                        f"{refkey}: RefObjFQName was given without "
                        "RefObjFQNameLengths. Build the row with "
                        "fkxref(parts=[...]) so the lengths come from the real "
                        "segment list.")
                lens = fqlens
                doc.append(field("RefObjFQName", S, fqname))
                doc.append(field("RefObjFQType", S, fqtype))
                doc.append(field("RefObjFQNameLengths", S, lens))
            else:
                doc.append(field("RefObjFQName", S, None))
                doc.append(field("RefObjFQType", S, None))
                doc.append(field("RefObjFQNameLengths", S, None))
            doc.append("</Object>")

        doc.append("</SunopsisExport>")
        return "\n".join(doc)

    # -- encoding -----------------------------------------------------------
    def unencodable_text(self):
        """[(class, field, offending characters)] for any value this file's
        declared encoding cannot represent.

        A real ODI export declares ISO-8859-1 and, in both files inspected, is
        pure ASCII -- there is no observed example of how ODI writes a
        character outside that set. Escaping it as &#NNNN; is NOT a safe
        fallback here: every value lives inside a CDATA section, and character
        references are not interpreted inside CDATA, so the SQL would end up
        containing the literal text '&#3605;' instead of the character. That is
        harmless in a comment and wrong in a string literal.
        """
        bad = []
        for cls, fields in self.objects:
            for name, _t, v in fields:
                if v is None:
                    continue
                try:
                    v.encode(FILE_ENCODING)
                except UnicodeEncodeError:
                    chars = sorted({c for c in v
                                    if not self._encodable(c)})
                    bad.append((cls, name, "".join(chars)))
        return bad

    @staticmethod
    def _encodable(ch):
        try:
            ch.encode(FILE_ENCODING)
            return True
        except UnicodeEncodeError:
            return False

    # -- validate -----------------------------------------------------------
    def validate(self, forbid_prefixes=()):
        """Returns {'errors': [...], 'fatal': [...], 'warnings': [...],
        'summary': {...}}. Run this BEFORE handing the zip over; every check
        here corresponds to a real defect that reached a user at least once.

        'fatal' is the subset of errors that no override may bypass -- they
        mean the document itself is wrong (no steps, missing topology, a stray
        ITxtOrig, a dangling text pointer, malformed XML, text the declared
        encoding cannot carry). 'errors' minus 'fatal' is the bind-prefix scan,
        the one check a human can reasonably overrule."""
        errors, warnings = [], []
        # Errors a human may knowingly override. Only the bind-prefix scan
        # qualifies: it is a text search, so SQL that legitimately contains
        # '#WORD.' in a string literal can trip it. Everything else here means
        # the file is structurally wrong -- no override, at any flag.
        overridable = []
        xml_text = self.render()

        # 1. well-formed. Parsed as text with the prolog removed: encoding the
        #    document here with xmlcharrefreplace (an earlier version did) would
        #    check a document that differs from the one write_zip() refuses to
        #    produce, and would hide exactly the characters check 5b reports.
        try:
            ET.fromstring(xml_text.split("\n", 1)[1])
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"XML is not well-formed: {exc}")

        # 2. CDATA balance (a literal ']]>' inside SQL silently corrupts the file)
        if xml_text.count("<![CDATA[") != xml_text.count("]]>"):
            errors.append("CDATA open/close counts differ -- some SQL body "
                          "probably contains a literal ']]>'")

        # 3. duplicate FKXRef RefKeys
        keys = [k for k, *_ in self.fkxrefs]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            errors.append(f"duplicate FKXRef RefKeys: {dupes}")

        # 4. step chain integrity
        known = {s[0] for s in self.steps}
        for istep, name, _t, _r, ok_next in self.steps:
            if ok_next is not None and ok_next not in known:
                errors.append(f"step {name}: OkNextStep={ok_next} does not exist")
        if not self.steps:
            errors.append(
                "the package has no steps -- it would import cleanly and then "
                "do nothing. Call add_steps() with the flattened execution "
                "order.")
        terminals = [s for s in self.steps if s[4] is None]
        if len(terminals) != 1 and self.steps:
            errors.append(f"expected exactly 1 terminal step, found {len(terminals)}")

        # 5. bind-variable prefixes that are not this project's
        #    ODI resolves #<PROJECT_CODE>.<VAR> against the project and
        #    #GLOBAL.<VAR> against the global namespace; anything else names a
        #    project that will not exist here, and resolves to nothing at run
        #    time rather than failing at import. Scanned always, not only when
        #    the caller remembers to pass forbid_prefixes.
        seen_prefixes = set(re.findall(r"#([A-Za-z][A-Za-z0-9_]*)\s*\.", xml_text))
        stray = sorted(seen_prefixes - {self.project_code, GLOBAL_VAR_PREFIX})
        for pfx in stray:
            msg = (f"SQL still references bind variables as #{pfx}. -- this "
                   f"project's code is {self.project_code}. Rename them "
                   f"(rename_bind_prefix_from) or the variables resolve to "
                   "nothing at run time.")
            if pfx.isupper():
                errors.append(msg)
                overridable.append(msg)
            else:
                warnings.append(msg)
        for prefix in forbid_prefixes:
            if prefix in xml_text:
                msg = (f"source bind-variable prefix {prefix!r} still present "
                       "-- rename it to the new project code")
                errors.append(msg)
                overridable.append(msg)

        # 5a. ...and the NAME after the prefix must be a Variable we declared.
        #     Checking only the prefix leaves a typo -- #AI_TEST_01.V_SUCESS --
        #     importing cleanly and resolving to nothing at run time, which is
        #     the exact failure mode this package exists to prevent.
        #     The reverse direction is NOT checked: control variables such as
        #     V_RUNNING drive Package steps and legitimately appear in no SQL.
        referenced = set(re.findall(
            r"#" + re.escape(self.project_code) + r"\.([A-Za-z_][A-Za-z0-9_]*)",
            xml_text))
        for missing in sorted(referenced - set(self.vars)):
            msg = (f"SQL references #{self.project_code}.{missing} but no "
                   f"Variable named {missing!r} is declared in this project "
                   f"(declared: {sorted(self.vars) or 'none'}). It imports "
                   "cleanly and resolves to nothing at run time.")
            errors.append(msg)
            overridable.append(msg)

        # 5b. text the declared file encoding cannot represent
        for cls, field, chars in self.unencodable_text():
            errors.append(
                f"{cls}.{field} contains character(s) {chars!r} that "
                f"{FILE_ENCODING} cannot represent. A real ODI export is "
                "ASCII and gives no example of how it escapes these, and a "
                "&#NNNN; escape is NOT interpreted inside CDATA -- the SQL "
                "would carry the literal escape text. Keep SQL (comments "
                "included) within ISO-8859-1, or verify against a real export "
                "that contains such a character before allowing it.")

        # 5c. a dot inside an FQName segment is representable but untested
        for refkey, parts in self._fq_parts.items():
            dotted = [p for p in parts if "." in p]
            if dotted:
                warnings.append(
                    f"{refkey}: name segment(s) {dotted} contain '.'. "
                    "RefObjFQNameLengths is computed from the real segments so "
                    "this is representable, but no real export shows an object "
                    "named with a dot -- prefer names without one.")

        # 6. ITxtOrig ids must be the reference's, never invented
        ref_ids = {v[0] for v in self._origtxt.values()}
        used = {int(v) for cls, fields in self.objects if cls == "SnpTxtHeader"
                for n, _t, v in fields if n == "ITxtOrig" and v is not None}
        stray = used - ref_ids
        if stray:
            errors.append(f"SnpTxtHeader uses ITxtOrig ids not present in the "
                          f"reference: {sorted(stray)} (throws "
                          "SnpsInexistantObjectException at import)")

        # 7. topology must be embedded, not FKXRef-only
        cls_counts = Counter(c for c, _ in self.objects)
        for cls in ("SnpConnect", "SnpContext", "SnpLschema", "SnpPschema"):
            if cls_counts.get(cls, 0) == 0:
                errors.append(f"{cls} object missing -- FKXRef-only topology "
                              "causes ODI-10113 Broken Link")

        # 7b. every ITxt pointer resolves to a SnpTxtHeader in THIS document
        #     A dangling pointer is the same family of failure as gotcha #3:
        #     import looks the text up and dies when it is not there.
        txt_ids = {v for cls, fields in self.objects if cls == "SnpTxtHeader"
                   for n, _t, v in fields if n == "ITxt" and v is not None}
        pointers = {"SnpVar": "ITxtVarIn", "SnpTrt": "ITxtTrtTxt",
                    "SnpLineTrt": "DefITxt"}
        for cls, fields in self.objects:
            field_name = pointers.get(cls)
            if not field_name:
                continue
            vals = dict((n, v) for n, _t, v in fields)
            target = vals.get(field_name)
            if target is not None and target not in txt_ids:
                errors.append(
                    f"{cls}.{field_name}={target} points at a SnpTxtHeader "
                    "that this document does not contain -- import resolves "
                    "it and fails.")
        dupes_txt = [v for v in txt_ids
                     if sum(1 for cls, fields in self.objects
                            if cls == "SnpTxtHeader"
                            for n, _t, x in fields
                            if n == "ITxt" and x == v) > 1]
        if dupes_txt:
            errors.append(f"duplicate SnpTxtHeader ITxt ids: {sorted(dupes_txt)}")

        # 8. project state metadata present when the reference has it
        if self.ref.seed_state_objects() and cls_counts.get("SnpGrpState", 0) == 0:
            warnings.append(
                "reference contains SnpGrpState/SnpState2 (project marker "
                "metadata) but this document does not -- call "
                "clone_seed_states(). Their repository columns are NOT NULL "
                "and a real export always carries them.")

        # 9. layout drift vs the reference
        warnings += self.ref.verify_layouts()

        # 10. conventions this reference could not decide, so a built-in
        #     literal from another repository was used instead.
        for (cls, field_name), v in sorted(self._convention_fallbacks.items()):
            warnings.append(
                f"{cls}.{field_name} = {v!r} came from a built-in literal, not "
                f"from this reference: it contains no {cls} at all, so this "
                "repository's own convention could not be read. Verify the "
                "value, or export a reference that includes one.")

        # 11. objects that exist in the project but are in no Package step.
        #     A warning, not an error: ODI Procedures are legitimately run by
        #     another Package or straight from a Scenario.
        stepped = {s[3] for s in self.steps}
        for kind, declared in (("Procedure", self.trts), ("Variable", self.vars)):
            for orphan in sorted(set(declared) - stepped):
                warnings.append(
                    f"{kind} {orphan!r} is created but appears in no Package "
                    "step, so running this package never executes it. Intended "
                    "only if something outside this package calls it.")

        # 12. ProjectCode style.
        warnings += self._code_warnings

        # 13. SqlIndGrp values that rest on a single example in the reference.
        for (slot, kw), v in sorted(self._weak_sqlgrp.items()):
            warnings.append(
                f"SqlIndGrp={v!r} for a {kw or '(empty)'} statement in slot "
                f"{slot} was derived from ONE example in the reference. One "
                "observation is not a rule -- a thin reference can teach a "
                "confident wrong answer here. Confirm it, pass the value "
                "explicitly, or use a reference with more of these statements.")

        return {
            "errors": errors,
            "fatal": [e for e in errors if e not in overridable],
            "warnings": warnings,
            "summary": {
                "objects_by_class": dict(sorted(cls_counts.items())),
                "fkxrefs": len(self.fkxrefs),
                "steps": [
                    {"istep": s[0], "name": s[1], "type": s[2],
                     "ref": s[3], "ok_next": s[4], "ok_exit": self.ok_exit(s[4])}
                    for s in self.steps
                ],
            },
        }

    # -- output -------------------------------------------------------------
    def write_zip(self, xml_path, zip_path, xml_name="SmartExport.xml"):
        bad = self.unencodable_text()
        if bad:
            raise ValueError(
                "refusing to write: " + "; ".join(
                    f"{c}.{f} contains {ch!r}" for c, f, ch in bad) +
                f" -- {FILE_ENCODING} cannot represent these and a character "
                "reference is not interpreted inside CDATA, so the text would "
                "be silently corrupted. See validate() for the full message.")
        xml_text = self.render()
        os.makedirs(os.path.dirname(os.path.abspath(xml_path)), exist_ok=True)
        # errors="strict": a character this encoding cannot represent must
        # raise here too, never be silently escaped into a CDATA section where
        # the escape is not interpreted. unencodable_text() above is the
        # friendly guard; this is the one that cannot be bypassed.
        with open(xml_path, "w", encoding=FILE_ENCODING, errors="strict") as fh:
            fh.write(xml_text)
        os.makedirs(os.path.dirname(os.path.abspath(zip_path)), exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(xml_path, xml_name)
        return xml_path, zip_path


def rename_bind_prefix(sql, old_code, new_code):
    """'#OLD.V_X' -> '#NEW.V_X'. The only text substitution proven-good SQL
    from another project should need."""
    return re.sub(r"#" + re.escape(old_code) + r"\.", f"#{new_code}.", sql)
