from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass(frozen=True)
class StoredEventRecord:
    source: str
    event_id: str
    timestamp: int
    country: str
    indicator: str
    category: str
    importance: str
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None
    revised_previous: str | None = None
    surprise: float | None = None
    currency: str = ""
    unit: str = ""
    raw_json: dict[str, Any] = field(default_factory=dict)
    indicator_id: str | None = None

@dataclass(frozen=True)
class CalendarIndicatorRecord:
    indicator_id: str               # 'us.inflation.cpi_mom'
    canonical_name: str             # 'CPI MoM'
    topic: str
    country_code: str
    frequency: str                  # monthly, quarterly, etc.
    unit: str
    obs_family_id: str | None = None
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""

@dataclass(frozen=True)
class CalendarIndicatorAliasRecord:
    alias_normalized: str           # lowercased, stripped
    indicator_id: str               # FK → calendar_indicator
    source: str                     # 'investing'|'forexfactory'|'tradingeconomics'
    country_code: str
    alias_original: str = ""
    created_at: str = ""

@dataclass(frozen=True)
class MarketPriceRecord:
    symbol: str
    asset_class: str
    price: float
    change_pct: float | None
    timestamp: int
    name: str = ""

@dataclass(frozen=True)
class CentralBankCommunicationRecord:
    source: str
    title: str
    url: str
    timestamp: int
    content_type: str
    speaker: str = ""
    summary: str = ""
    full_text: str = ""

@dataclass(frozen=True)
class IndicatorObservationRecord:
    series_id: str
    source: str
    date: str
    value: float
    metadata: dict[str, Any] = field(default_factory=dict)
    obs_family_id: str | None = None

@dataclass(frozen=True)
class IndicatorVintageRecord:
    series_id: str
    source: str
    observation_date: str   # the date being measured
    vintage_date: str       # when this measurement was published
    value: float
    metadata: dict[str, Any] = field(default_factory=dict)
    obs_family_id: str | None = None

@dataclass(frozen=True)
class ObsSourceRecord:
    source_id: str          # 'fred', 'eia', 'treasury_fiscal'
    source_code: str
    source_name: str
    source_type: str        # data_aggregator, government_agency, central_bank, exchange, market_data
    country_code: str
    homepage_url: str
    api_base_url: str
    is_active: bool
    created_at: str
    updated_at: str

@dataclass(frozen=True)
class ObsFamilyRecord:
    family_id: str                  # 'us.inflation.cpi_all'
    source_id: str                  # 'fred'
    provider_series_id: str         # 'CPIAUCSL' (matches indicators.series_id)
    canonical_name: str             # 'CPI All Urban Consumers'
    short_name: str
    unit: str                       # 'index', 'percent', 'billions_usd'
    frequency: str                  # daily, weekly, monthly, quarterly, annual, irregular
    seasonal_adjustment: str        # sa, nsa, saar, none
    country_code: str
    topic_code: str                 # inflation, employment, rates, energy, fiscal
    category: str                   # consumer_prices, treasury_yields
    is_active: bool
    has_vintages: bool
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

@dataclass(frozen=True)
class ObsFamilyDocumentRecord:
    family_id: str
    release_family_id: str
    relationship: str           # produced_by, derived_from, related_to
    created_at: str

@dataclass(frozen=True)
class NewsArticleRecord:
    url_hash: str
    source_feed: str
    feed_category: str
    title: str
    url: str
    timestamp: int
    description: str
    content_markdown: str
    impact_level: str
    finance_category: str
    confidence: float
    content_fetched: bool
    institution: str = ""
    country: str = ""
    market: str = ""
    asset_class: str = ""
    sector: str = ""
    document_type: str = ""
    event_type: str = ""
    subject: str = ""
    subject_id: str = ""
    data_period: str = ""
    contains_commentary: bool = False
    language: str = "en"
    authors: str = ""
    extraction_provider: str = "keyword"

@dataclass(frozen=True)
class RegimeSnapshotRecord:
    snapshot_id: int
    timestamp: str
    regime_json: dict[str, Any]
    trigger_event: str
    summary: str

