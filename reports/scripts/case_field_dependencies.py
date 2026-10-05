#!/usr/bin/env python3
"""Scan the Salesforce metadata in force-app/ and find where each Case field is used.

Writes a JSON file with field definitions and dependency rows, which
build_case_field_report.py turns into an Excel workbook.

Usage: python case_field_dependencies.py <repo_root> <out.json>
"""
import json
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from collections import defaultdict

NS = "{http://soap.sforce.com/2006/04/metadata}"

REPO = sys.argv[1] if len(sys.argv) > 1 else "."
OUT = sys.argv[2] if len(sys.argv) > 2 else "case_field_dependencies.json"
SRC = os.path.join(REPO, "force-app", "main", "default")
CASE_DIR = os.path.join(SRC, "objects", "Case")

# Types of standard Case fields, whose metadata files usually omit <type>.
STANDARD_TYPES = {
    "AccountId": "Lookup(Account)", "AssetId": "Lookup(Asset)",
    "BusinessHoursId": "Lookup(Business Hours)", "ClosedDate": "DateTime",
    "Comments": "TextArea", "ContactEmail": "Email", "ContactFax": "Fax",
    "ContactId": "Lookup(Contact)", "ContactMobile": "Phone",
    "ContactPhone": "Phone", "Description": "LongTextArea(32000)",
    "EntitlementId": "Lookup(Entitlement)", "IsClosedOnCreate": "Checkbox",
    "IsEscalated": "Checkbox", "IsStopped": "Checkbox", "Language": "Picklist",
    "MilestoneStatus": "Text", "MilestoneStatusIcon": "Text",
    "Origin": "Picklist", "OwnerId": "Lookup(User,Group)",
    "ParentId": "Lookup(Case)", "Priority": "Picklist",
    "ProductId": "Lookup(Product)", "Reason": "Picklist",
    "ServiceContractId": "Lookup(Service Contract)", "SlaExitDate": "DateTime",
    "SlaStartDate": "DateTime", "SourceId": "Lookup(Social Post,...)",
    "Status": "Picklist", "StopStartDate": "DateTime", "Subject": "Text(255)",
    "SuppliedCompany": "Text(80)", "SuppliedEmail": "Email",
    "SuppliedName": "Text(80)", "SuppliedPhone": "Text(40)", "Type": "Picklist",
}
STANDARD_LABELS = {
    "AccountId": "Account Name", "AssetId": "Asset", "BusinessHoursId": "Business Hours",
    "ClosedDate": "Date/Time Closed", "Comments": "Internal Comments",
    "ContactEmail": "Contact Email", "ContactFax": "Contact Fax", "ContactId": "Contact Name",
    "ContactMobile": "Contact Mobile", "ContactPhone": "Contact Phone",
    "Description": "Description", "EntitlementId": "Entitlement Name",
    "IsClosedOnCreate": "Closed When Created", "IsEscalated": "Escalated",
    "IsStopped": "Stopped", "Language": "Language", "MilestoneStatus": "Milestone Status",
    "MilestoneStatusIcon": "Milestone Status Icon", "Origin": "Case Origin",
    "OwnerId": "Case Owner", "ParentId": "Parent Case", "Priority": "Priority",
    "ProductId": "Product", "Reason": "Case Reason", "ServiceContractId": "Service Contract",
    "SlaExitDate": "Entitlement Process End Time", "SlaStartDate": "Entitlement Process Start Time",
    "SourceId": "Source", "Status": "Status", "StopStartDate": "Stopped Since",
    "Subject": "Subject", "SuppliedCompany": "Web Company", "SuppliedEmail": "Web Email",
    "SuppliedName": "Web Name", "SuppliedPhone": "Web Phone", "Type": "Type",
}

CONFIRMED = "Confirmed"
PROBABLE = "Probable"
POSSIBLE = "Possible"


def rel(path):
    return os.path.relpath(path, REPO)


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def parse_xml(path):
    try:
        return ET.parse(path).getroot()
    except ET.ParseError:
        return None


def child_text(el, tag, default=""):
    c = el.find(NS + tag)
    return c.text.strip() if c is not None and c.text else default


def strip_ns(tag):
    return tag.replace(NS, "")


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


# --------------------------------------------------------------------------
# Field definitions
# --------------------------------------------------------------------------
fields = {}
for fn in sorted(os.listdir(os.path.join(CASE_DIR, "fields"))):
    path = os.path.join(CASE_DIR, "fields", fn)
    root = parse_xml(path)
    name = fn.replace(".field-meta.xml", "")
    f = {
        "api": name, "label": child_text(root, "label") or STANDARD_LABELS.get(name, name),
        "custom": name.endswith("__c"), "raw_type": child_text(root, "type"),
        "length": child_text(root, "length"), "precision": child_text(root, "precision"),
        "scale": child_text(root, "scale"), "visible_lines": child_text(root, "visibleLines"),
        "reference_to": child_text(root, "referenceTo"),
        "relationship_name": child_text(root, "relationshipName"),
        "required": child_text(root, "required"), "unique": child_text(root, "unique"),
        "external_id": child_text(root, "externalId"), "formula": child_text(root, "formula"),
        "default": child_text(root, "defaultValue"),
        "controlling_field": "", "description": child_text(root, "description"),
        "help": child_text(root, "inlineHelpText"),
        "track_history": child_text(root, "trackHistory"),
        "summary": "", "path": rel(path),
    }
    vs = root.find(NS + "valueSet")
    if vs is not None:
        f["controlling_field"] = child_text(vs, "controllingField")
        f["global_value_set"] = child_text(vs, "valueSetName")
    if f["raw_type"] == "Summary":
        f["summary"] = "%s(%s)" % (child_text(root, "summaryOperation"),
                                   child_text(root, "summaryForeignKey"))
    if f["raw_type"] == "EncryptedText":
        f["mask"] = child_text(root, "maskType")
    lf = root.find(NS + "lookupFilter")
    f["lookup_filter"] = ET.tostring(lf, encoding="unicode") if lf is not None else ""
    fields[name] = f


