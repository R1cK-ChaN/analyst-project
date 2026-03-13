from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(frozen=True)
class OECDCode:
    """A single code from an OECD codelist."""

    id: str
    name: str = ""
    description: str = ""
    parent_id: str = ""

@dataclass(frozen=True)
class OECDDimension:
    """A dimension declared in an OECD datastructure."""

    id: str
    position: int
    name: str = ""
    codelist_id: str = ""
    codelist_agency_id: str = ""
    codelist_version: str = ""
    is_time: bool = False
    codes: tuple[OECDCode, ...] = ()

@dataclass(frozen=True)
class OECDDataflow:
    """Metadata for an OECD dataflow exposed in Data Explorer."""

    id: str
    agency_id: str
    version: str
    name: str = ""
    description: str = ""
    structure_id: str = ""
    structure_agency_id: str = ""
    structure_version: str = ""
    defaults: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class OECDDataStructure:
    """Datastructure metadata and codelists for a dataflow."""

    id: str
    agency_id: str
    version: str
    name: str = ""
    dimensions: tuple[OECDDimension, ...] = ()
    dataflow_id: str = ""
    dataflow_agency_id: str = ""
    dataflow_version: str = ""
    defaults: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class OECDStructureSummary:
    """Compact structure metadata for catalogue discovery and inspection."""

    dataflow_id: str
    agency_id: str
    version: str
    name: str = ""
    description: str = ""
    structure_id: str = ""
    time_dimension_id: str = ""
    series_dimensions: tuple[str, ...] = ()
    code_counts: dict[str, int] = field(default_factory=dict)
    defaults: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class OECDSeries:
    """A single series key and its resolved dimensions."""

    key: str
    raw_key: str = ""
    dimensions: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class OECDObservation:
    """A single observation from the OECD SDMX API."""

    series_id: str
    date: str
    value: float
    dataflow: str = ""
    dataset: str = ""
    agency_id: str = ""
    series_key: str = ""
    raw_series_key: str = ""
    dimensions: dict[str, str] = field(default_factory=dict)

class OECDAPIError(RuntimeError):
    """Base error for OECD API failures."""

class OECDRateLimitError(OECDAPIError):
    """Raised when OECD throttles a request."""

class OECDResponseFormatError(OECDAPIError):
    """Raised when OECD returns an unexpected response format."""