@dataclass(frozen=True)
class GeneratedNoteRecord:
    note_id: int
    created_at: str
    note_type: str
    title: str
    summary: str
    body_markdown: str
    regime_json: dict[str, Any] | None
    metadata: dict[str, Any]

@dataclass(frozen=True)
class AnalyticalObservationRecord:
    observation_id: int
    observation_type: str
    summary: str
    detail: str
    source_kind: str
    source_id: int
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ResearchArtifactRecord:
    artifact_id: int
    artifact_type: str
    title: str
    summary: str
    content_markdown: str
    source_kind: str
    source_id: int
    created_at: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class TradeSignalRecord:
    signal_id: int
    signal_type: str
    title: str
    summary: str
    rationale_markdown: str
    signal: dict[str, Any]
    confidence: float
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class DecisionLogRecord:
    decision_id: int
    decision_type: str
    title: str
    summary: str
    rationale_markdown: str
    research_artifact_id: int | None
    signal_id: int | None
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class PositionStateRecord:
    symbol: str
    exposure: float
    direction: str
    thesis: str
    updated_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class PerformanceRecord:
    record_id: int
    metric_name: str
    metric_value: float
    period_label: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class TradingArtifactRecord:
    artifact_id: int
    artifact_type: str
    title: str
    summary: str
    rationale_markdown: str
    research_artifact_id: int
    decision_log_id: int | None
    signal: dict[str, Any]
    confidence: float
    created_at: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ClientProfileRecord:
    client_id: str
    preferred_language: str
    watchlist_topics: list[str]
    response_style: str
    risk_appetite: str
    investment_horizon: str
    institution_type: str
    risk_preference: str
    asset_focus: list[str]
    market_focus: list[str]
    expertise_level: str
    activity: str
    current_mood: str
    emotional_trend: str
    stress_level: str
    confidence: str
    notes: str
    personal_facts: list[str]
    last_active_at: str
    total_interactions: int
    updated_at: str
    timezone_name: str = "Asia/Shanghai"


@dataclass(frozen=True)
class NicknameEntry:
    name: str
    target: str  # "ai" (用户给AI起的) | "user" (AI给用户起的)
    created_by: str  # "user" | "ai"
    context: str = ""
    sentiment: str = ""  # affectionate / playful / casual
    accepted: bool = True
    frequency: int = 0


@dataclass(frozen=True)
class CompanionRelationshipStateRecord:
    client_id: str
    intimacy_level: float  # 0.0-1.0
    relationship_stage: str  # stranger / acquaintance / familiar / close
    tendency_friend: float
    tendency_romantic: float
    tendency_confidant: float
    tendency_mentor: float
    streak_days: int
    total_turns: int
    avg_session_turns: float
    mood_history: list[str]  # last 10 moods
    nicknames: list[dict]  # serialized NicknameEntry dicts
    previous_stage: str  # stage before last transition (for soft regression)
    last_interaction_date: str  # YYYY-MM-DD for streak calc
    last_stage_transition_at: str  # ISO timestamp
    created_at: str
    updated_at: str
    outreach_paused: bool = False
    outreach_paused_at: str = ""
    peak_intimacy_level: float = 0.0
    tendency_damping_json: str = "{}"


@dataclass(frozen=True)
class CompanionCheckInStateRecord:
    client_id: str
    channel: str
    thread_id: str
    enabled: bool
    pending_kind: str
    pending_due_at: str
    last_sent_at: str
    last_sent_kind: str
    cooldown_until: str
    retry_count: int
    updated_at: str

@dataclass(frozen=True)
class CompanionLifestyleStateRecord:
    client_id: str
    channel: str
    thread_id: str
    timezone_name: str
    home_base: str
    work_area: str
    routine_state: str
    last_state_changed_at: str
    last_morning_checkin_at: str
    last_evening_checkin_at: str
    last_weekend_checkin_at: str
    updated_at: str