def display_type(f):
    t = f["raw_type"]
    if not t:
        return STANDARD_TYPES.get(f["api"], "Standard")
    if f["formula"]:
        base = t
        if t in ("Number", "Currency", "Percent") and f["precision"]:
            base = "%s(%s,%s)" % (t, int(f["precision"]) - int(f["scale"] or 0), f["scale"] or 0)
        return "Formula (%s)" % base
    if t in ("Text", "EncryptedText") and f["length"]:
        return "%s(%s)" % (t, f["length"])
    if t in ("LongTextArea", "Html") and f["length"]:
        return "%s(%s)" % (t, f["length"])
    if t in ("Number", "Currency", "Percent") and f["precision"]:
        return "%s(%s,%s)" % (t, int(f["precision"]) - int(f["scale"] or 0), f["scale"] or 0)
    if t in ("Lookup", "MasterDetail"):
        if not f["reference_to"]:
            return STANDARD_TYPES.get(f["api"], t)
        return "%s(%s)" % (t, f["reference_to"])
    if t == "Summary":
        return "Roll-Up Summary (%s)" % f["summary"]
    return t


for f in fields.values():
    f["type"] = display_type(f)

LOWER = {k.lower(): k for k in fields}
NORM = {k.lower().replace("_", ""): k for k in fields}

# Field names that also exist on other objects (token-only matches are ambiguous)
other_object_fields = set()
for obj in os.listdir(os.path.join(SRC, "objects")):
    if obj == "Case":
        continue
    fd = os.path.join(SRC, "objects", obj, "fields")
    if os.path.isdir(fd):
        for fn in os.listdir(fd):
            other_object_fields.add(fn.replace(".field-meta.xml", "").lower())
for f in fields.values():
    f["shared_name"] = f["api"].lower() in other_object_fields

# Custom object names that collide with Case field names (e.g. CaseAnnex__c)
OBJECT_NAMES = {o.lower() for o in os.listdir(os.path.join(SRC, "objects"))}

# Relationship names of lookups to Case from other objects (e.g. Case__r)
case_rel_names = set()
for obj in os.listdir(os.path.join(SRC, "objects")):
    fd = os.path.join(SRC, "objects", obj, "fields")
    if not os.path.isdir(fd):
        continue
    for fn in os.listdir(fd):
        p = os.path.join(fd, fn)
        txt = read(p)
        if "<referenceTo>Case</referenceTo>" in txt:
            m = re.search(r"<relationshipName>([^<]+)</relationshipName>", txt)
            if m:
                case_rel_names.add(m.group(1) + "__r")
# Parent relationship on Case itself
case_rel_names.add("Parent")


def resolve(token):
    """Map a metadata field token (e.g. 'Case.Status', 'CASES.CLOSED_DATE', 'Account') to a Case field."""
    if not token:
        return None
    t = token.strip()
    for prefix in ("Case.", "CASES.", "Cases."):
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    else:
        if "." in t:
            return None
    lo = t.lower()
    if lo in LOWER:
        return LOWER[lo]
    if lo.endswith("__r") and lo[:-3] + "__c" in LOWER:
        return LOWER[lo[:-3] + "__c"]
    if lo + "id" in LOWER:
        return LOWER[lo + "id"]
    n = lo.replace("_", "")
    if n in NORM:
        return NORM[n]
    if n + "id" in NORM:
        return NORM[n + "id"]
    return None


# --------------------------------------------------------------------------
# Dependency collection
# --------------------------------------------------------------------------
deps = defaultdict(dict)   # key (field, type, component, detail) -> row
components = []            # inventory of scanned components


def add(field, mtype, component, path, detail="", confidence=CONFIRMED, lines=None,
        evidence="", status="", how=""):
    if field not in fields:
        return
    key = (field, mtype, component, detail)
    row = deps.get(key)
    rank = {CONFIRMED: 0, PROBABLE: 1, POSSIBLE: 2}
    if row is None:
        deps[key] = row = {
            "field": field, "type": mtype, "component": component, "detail": detail,
            "path": rel(path), "confidence": confidence, "lines": set(), "evidence": evidence,
            "status": status, "how": set(),
        }
    elif rank[confidence] < rank[row["confidence"]]:
        row["confidence"] = confidence
        row["evidence"] = evidence or row["evidence"]
    if not row["evidence"] and evidence:
        row["evidence"] = evidence
    if lines:
        row["lines"].update(lines)
    if how:
        row["how"].add(how)


def snippet(text, pos):
    s = text.rfind("\n", 0, pos) + 1
    e = text.find("\n", pos)
    e = len(text) if e == -1 else e
    return text[s:e].strip()[:250]


# ---------- formula helpers -------------------------------------------------
STR_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')
TOKEN_RE = re.compile(r"(?<![\w$.:])([A-Za-z][\w]*)(?=\s*(?:[^\w.(]|$|\.))")
REL_RE = re.compile(r"(?<![\w$.:])([A-Za-z]\w*__r)\.")


def formula_fields(formula, case_context=True):
    """Return Case fields referenced by a formula string."""
    found = set()
    if not formula:
        return found
    f = STR_RE.sub('""', formula)
    if case_context:
        for m in re.finditer(r"(?<![\w$.:])\$?(?:Case\.)?([A-Za-z]\w*)", f):
            tok = m.group(1)
            # skip function names: token followed by "("
            after = f[m.end():m.end() + 2].lstrip()
            if after.startswith("("):
                continue
            # 'X.Y' where X is a relationship: X__r -> X__c, Parent/Account/Owner -> ...Id
            nxt = f[m.end():m.end() + 1]
            if nxt == ".":
                lo = tok.lower()
                if lo.endswith("__r") and lo[:-3] + "__c" in LOWER:
                    found.add(LOWER[lo[:-3] + "__c"])
                elif lo + "id" in LOWER:
                    found.add(LOWER[lo + "id"])
                continue
            if tok.lower() in LOWER:
                found.add(LOWER[tok.lower()])
    for r in case_rel_names:
        for m in re.finditer(r"(?<![\w$])%s\.(\w+)" % re.escape(r), f, re.I):
            if m.group(1).lower() in LOWER:
                found.add(LOWER[m.group(1).lower()])
    return found


# ---------- code helpers ----------------------------------------------------
def strip_comments(code, html=False):
    """Blank out comments while keeping line numbers."""
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    code = re.sub(r"/\*.*?\*/", blank, code, flags=re.S)
    code = re.sub(r"(?<![:\"'])//[^\n]*", blank, code)
    if html:
        code = re.sub(r"<!--.*?-->", blank, code, flags=re.S)
    return code


