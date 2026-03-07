from __future__ import annotations

from analyst.storage import SQLiteEngineStore

from .manager import MemoryManager
from .profile import extract_profile_fact_updates
from .render import merge_hydrated_contexts, render_memory_context
from .types import (
    AgentKind,
    MemoryPolicy,
    MemoryScopeKey,
    MemoryScopeKind,
    MemoryVisibility,
    PublishedArtifactRecord,
)


def sales_client_scope(client_id: str, tenant_id: str = "default") -> MemoryScopeKey:
    return MemoryScopeKey(
        tenant_id=tenant_id,
        agent_kind=AgentKind.SALES,
        visibility=MemoryVisibility.PRIVATE,
        scope_kind=MemoryScopeKind.CLIENT,
        scope_id=client_id,
        subject_id=client_id,
    )


def sales_thread_scope(
    client_id: str,
    channel_id: str,
    thread_id: str,
    tenant_id: str = "default",
) -> MemoryScopeKey:
    return MemoryScopeKey(
        tenant_id=tenant_id,
        agent_kind=AgentKind.SALES,
        visibility=MemoryVisibility.PRIVATE,
        scope_kind=MemoryScopeKind.THREAD,
        scope_id=f"{channel_id}:{thread_id}",
        subject_id=client_id,
        thread_id=thread_id,
    )


def research_global_scope(tenant_id: str = "default") -> MemoryScopeKey:
    return MemoryScopeKey(
        tenant_id=tenant_id,
        agent_kind=AgentKind.RESEARCH,
        visibility=MemoryVisibility.PRIVATE,
        scope_kind=MemoryScopeKind.GLOBAL,
        scope_id="main",
    )


def build_sales_memory_context(
    *,
    manager: MemoryManager,
    store: SQLiteEngineStore,
    client_id: str,
    channel_id: str,
    thread_id: str,
    query: str,
) -> str:
    policy = MemoryPolicy()
    client_session = manager.get_session(sales_client_scope(client_id), policy=policy)
    thread_session = manager.get_session(sales_thread_scope(client_id, channel_id, thread_id), policy=policy)
    merged = merge_hydrated_contexts(
        client_session.hydrate(query),
        thread_session.hydrate(query),
    )

    published = store.search_published_artifacts(
        query=query,
        limit=2,
        client_safe_only=True,
        artifact_types=("research_note", "regime_snapshot"),
    )
    if published:
        merged = merge_hydrated_contexts(
            merged,
            _published_artifacts_context(published),
        )
    return render_memory_context(merged)


def record_sales_interaction(
    *,
    manager: MemoryManager,
    store: SQLiteEngineStore,
    client_id: str,
    channel_id: str,
    thread_id: str,
    user_text: str,
    assistant_text: str,
) -> None:
    client_session = manager.get_session(sales_client_scope(client_id))
    thread_session = manager.get_session(sales_thread_scope(client_id, channel_id, thread_id))

    current_facts = {fact.key: fact.value for fact in client_session.hydrate().semantic_facts}
    fact_updates = []
    for update in extract_profile_fact_updates(user_text):
        if current_facts.get(update.key) == update.value:
            continue
        fact_updates.append(
            {
                "key": update.key,
                "value": update.value,
                "confidence": update.confidence,
                "metadata": {},
            }
        )

    store.record_sales_memory_turn(
        client_scope=client_session.scope,
        thread_scope=thread_session.scope,
        channel=channel_id,
        thread_id=thread_id,
        user_text=user_text,
        assistant_text=assistant_text,
        fact_updates=fact_updates,
    )


def _published_artifacts_context(artifacts: list[PublishedArtifactRecord]):
    from .types import HydratedMemoryContext, RetrievedMemoryItem

    return HydratedMemoryContext(
        retrieved_items=[
            RetrievedMemoryItem(
                content=f"{artifact.title}\n{artifact.summary}\n{artifact.content_markdown}",
                score=float(len(artifacts) - index),
                created_at=artifact.created_at,
                metadata={"artifact_type": artifact.artifact_type},
            )
            for index, artifact in enumerate(artifacts)
        ]
    )