@dataclass(frozen=True)
class CompanionDailyScheduleRecord:
    client_id: str
    schedule_date: str
    timezone_name: str
    routine_state_snapshot: str
    morning_plan: str
    lunch_plan: str
    afternoon_plan: str
    dinner_plan: str
    evening_plan: str
    current_plan: str
    next_plan: str
    revision_note: str
    last_explicit_update_at: str
    created_at: str
    updated_at: str

@dataclass(frozen=True)
class CompanionSelfStateRecord:
    client_id: str
    channel: str
    thread_id: str
    state_date: str
    timezone_name: str
    routine_state_snapshot: str
    internal_state: list[str]
    opinion_profile: list[str]
    used_callback_facts: list[str]
    last_callback_fact: str
    last_callback_at: str
    last_engagement_mode: str
    last_engagement_reason: str
    created_at: str
    updated_at: str

@dataclass(frozen=True)
class CompanionImageLogRecord:
    image_log_id: int
    client_id: str
    channel: str
    thread_id: str
    mode: str
    scene_key: str
    trigger_type: str  # "reactive" / "proactive" / "explicit"
    outreach_kind: str
    relationship_stage: str
    generated_at: str
    scene_override: bool
    blocked: bool
    block_reason: str


@dataclass(frozen=True)
class CompanionOutreachLogRecord:
    outreach_id: int
    client_id: str
    channel: str
    thread_id: str
    kind: str
    content_raw: str
    content_normalized: str
    sent_at: str
    user_replied: bool
    user_replied_at: str
    created_at: str


@dataclass(frozen=True)
class CompanionReminderRecord:
    reminder_id: int
    client_id: str
    channel: str
    thread_id: str
    reminder_text: str
    due_at: str
    timezone_name: str
    status: str
    created_at: str
    sent_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ConversationMessageRecord:
    message_id: int
    client_id: str
    channel: str
    thread_id: str
    role: str
    content: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class DeliveryQueueRecord:
    delivery_id: int
    client_id: str
    channel: str
    thread_id: str
    source_type: str
    source_artifact_id: int | None
    content_rendered: str
    status: str
    delivered_at: str | None
    client_reaction: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class GroupProfileRecord:
    group_id: str
    group_name: str
    group_topic: str
    group_notes: str
    bot_relational_role: str
    member_count: int
    created_at: str
    updated_at: str

@dataclass(frozen=True)
class GroupMemberRecord:
    group_id: str
    user_id: str
    display_name: str
    role_in_group: str
    personality_notes: str
    relational_role: str
    first_seen_at: str
    last_seen_at: str
    message_count: int
    username: str = ""

@dataclass(frozen=True)
class GroupMessageRecord:
    message_id: int
    group_id: str
    thread_id: str
    user_id: str
    display_name: str
    content: str
    created_at: str

@dataclass(frozen=True)
class DocSourceRecord:
    source_id: str
    source_code: str
    source_name: str
    source_type: str
    country_code: str
    default_language_code: str
    homepage_url: str
    is_active: bool
    created_at: str
    updated_at: str

@dataclass(frozen=True)
class DocReleaseFamilyRecord:
    release_family_id: str
    source_id: str
    release_code: str
    release_name: str
    topic_code: str
    country_code: str
    frequency: str
    default_language_code: str
    created_at: str
    updated_at: str

@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    release_family_id: str
    source_id: str
    canonical_url: str
    title: str
    subtitle: str
    document_type: str
    mime_type: str
    language_code: str
    country_code: str
    topic_code: str
    published_date: str
    published_at: str
    status: str
    version_no: int
    parent_document_id: str
    hash_sha256: str
    created_at: str
    updated_at: str
    published_precision: str = ""
    published_epoch_ms: int = 0
    created_epoch_ms: int = 0
    updated_epoch_ms: int = 0

@dataclass(frozen=True)
class DocumentBlobRecord:
    document_blob_id: str
    document_id: str
    blob_role: str
    storage_path: str
    content_text: str
    content_bytes: bytes | None
    byte_size: int
    encoding: str
    parser_name: str
    parser_version: str
    extracted_at: str

@dataclass(frozen=True)
class DocumentExtraRecord:
    document_id: str
    extra_json: dict[str, Any]