FIELD_ALT = "|".join(sorted((re.escape(k) for k in fields), key=len, reverse=True))
ANY_FIELD_TOKEN = re.compile(r"(?<![\w$])(%s)(?![\w])" % FIELD_ALT, re.I)


def scan_code(text, path, mtype, component, kind, status=""):
    """Find Case field references in Apex / JS / markup."""
    code = strip_comments(text, html=kind in ("aura", "lwc", "vf"))
    hits = defaultdict(lambda: {"conf": POSSIBLE, "pos": [], "how": set()})

    def hit(field, pos, conf, how):
        h = hits[field]
        order = {CONFIRMED: 0, PROBABLE: 1, POSSIBLE: 2}
        if order[conf] < order[h["conf"]]:
            h["conf"] = conf
            h["pos"].insert(0, pos)
        else:
            h["pos"].append(pos)
        h["how"].add(how)

    # 1. Explicit Case.Field (Schema tokens, LWC schema imports, VF {!Case.X}, 'Case.X' strings)
    for m in re.finditer(r"(?<![\w.])(?:Schema\s*\.\s*)?(?:SObjectType\s*\.\s*)?Case\s*\.\s*(?:fields\s*\.\s*)?(\w+)", code, re.I if kind in ("apex", "trigger") else 0):
        f = LOWER.get(m.group(1).lower())
        if f:
            hit(f, m.start(1), CONFIRMED, "Case.%s reference" % f)
    for m in re.finditer(r"@salesforce/schema/Case\.(\w+)", code):
        f = LOWER.get(m.group(1).lower())
        if f:
            hit(f, m.start(1), CONFIRMED, "LWC schema import")

    # 2. Relationship traversal from other objects to Case (Case__r.Field)
    for r in case_rel_names:
        for m in re.finditer(r"(?<![\w$])%s\s*\.\s*(\w+)" % re.escape(r), code, re.I):
            f = LOWER.get(m.group(1).lower())
            if f:
                hit(f, m.start(1), CONFIRMED, "%s.%s relationship" % (r, f))

    # 3. SOQL against Case (static [..] or dynamic strings)
    for m in re.finditer(r"\bFROM\s+(Case|Cases)\b", code, re.I):
        start = code.rfind("SELECT", max(0, m.start() - 6000), m.start())
        start_u = max(code.lower().rfind("select", max(0, m.start() - 6000), m.start()), start)
        if start_u == -1:
            continue
        seg_end_candidates = [code.find(c, m.end()) for c in ("]", ";")]
        seg_end_candidates = [c for c in seg_end_candidates if c != -1]
        seg_end = min(seg_end_candidates) if seg_end_candidates else m.end() + 1500
        seg_end = min(seg_end, m.end() + 3000)
        # select list (only the innermost SELECT before FROM Case)
        for fm in ANY_FIELD_TOKEN.finditer(code, start_u, m.start()):
            if code[fm.start() - 1] == ".":
                continue
            hit(LOWER[fm.group(1).lower()], fm.start(), CONFIRMED, "SOQL on Case")
        for fm in ANY_FIELD_TOKEN.finditer(code, m.end(), seg_end):
            if code[fm.start() - 1] in ".:":
                continue
            hit(LOWER[fm.group(1).lower()], fm.start(), CONFIRMED, "SOQL on Case (filter/order)")

    if kind in ("apex", "trigger"):
        # 4. Case-typed variables
        case_vars = set()
        for m in re.finditer(r"(?<![\w.])(?:Case|List\s*<\s*Case\s*>|Set\s*<\s*Case\s*>|Case\s*\[\s*\])\s+(\w+)\s*(?=[=;,):{])", code, re.I):
            case_vars.add(m.group(1).lower())
        for m in re.finditer(r"\bfor\s*\(\s*Case\s+(\w+)\s*:", code, re.I):
            case_vars.add(m.group(1).lower())
        map_vars = set()
        for m in re.finditer(r"Map\s*<\s*[\w.]+\s*,\s*(?:Case|List\s*<\s*Case\s*>)\s*>\s+(\w+)", code, re.I):
            map_vars.add(m.group(1).lower())
        if kind == "trigger" and re.search(r"\btrigger\s+\w+\s+on\s+Case\b", code, re.I):
            map_vars.update({"trigger.newmap", "trigger.oldmap"})
            case_vars.update({"trigger.new", "trigger.old"})
        case_vars -= {"case"}
        for m in re.finditer(r"(?<![\w.])([A-Za-z_]\w*(?:\.\w+)?)\s*(?:\[[^\]\n]*\]|\.get\([^()\n]*(?:\([^()\n]*\))?[^()\n]*\))?\s*\.\s*(\w+)", code):
            base = m.group(1).lower()
            f = LOWER.get(m.group(2).lower())
            if not f:
                continue
            seg = m.group(0)
            if base in case_vars or (base in map_vars and ".get(" in seg.replace(" ", "")):
                hit(f, m.start(2), CONFIRMED, "Case variable '%s'" % m.group(1))
        # 5. new Case(Field = ...)
        for m in re.finditer(r"\bnew\s+Case\s*\(", code, re.I):
            depth, i = 1, m.end()
            while i < len(code) and depth:
                depth += {"(": 1, ")": -1}.get(code[i], 0)
                i += 1
            for fm in re.finditer(r"(?<![\w.])(\w+)\s*=(?!=)", code[m.end():i]):
                f = LOWER.get(fm.group(1).lower())
                if f:
                    hit(f, m.end() + fm.start(1), CONFIRMED, "new Case(...) assignment")

    if kind in ("aura", "lwc", "vf"):
        case_ctx = re.search(r"objectApiName\s*[=:]\s*[\"'{]*\s*[\"']?Case[\"']|object-api-name\s*=\s*[\"']Case[\"']|sobjectType[\"']?\s*[:=]\s*[\"']Case[\"']|standardController\s*=\s*[\"']Case[\"']|@salesforce/schema/Case\b|sObjectName\s*=\s*[\"']Case[\"']", code, re.I)
        if case_ctx:
            for m in re.finditer(r"(?:fieldName|field-name|fieldApiName|field-api-name)\s*[=:]\s*[\"'{]\s*[\"']?(\w+)", code, re.I):
                f = LOWER.get(m.group(1).lower())
                if f:
                    hit(f, m.start(1), CONFIRMED, "Field on Case record form/component")

    # 6. Token-only fallback for custom fields
    mentions_case = re.search(r"\bcase(s)?\b", code, re.I) is not None
    for fm in ANY_FIELD_TOKEN.finditer(code):
        f = LOWER[fm.group(1).lower()]
        if not fields[f]["custom"] or f.lower() in OBJECT_NAMES or f in hits and hits[f]["conf"] == CONFIRMED:
            if f in hits:
                hits[f]["pos"].append(fm.start())
            continue
        conf = PROBABLE if (mentions_case and not fields[f]["shared_name"]) else POSSIBLE
        hit(f, fm.start(), conf, "API name token")

    for f, h in hits.items():
        pos = sorted(set(h["pos"]))
        lines = sorted({line_of(code, p) for p in pos})
        first = h["pos"][0]
        add(f, mtype, component, path, detail="", confidence=h["conf"], lines=lines,
            evidence=snippet(text, first), status=status, how="; ".join(sorted(h["how"])))
    return len(hits)


