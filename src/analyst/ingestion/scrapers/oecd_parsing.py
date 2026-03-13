from __future__ import annotations

from datetime import date
import re
import xml.etree.ElementTree as ET

_QUARTER_MAP = {"Q1": "01", "Q2": "04", "Q3": "07", "Q4": "10"}
_SEMESTER_MAP = {"S1": "01", "S2": "07"}
_XML_NS = {
    "common": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
    "message": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "structure": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
}
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_EMPTY_DATA_PAYLOAD = {"data": {"dataSets": [], "structures": []}}

def _normalize_date(raw: str) -> str:
    """Normalize OECD period strings to YYYY-MM-DD where possible."""

    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw

    m = re.match(r"^(\d{4})-Q(\d)$", raw)
    if m:
        return f"{m.group(1)}-{_QUARTER_MAP.get('Q' + m.group(2), '01')}-01"

    m = re.match(r"^(\d{4})-S([12])$", raw)
    if m:
        return f"{m.group(1)}-{_SEMESTER_MAP.get('S' + m.group(2), '01')}-01"

    m = re.match(r"^(\d{4})-W(\d{2})$", raw)
    if m:
        try:
            return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1).isoformat()
        except ValueError:
            return raw

    if re.match(r"^\d{4}-\d{2}$", raw):
        return f"{raw}-01"

    if re.match(r"^\d{4}$", raw):
        return f"{raw}-01-01"

    return raw

def _pick_localized_xml_text(parent: ET.Element, tag: str) -> str:
    values = parent.findall(tag, _XML_NS)
    if not values:
        return ""
    for lang in ("en", "en-US"):
        for value in values:
            if value.attrib.get(_XML_LANG) == lang and value.text:
                return value.text.strip()
    for value in values:
        if value.text and value.text.strip():
            return value.text.strip()
    return ""

def _parse_assignments(raw: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for part in raw.split(","):
        left, sep, right = part.partition("=")
        if not sep:
            continue
        key = left.strip()
        value = right.strip()
        if key and value:
            assignments[key] = value
    return assignments

