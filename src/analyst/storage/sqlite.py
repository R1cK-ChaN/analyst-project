from __future__ import annotations

from .sqlite_core import default_engine_db_path
from .sqlite_records import (
    StoredEventRecord,
    CalendarIndicatorRecord,
    CalendarIndicatorAliasRecord,
    MarketPriceRecord,
    CentralBankCommunicationRecord,
    IndicatorObservationRecord,
    IndicatorVintageRecord,
    ObsSourceRecord,
    ObsFamilyRecord,
    ObsFamilyDocumentRecord,
    NewsArticleRecord,
    RegimeSnapshotRecord,
    GeneratedNoteRecord,
    AnalyticalObservationRecord,
    ResearchArtifactRecord,
    TradeSignalRecord,
    DecisionLogRecord,
    PositionStateRecord,
    PerformanceRecord,
    TradingArtifactRecord,
    ClientProfileRecord,
    CompanionCheckInStateRecord,
    CompanionLifestyleStateRecord,
    CompanionDailyScheduleRecord,
    CompanionReminderRecord,
    ConversationMessageRecord,
    DeliveryQueueRecord,
    GroupProfileRecord,
    GroupMemberRecord,
    GroupMessageRecord,
    DocSourceRecord,
    DocReleaseFamilyRecord,
    DocumentRecord,
    DocumentBlobRecord,
    DocumentExtraRecord
)
from .sqlite_calendar_normalization import SQLiteCalendarNormalizationMixin
from .sqlite_documents import SQLiteDocumentMixin
from .sqlite_groups import SQLiteGroupMixin
from .sqlite_market_macro import SQLiteMarketMacroMixin
from .sqlite_memory import SQLiteMemoryMixin
from .sqlite_news import SQLiteNewsMixin
from .sqlite_observation_families import SQLiteObservationFamilyMixin
from .sqlite_portfolio import SQLitePortfolioMixin
from .sqlite_research import SQLiteResearchMixin
from .sqlite_schema import SQLiteSchemaMixin


class SQLiteEngineStore(
    SQLiteSchemaMixin,
    SQLiteResearchMixin,
    SQLiteMarketMacroMixin,
    SQLiteNewsMixin,
    SQLiteMemoryMixin,
    SQLitePortfolioMixin,
    SQLiteGroupMixin,
    SQLiteDocumentMixin,
    SQLiteObservationFamilyMixin,
    SQLiteCalendarNormalizationMixin,
):
    """Compatibility facade composed from feature-specific mixins."""


__all__ = [
    'AnalyticalObservationRecord',
    'CalendarIndicatorAliasRecord',
    'CalendarIndicatorRecord',
    'CentralBankCommunicationRecord',
    'ClientProfileRecord',
    'CompanionCheckInStateRecord',
    'CompanionDailyScheduleRecord',
    'CompanionLifestyleStateRecord',
    'CompanionReminderRecord',
    'ConversationMessageRecord',
    'DecisionLogRecord',
    'DeliveryQueueRecord',
    'DocReleaseFamilyRecord',
    'DocSourceRecord',
    'DocumentBlobRecord',
    'DocumentExtraRecord',
    'DocumentRecord',
    'GeneratedNoteRecord',
    'GroupMemberRecord',
    'GroupMessageRecord',
    'GroupProfileRecord',
    'IndicatorObservationRecord',
    'IndicatorVintageRecord',
    'MarketPriceRecord',
    'NewsArticleRecord',
    'ObsFamilyDocumentRecord',
    'ObsFamilyRecord',
    'ObsSourceRecord',
    'PerformanceRecord',
    'PositionStateRecord',
    'ResearchArtifactRecord',
    'RegimeSnapshotRecord',
    'SQLiteEngineStore',
    'StoredEventRecord',
    'TradeSignalRecord',
    'TradingArtifactRecord',
    'default_engine_db_path',
]