# ---------- Apex classes & triggers ----------------------------------------
for d, mtype, ext, kind in (("classes", "Apex Class", ".cls", "apex"),
                            ("triggers", "Apex Trigger", ".trigger", "trigger")):
    base = os.path.join(SRC, d)
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(ext):
            continue
        path = os.path.join(base, fn)
        name = fn[:-len(ext)]
        meta = path + "-meta.xml"
        status = ""
        if os.path.exists(meta):
            m = re.search(r"<status>([^<]+)</status>", read(meta))
            status = m.group(1) if m else ""
        txt = read(path)
        is_test = bool(re.search(r"@isTest", txt, re.I))
        n = scan_code(txt, path, mtype, name, kind, status)
        components.append((mtype, name, rel(path), status, "Test class" if is_test else "", n))

# Mark test classes
test_classes = {c[1] for c in components if c[4] == "Test class"}

# ---------- Visualforce pages & components ---------------------------------
for d, mtype, ext in (("pages", "Visualforce Page", ".page"),
                      ("components", "Visualforce Component", ".component")):
    base = os.path.join(SRC, d)
    if not os.path.isdir(base):
        continue
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(ext):
            continue
        path = os.path.join(base, fn)
        n = scan_code(read(path), path, mtype, fn[:-len(ext)], "vf")
        components.append((mtype, fn[:-len(ext)], rel(path), "", "", n))

# ---------- Aura & LWC bundles ---------------------------------------------
for d, mtype, kind in (("aura", "Aura Component", "aura"), ("lwc", "Lightning Web Component", "lwc")):
    base = os.path.join(SRC, d)
    for bundle in sorted(os.listdir(base)):
        bdir = os.path.join(base, bundle)
        if not os.path.isdir(bdir):
            continue
        count_fields = set()
        for root_dir, _, files in os.walk(bdir):
            for fn in sorted(files):
                if fn.endswith((".js", ".cmp", ".html", ".app", ".evt", ".design", ".intf", ".tokens")) and "__tests__" not in root_dir:
                    path = os.path.join(root_dir, fn)
                    before = {k for k in deps if k[1] == mtype and k[2] == bundle}
                    scan_code(read(path), path, mtype, bundle, kind)
                    # keep one row per bundle: fold the per-file detail into the path column
        rows = [k for k in deps if k[1] == mtype and k[2] == bundle]
        components.append((mtype, bundle, rel(bdir), "", "", len(rows)))

# Aura/LWC rows were keyed per bundle; the path recorded is the first file that matched.

# ---------- Flows & Process Builders ---------------------------------------
flow_dir = os.path.join(SRC, "flows")
for fn in sorted(os.listdir(flow_dir)):
    if not fn.endswith(".flow-meta.xml"):
        continue
    path = os.path.join(flow_dir, fn)
    text = read(path)
    root = parse_xml(path)
    if root is None:
        continue
    name = fn.replace(".flow-meta.xml", "")
    label = child_text(root, "label")
    ptype = child_text(root, "processType")
    status = child_text(root, "status")
    mtype = "Process Builder" if ptype == "Workflow" else "Flow"
    trig = ""
    start = root.find(NS + "start")
    start_obj = child_text(start, "object") if start is not None else ""
    if start is not None:
        trig = child_text(start, "recordTriggerType") or child_text(start, "triggerType")
    case_vars = set()
    if start_obj == "Case":
        case_vars.update({"$record", "$record__prior"})
    for v in root.findall(NS + "variables"):
        if child_text(v, "objectType") == "Case":
            case_vars.add(child_text(v, "name").lower())
    lookup_names = []
    for el in root:
        tag = strip_ns(el.tag)
        obj = child_text(el, "object")
        if obj == "Case" and tag in ("recordLookups", "recordCreates", "recordUpdates", "recordDeletes"):
            ename = child_text(el, "name")
            lookup_names.append(ename)
            if tag == "recordLookups" and child_text(el, "storeOutputAutomatically") == "true":
                case_vars.add(ename.lower())
            out = child_text(el, "outputReference")
            if out:
                case_vars.add(out.lower())
            for f_el in el.iter():
                t2 = strip_ns(f_el.tag)
                if t2 in ("field", "queriedFields", "sortField") and f_el.text:
                    f = resolve(f_el.text.strip())
                    if f:
                        pos = text.find(">%s<" % f_el.text.strip(), text.find("<name>%s</name>" % ename))
                        add(f, mtype, name, path, detail="", confidence=CONFIRMED,
                            lines=[line_of(text, pos)] if pos > 0 else None,
                            evidence="%s '%s' on Case uses field %s" % (tag, ename, f_el.text.strip()),
                            status=status, how="%s on Case" % tag)
    # loops over Case collections
    for lp in root.findall(NS + "loops"):
        coll = child_text(lp, "collectionReference").lower()
        if coll in case_vars:
            case_vars.add(child_text(lp, "name").lower())
    # Process Builder: myVariable_current / myVariable_old with objectType Case
    for pv in root.findall(NS + "processMetadataValues"):
        pass
    if case_vars:
        alt = "|".join(re.escape(v) for v in sorted(case_vars, key=len, reverse=True))
        for m in re.finditer(r"(?<![\w$])(%s)\.(\w+)" % alt, text, re.I):
            tok = m.group(2)
            f = LOWER.get(tok.lower())
            if not f and tok.lower().endswith("__r"):
                f = LOWER.get(tok.lower()[:-3] + "__c")
            if not f and text[m.end():m.end() + 1] == "." and tok.lower() + "id" in LOWER:
                f = LOWER[tok.lower() + "id"]
            if f:
                add(f, mtype, name, path, detail="", confidence=CONFIRMED,
                    lines=[line_of(text, m.start())], evidence=snippet(text, m.start()),
                    status=status, how="Case variable '%s'" % m.group(1))
    # Relationship traversal to Case from other records ($Record.Case__r.Status)
    for r in case_rel_names - {"Parent"}:
        for m in re.finditer(r"\.%s\.(\w+)" % re.escape(r), text, re.I):
            f = LOWER.get(m.group(1).lower())
            if f:
                add(f, mtype, name, path, confidence=CONFIRMED, lines=[line_of(text, m.start())],
                    evidence=snippet(text, m.start()), status=status, how="%s relationship" % r)
    n = len({k for k in deps if k[1] == mtype and k[2] == name})
    components.append((mtype, name, rel(path), status,
                       "%s%s%s" % (ptype, "; object=" + start_obj if start_obj else "",
                                   "; trigger=" + trig if trig else ""), n))

# ---------- Case validation rules ------------------------------------------
vr_dir = os.path.join(CASE_DIR, "validationRules")
for fn in sorted(os.listdir(vr_dir)):
    path = os.path.join(vr_dir, fn)
    root = parse_xml(path)
    name = fn.replace(".validationRule-meta.xml", "")
    formula = child_text(root, "errorConditionFormula")
    active = child_text(root, "active")
    err_field = child_text(root, "errorDisplayField")
    text = read(path)
    found = formula_fields(formula)
    for f in found:
        m = re.search(r"(?<![\w.])%s(?!\w)" % re.escape(f), text, re.I)
        add(f, "Validation Rule", name, path, detail="Error condition formula",
            lines=[line_of(text, m.start())] if m else None,
            evidence=formula[:250].replace("\n", " "), status="Active" if active == "true" else "Inactive")
    if err_field and resolve(err_field):
        add(resolve(err_field), "Validation Rule", name, path, detail="Error display field",
            status="Active" if active == "true" else "Inactive", evidence="errorDisplayField=" + err_field)
    components.append(("Validation Rule", name, rel(path), "Active" if active == "true" else "Inactive", "", len(found)))

# ---------- Other objects' validation rules & formula fields (cross-object) --
for obj in sorted(os.listdir(os.path.join(SRC, "objects"))):
    if obj == "Case":
        continue
    for sub, mtype, tag in (("validationRules", "Validation Rule (Other Object)", "errorConditionFormula"),
                            ("fields", "Formula Field (Other Object)", "formula")):
        d = os.path.join(SRC, "objects", obj, sub)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            path = os.path.join(d, fn)
            txt = read(path)
            if not any(r.lower() in txt.lower() for r in case_rel_names - {"Parent"}):
                continue
            root = parse_xml(path)
            formula = child_text(root, tag)
            if not formula:
                continue
            nm = obj + "." + fn.split(".")[0]
            for f in formula_fields(formula, case_context=False):
                add(f, mtype, nm, path, detail="Cross-object reference via lookup to Case",
                    evidence=formula[:250].replace("\n", " "),
                    status=("Active" if child_text(root, "active") == "true" else "Inactive") if sub == "validationRules" else "")

# ---------- Case formula fields, field dependencies, lookup filters --------
for f in fields.values():
    path = os.path.join(REPO, f["path"])
    if f["formula"]:
        for ref in formula_fields(f["formula"]):
            if ref != f["api"]:
                add(ref, "Formula Field (Case)", f["api"], path, detail="Referenced in formula",
                    evidence=f["formula"][:250].replace("\n", " "))
    if f["formula"]:
        components.append(("Formula Field (Case)", f["api"], f["path"], "", "", len(formula_fields(f["formula"]) - {f["api"]})))
    if f["controlling_field"]:
        components.append(("Field Dependency (Picklist)", f["api"], f["path"], "", "Controlled by " + f["controlling_field"], 2))
        cf = resolve(f["controlling_field"])
        if cf:
            add(cf, "Field Dependency (Picklist)", f["api"], path,
                detail="Controlling field of dependent picklist %s" % f["api"],
                evidence="controllingField=" + f["controlling_field"])
            add(f["api"], "Field Dependency (Picklist)", f["api"], path,
                detail="Dependent picklist controlled by %s" % cf,
                evidence="controllingField=" + f["controlling_field"])
    if f["lookup_filter"]:
        for m in re.finditer(r"\$Source\.(\w+)|<field>\$?Source\.(\w+)</field>", f["lookup_filter"]):
            ref = LOWER.get((m.group(1) or m.group(2)).lower())
            if ref:
                add(ref, "Lookup Filter", f["api"], path,
                    detail="Used in lookup filter of %s" % f["api"], evidence=m.group(0))

# ---------- Workflow (Case) -------------------------------------------------
wf = os.path.join(SRC, "workflows", "Case.workflow-meta.xml")
if os.path.exists(wf):
    root = parse_xml(wf)
    text = read(wf)

    def wf_line(name):
        p = text.find("<fullName>%s</fullName>" % name)
        return [line_of(text, p)] if p >= 0 else None

    for r in root.findall(NS + "rules"):
        name = child_text(r, "fullName")
        st = "Active" if child_text(r, "active") == "true" else "Inactive"
        n = set()
        for ci in r.findall(NS + "criteriaItems"):
            f = resolve(child_text(ci, "field"))
            if f:
                n.add(f)
                add(f, "Workflow Rule", name, wf, detail="Rule criteria", lines=wf_line(name),
                    evidence="%s %s %s" % (child_text(ci, "field"), child_text(ci, "operation"), child_text(ci, "value")), status=st)
        for f in formula_fields(child_text(r, "formula")):
            n.add(f)
            add(f, "Workflow Rule", name, wf, detail="Rule formula", lines=wf_line(name),
                evidence=child_text(r, "formula")[:250], status=st)
        components.append(("Workflow Rule", name, rel(wf), st, "", len(n)))
    for fu in root.findall(NS + "fieldUpdates"):
        name = child_text(fu, "fullName")
        tgt = child_text(fu, "field")
        if child_text(fu, "targetObject") not in ("", "Case"):
            continue
        n = set()
        f = resolve(tgt)
        if f:
            n.add(f)
            add(f, "Workflow Field Update", name, wf, detail="Field updated", lines=wf_line(name),
                evidence="Updates %s (%s)" % (tgt, child_text(fu, "operation")))
        for f in formula_fields(child_text(fu, "formula")):
            n.add(f)
            add(f, "Workflow Field Update", name, wf, detail="Used in update formula", lines=wf_line(name),
                evidence=child_text(fu, "formula")[:250])
        components.append(("Workflow Field Update", name, rel(wf), "", "", len(n)))
    for al in root.findall(NS + "alerts"):
        name = child_text(al, "fullName")
        n = set()
        for rc in al.findall(NS + "recipients"):
            f = resolve(child_text(rc, "field"))
            if f:
                n.add(f)
                add(f, "Workflow Email Alert", name, wf, detail="Recipient field (%s)" % child_text(rc, "type"),
                    lines=wf_line(name), evidence="Recipient: %s" % child_text(rc, "field"))
        components.append(("Workflow Email Alert", name, rel(wf), "", "", len(n)))
    for om in root.findall(NS + "outboundMessages"):
        name = child_text(om, "fullName")
        n = set()
        for fe in om.findall(NS + "fields"):
            f = resolve(fe.text or "")
            if f:
                n.add(f)
                add(f, "Workflow Outbound Message", name, wf, detail="Field sent", lines=wf_line(name),
                    evidence="Field: %s" % fe.text)
        components.append(("Workflow Outbound Message", name, rel(wf), "", "", len(n)))

# Field updates on other objects' workflows that target Case
for fn in os.listdir(os.path.join(SRC, "workflows")):
    if fn == "Case.workflow-meta.xml":
        continue
    path = os.path.join(SRC, "workflows", fn)
    root = parse_xml(path)
    for fu in root.findall(NS + "fieldUpdates"):
        if child_text(fu, "targetObject") == "Case" or child_text(fu, "field").startswith("Case."):
            f = resolve(child_text(fu, "field"))
            if f:
                add(f, "Workflow Field Update", fn.split(".")[0] + "." + child_text(fu, "fullName"), path,
                    detail="Cross-object field update on Case", evidence="Updates " + child_text(fu, "field"))


# ---------- Rule files with ruleEntry (assignment, auto-response, escalation)
def scan_rule_file(path, mtype, rule_tag):
    if not os.path.exists(path):
        return
    root = parse_xml(path)
    text = read(path)
    for rule in root.findall(NS + rule_tag):
        rname_raw = child_text(rule, "fullName")
        rname = urllib.parse.unquote(rname_raw)
        st = "Active" if child_text(rule, "active") == "true" else "Inactive"
        rp = text.find("<fullName>%s</fullName>" % rname_raw)
        n = set()
        for i, entry in enumerate(rule.findall(NS + "ruleEntry"), 1):
            target = child_text(entry, "assignedTo") or child_text(entry, "senderEmail") or child_text(entry, "template")
            detail = "Entry %d%s" % (i, " -> " + target if target else "")
            for ci in entry.findall(NS + "criteriaItems"):
                f = resolve(child_text(ci, "field"))
                if f:
                    n.add(f)
                    add(f, mtype, rname, path, detail=detail, lines=[line_of(text, rp)] if rp >= 0 else None,
                        evidence="%s %s %s" % (child_text(ci, "field"), child_text(ci, "operation"), child_text(ci, "value")), status=st)
            fml = child_text(entry, "formula")
            for f in formula_fields(fml):
                n.add(f)
                add(f, mtype, rname, path, detail=detail, lines=[line_of(text, rp)] if rp >= 0 else None,
                    evidence=re.sub(r"\s+", " ", fml)[:250], status=st)
            for esc in entry.findall(NS + "escalationAction"):
                pass
        components.append((mtype, rname, rel(path), st, "", len(n)))


scan_rule_file(os.path.join(SRC, "assignmentRules", "Case.assignmentRules-meta.xml"), "Assignment Rule", "assignmentRule")
scan_rule_file(os.path.join(SRC, "autoResponseRules", "Case.autoResponseRules-meta.xml"), "Auto-Response Rule", "autoResponseRule")
escalation_path = os.path.join(SRC, "escalationRules", "Case.escalationRules-meta.xml")
scan_rule_file(escalation_path, "Escalation Rule", "escalationRule")
ESCALATION_PRESENT = os.path.exists(escalation_path)

# ---------- Sharing rules (Case) -------------------------------------------
sr = os.path.join(SRC, "sharingRules", "Case.sharingRules-meta.xml")
if os.path.exists(sr):
    root = parse_xml(sr)
    text = read(sr)
    for rule in list(root.findall(NS + "sharingCriteriaRules")) + list(root.findall(NS + "sharingOwnerRules")):
        name = child_text(rule, "fullName")
        rp = text.find("<fullName>%s</fullName>" % name)
        n = set()
        for ci in rule.findall(NS + "criteriaItems"):
            f = resolve(child_text(ci, "field"))
            if f:
                n.add(f)
                add(f, "Sharing Rule", name, sr, detail="Criteria (%s access)" % child_text(rule, "accessLevel"),
                    lines=[line_of(text, rp)], evidence="%s %s %s" % (child_text(ci, "field"), child_text(ci, "operation"), child_text(ci, "value")))
        for f in formula_fields(child_text(rule, "criteriaFormula") or child_text(rule, "formula")):
            n.add(f)
            add(f, "Sharing Rule", name, sr, detail="Criteria formula", lines=[line_of(text, rp)])
        components.append(("Sharing Rule", name, rel(sr), "", strip_ns(rule.tag), len(n)))

# ---------- Generic "list of field names" XML metadata ---------------------
def scan_field_list(path, mtype, component, tags, detail="", status="", formula_tags=()):
    root = parse_xml(path)
    if root is None:
        return 0
    text = read(path)
    n = set()
    for el in root.iter():
        t = strip_ns(el.tag)
        if t in tags and el.text:
            f = resolve(el.text.strip())
            if f:
                n.add(f)
                pos = text.find(">%s<" % el.text.strip())
                add(f, mtype, component, path, detail=detail or t, status=status,
                    lines=[line_of(text, pos)] if pos >= 0 else None, evidence="<%s>%s</%s>" % (t, el.text.strip(), t))
        if t in formula_tags and el.text:
            for f in formula_fields(el.text):
                n.add(f)
                add(f, mtype, component, path, detail=detail or ("Formula (%s)" % t), status=status,
                    evidence=re.sub(r"\s+", " ", el.text)[:250])
    return len(n)


# Page layouts
for fn in sorted(os.listdir(os.path.join(SRC, "layouts"))):
    if fn.startswith("Case-") or fn.startswith("Case %28") :
        path = os.path.join(SRC, "layouts", fn)
        name = fn.replace(".layout-meta.xml", "")
        n = scan_field_list(path, "Page Layout", name, {"field"}, detail="Layout field")
        components.append(("Page Layout", name, rel(path), "", "", n))

# Compact layouts, list views, record types, business processes, web links (Case)
for sub, mtype, tags in (("compactLayouts", "Compact Layout", {"fields"}),
                         ("listViews", "List View", {"columns", "field"}),
                         ("recordTypes", "Record Type", {"picklist"}),
                         ("businessProcesses", "Business Process", set()),
                         ("webLinks", "Web Link / Button", set())):
    d = os.path.join(CASE_DIR, sub)
    for fn in sorted(os.listdir(d)):
        path = os.path.join(d, fn)
        name = fn.split(".")[0]
        if sub == "businessProcesses":
            add("Status", mtype, name, path, detail="Defines available Status values",
                evidence="Business process controls Status picklist values")
            components.append((mtype, name, rel(path), "", "", 1))
            continue
        if sub == "webLinks":
            text = read(path)
            n = set()
            for m in re.finditer(r"\{!\s*Case\.(\w+)", text):
                f = LOWER.get(m.group(1).lower())
                if f:
                    n.add(f)
                    add(f, mtype, name, path, detail="Merge field", lines=[line_of(text, m.start())],
                        evidence=snippet(text, m.start()))
            components.append((mtype, name, rel(path), "", "", len(n)))
            continue
        detail = {"columns": "Column", "field": "Filter", "fields": "Compact layout field",
                  "picklist": "Picklist values configured"}
        root = parse_xml(path)
        text = read(path)
        n = set()
        for el in root.iter():
            t = strip_ns(el.tag)
            if t in tags and el.text:
                f = resolve(el.text.strip())
                if f:
                    n.add(f)
                    pos = text.find(">%s<" % el.text.strip())
                    add(f, mtype, name, path, detail=detail[t], lines=[line_of(text, pos)] if pos >= 0 else None,
                        evidence="<%s>%s</%s>" % (t, el.text.strip(), t))
        components.append((mtype, name, rel(path), "", "", len(n)))

# Quick actions targeting Case
for fn in sorted(os.listdir(os.path.join(SRC, "quickActions"))):
    path = os.path.join(SRC, "quickActions", fn)
    root = parse_xml(path)
    if root is None:
        continue
    name = fn.replace(".quickAction-meta.xml", "")
    target = child_text(root, "targetObject")
    src_obj = name.split(".")[0] if "." in name else ""
    if not (target == "Case" or (not target and src_obj == "Case")):
        continue
    text = read(path)
    n = set()
    for el in root.iter():
        t = strip_ns(el.tag)
        if t == "field" and el.text:
            f = resolve(el.text.strip())
            if f:
                n.add(f)
                pos = text.find(">%s<" % el.text.strip())
                add(f, "Quick Action", name, path, detail="Layout field / field override",
                    lines=[line_of(text, pos)] if pos >= 0 else None, evidence="<field>%s</field>" % el.text.strip())
        if t == "formula" and el.text and src_obj == "Case":
            for f in formula_fields(el.text):
                n.add(f)
                add(f, "Quick Action", name, path, detail="Predefined value formula",
                    evidence=el.text[:250])
    # Formulas on actions from other objects may reference the source Case (e.g. Case.X)
    if src_obj != "Case":
        for m in re.finditer(r"\bCase\.(\w+)", text):
            f = LOWER.get(m.group(1).lower())
            if f:
                n.add(f)
                add(f, "Quick Action", name, path, detail="Predefined value formula",
                    lines=[line_of(text, m.start())], evidence=snippet(text, m.start()))
    components.append(("Quick Action", name, rel(path), "", "type=%s; target=%s" % (child_text(root, "type"), target or src_obj), len(n)))

# Quick actions on Case whose formulas copy Case fields to other targets
for fn in sorted(os.listdir(os.path.join(SRC, "quickActions"))):
    if not fn.startswith("Case."):
        continue
    path = os.path.join(SRC, "quickActions", fn)
    root = parse_xml(path)
    if root is None or child_text(root, "targetObject") in ("", "Case"):
        continue
    text = read(path)
    name = fn.replace(".quickAction-meta.xml", "")
    for fo in root.findall(NS + "fieldOverrides"):
        fml = child_text(fo, "formula")
        for m in re.finditer(r"\bCase\.(\w+)", fml):
            f = LOWER.get(m.group(1).lower())
            if f:
                add(f, "Quick Action", name, path, detail="Source value for %s.%s" % (child_text(root, "targetObject"), child_text(fo, "field")),
                    evidence=fml[:250])

# Report types
for fn in sorted(os.listdir(os.path.join(SRC, "reportTypes"))):
    path = os.path.join(SRC, "reportTypes", fn)
    root = parse_xml(path)
    name = fn.replace(".reportType-meta.xml", "")
    text = read(path)
    n = set()
    for col in root.iter(NS + "columns"):
        table = child_text(col, "table")
        last = table.split(".")[-1]
        if table == "Case" or last in ("Cases", "Case") or last in case_rel_names:
            fld = child_text(col, "field")
            f = resolve(fld)
            if f:
                n.add(f)
                pos = text.find("<field>%s</field>" % fld)
                add(f, "Report Type", name, path, detail="Column (table %s)" % table,
                    lines=[line_of(text, pos)] if pos >= 0 else None, evidence="%s.%s" % (table, fld))
    if n or "Case" in child_text(root, "baseObject"):
        components.append(("Report Type", name, rel(path), "", "base=" + child_text(root, "baseObject"), len(n)))

# Approval processes on Case
for fn in sorted(os.listdir(os.path.join(SRC, "approvalProcesses"))):
    if not fn.startswith("Case."):
        continue
    path = os.path.join(SRC, "approvalProcesses", fn)
    root = parse_xml(path)
    name = fn.replace(".approvalProcess-meta.xml", "")
    st = "Active" if child_text(root, "active") == "true" else "Inactive"
    n = scan_field_list(path, "Approval Process", name, {"field"}, status=st,
                        formula_tags=("formula",))
    components.append(("Approval Process", name, rel(path), st, "", n))

# Entitlement processes (Case)
for fn in sorted(os.listdir(os.path.join(SRC, "entitlementProcesses"))):
    path = os.path.join(SRC, "entitlementProcesses", fn)
    root = parse_xml(path)
    if root is None or child_text(root, "SObjectType") not in ("", "Case"):
        continue
    name = fn.replace(".entitlementProcess-meta.xml", "").replace("%28", "(").replace("%29", ")")
    st = "Active" if child_text(root, "active") == "true" else "Inactive"
    n = scan_field_list(path, "Entitlement Process", name,
                        {"field", "entryStartDateField", "exitCriteriaBooleanFilter"},
                        status=st, formula_tags=("exitCriteriaFormula", "milestoneCriteriaFormula", "formula"))
    components.append(("Entitlement Process", name, rel(path), st, "", n))

# Duplicate / matching rules on Case
for d, mtype in (("duplicateRules", "Duplicate Rule"), ("matchingRules", "Matching Rule")):
    for fn in sorted(os.listdir(os.path.join(SRC, d))):
        if fn.startswith("Case."):
            path = os.path.join(SRC, d, fn)
            name = fn.split("-meta")[0]
            n = scan_field_list(path, mtype, name, {"field", "fieldName"})
            components.append((mtype, name, rel(path), "", "", n))

# Custom metadata records that name Case fields
cmd_dir = os.path.join(SRC, "customMetadata")
VALUES_RE = re.compile(r"<values>\s*<field>([^<]+)</field>\s*<value[^>]*>(.*?)</value>", re.S)
for fn in sorted(os.listdir(cmd_dir)):
    path = os.path.join(cmd_dir, fn)
    text = read(path)
    name = fn.replace(".md-meta.xml", "")
    vals = [(m.group(1), m.group(2).replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&"), m.start(2))
            for m in VALUES_RE.finditer(text)]
    # record points at Case when one of its values is exactly "Case"
    record_is_case = any(v.strip() == "Case" for _, v, _ in vals)
    n = set()
    for mfield, val, pos in vals:
        ln = [line_of(text, pos)]
        done = set()
        # JSON blocks: {"objectName": "Case", "fieldAPIName": "X"}
        for blk in re.finditer(r"\{[^{}]*\}", val):
            b = blk.group(0)
            om = re.search(r'"objectName"\s*:\s*"(\w+)"', b)
            fm = re.search(r'"field(?:API)?Name"\s*:\s*"(\w+)"', b, re.I)
            if om and fm:
                f = LOWER.get(fm.group(1).lower())
                if om.group(1) == "Case" and f:
                    n.add(f)
                    add(f, "Custom Metadata Record", name, path, detail="%s: JSON objectName=Case, fieldAPIName=%s" % (mfield, f),
                        lines=ln, evidence=re.sub(r"\s+", " ", b)[:250])
                done.add(fm.group(1).lower())
        for tok in re.findall(r"\bCase\.(\w+)", val):
            f = LOWER.get(tok.lower())
            if f:
                n.add(f)
                done.add(tok.lower())
                add(f, "Custom Metadata Record", name, path, detail="%s names Case.%s" % (mfield, f),
                    lines=ln, evidence=val[:250])
        # Delimited lists of API names, e.g. "cc_X__c;cc_Y__c;Free text label"
        for item in re.split(r"[;,|\n]", val):
            item = item.strip()
            f = LOWER.get(item.lower())
            if not f or f.lower() in done:
                continue
            if record_is_case:
                conf = CONFIRMED
            elif not fields[f]["custom"] or f.lower() in OBJECT_NAMES:
                continue
            else:
                conf = PROBABLE if ("Case" in text and not fields[f]["shared_name"]) else POSSIBLE
            done.add(f.lower())
            n.add(f)
            add(f, "Custom Metadata Record", name, path, detail="%s lists API name%s" % (mfield, " (record Object = Case)" if record_is_case else ""),
                confidence=conf, lines=ln, evidence=val[:250])
    if n:
        components.append(("Custom Metadata Record", name, rel(path), "", "", len(n)))

# --------------------------------------------------------------------------
rows = []
for r in deps.values():
    r = dict(r)
    lines = sorted(r["lines"])
    r["lines"] = ", ".join(str(x) for x in lines[:15]) + (" ..." if len(lines) > 15 else "")
    r["how"] = "; ".join(sorted(r["how"]))
    if r["type"] == "Apex Class" and r["component"] in test_classes:
        r["detail"] = (r["detail"] + "; " if r["detail"] else "") + "Test class"
    rows.append(r)

present_types = sorted({c[0] for c in components})
out = {
    "fields": list(fields.values()),
    "deps": rows,
    "components": components,
    "escalation_present": ESCALATION_PRESENT,
    "case_relationships": sorted(case_rel_names),
    "metadata_dirs": sorted(os.listdir(SRC)),
}
with open(OUT, "w") as fh:
    json.dump(out, fh)
print("fields", len(fields), "deps", len(rows), "components", len(components))
from collections import Counter
print(Counter(r["type"] for r in rows).most_common())
print(Counter(r["confidence"] for r in rows))
