# Analyst — Current System Migration Plan

## Status Update

As of March 12, 2026, this migration plan has been partially implemented.

What is now true:

- `analyst-project/` is a standalone Python project
- the live implementation is under `src/analyst/`
- a standalone sibling macro-data service now exists at `/home/rick/Desktop/analyst/macro-data-service`
- the agent/runtime side now talks through a dedicated macro-data client boundary and can consume the external service over HTTP
- local demo data lives under `data/demo/`
- smoke tests live under `tests/`
- the standalone project no longer imports from the sibling `information/` repo at runtime
- the standalone project no longer depends on `agent_maxwell` memory primitives; memory is now product-owned under `src/analyst/memory/` and `src/analyst/storage/`

What remains true:

- the sibling `information/` and `agent_maxwell/` repos are still useful reference material
- the current standalone implementation is still an early product slice, not a production system
- `analyst-project` still carries a compatibility copy of the service-side modules while cutover is completed

For the current implementation snapshot, see `00-overview/Implementation_Status.md`.

## Purpose

This plan describes how Analyst moved away from direct dependence on the current `agent_maxwell/` and `information/` implementations, and how it can still borrow ideas from them without breaking ongoing work.

The key constraint is architectural: both current codebases are still more generic than the Analyst product itself.

- `agent_maxwell/` is a reusable agent framework
- `information/` is a reusable information ingestion and grounding layer
- `analyst-project/` defines the product shape, workstreams, and delivery requirements

So the goal is **not** to dump all Analyst logic into the generic foundations. The goal is to create a clean Analyst product layer that wraps, composes, and gradually absorbs only the product-specific pieces.

---

## Historical Starting Point

### Agent side today

`agent_maxwell/` historically provided:

- the agent loop
- model/provider abstraction
- tool execution
- CLI and UI surfaces

What it does **not** yet provide as Analyst product code:

- Analyst-specific system prompts
- macro regime state logic
- China-focused financial tool adapters
- Sales-agent behavior for RM workflows
- WeCom-facing product wiring

### Information side today

`information/` already provides:

- macro time-series access via `data/macro_data_layer/`
- official report crawling via `gov_report/`
- document parsing via `doc_parser/`
- news ingestion and classification via `news/`
- an exported markdown layer in `6_information_layer/`

What it does **not** yet provide as Analyst-ready product contracts:

- a single Analyst event schema across all source types
- regime-ready derived features
- explicit APIs shaped for WS1/WS4 agent use
- clear freshness/SLA guarantees by source
- a product-facing "research store" and "market state store"

---

## Future State

The future Analyst implementation should look like this conceptually:

```text
Analyst Product Layer
├── analyst-runtime            product-owned orchestration around agent_maxwell
├── analyst-information        product-owned adapters around information
├── analyst-engine             WS1 outputs: briefings, flash notes, regime state
├── analyst-delivery           WS2 outputs: WeCom, publishing, shell behavior
└── analyst-integration        WS4 routing, logging, error handling

Reusable Foundations
├── agent_maxwell/             generic agent framework
├── information/               generic ingestion and grounding systems
└── macro-data-service/        standalone service for ingestion, storage, retrieval, and macro-data APIs
```

Design rule:

- generic capabilities stay in the current repos
- Analyst-specific workflows move into product-owned modules
- only mature, reusable abstractions get pushed back down into foundations
- service consumers should use the macro-data API/client boundary rather than importing ingestion/storage/RAG internals directly

---

## Migration Principles

1. Keep `agent_maxwell/` generic.
Analyst should consume `@maxwell/*` packages, not fork the framework into a finance-specific runtime.

2. Keep `information/` source-focused.
That repo should continue to fetch, parse, normalize, and export data. Product-specific interpretation belongs in Analyst.

3. Migrate by contracts first, not by folder moves.
If contracts are stable, code can live in separate folders temporarily without blocking execution.

4. Add Analyst wrappers before attempting consolidation.
Composition is lower risk than a big-bang repo merge.

5. Preserve independent deployability.
The information layer, agent runtime, and delivery shell should still be runnable separately.

6. Only consolidate after interfaces stabilize.
The right time to restructure folders is after WS1 and WS4 prove the contracts in production-like use.

---

## Recommended Target Layout

This is the future product-owned structure to build toward under the Analyst workspace:

```text
analyst/
├── analyst-project/                 planning and product specs
├── workstreams/                     team coordination
├── analyst-runtime/                 product agent wiring on top of agent_maxwell
├── analyst-information/             product adapters on top of information
├── analyst-engine/                  WS1 engine outputs and scheduled jobs
├── analyst-delivery/                WS2 channel apps and shell services
├── analyst-integration/             WS4 routing and interface layer
├── agent_maxwell/                   reusable foundation
└── information/                     reusable foundation
```

If needed, `analyst-runtime/`, `analyst-information/`, `analyst-engine/`, `analyst-delivery/`, and `analyst-integration/` can begin as thin folders and grow over time.

---

## Migration Phases

### Phase 0: Freeze the Product Contracts

Timeline: immediately

Objective:
Define the interfaces that Analyst needs before moving code.

Deliverables:

- canonical Analyst event schema
- canonical regime-state schema
- canonical research-output schema
- channel-safe response schema for WeCom and future delivery surfaces
- freshness classes for each information source

Key outputs:

- `Event`
- `MarketSnapshot`
- `RegimeState`
- `ResearchNote`
- `DraftResponse`
- `CalendarItem`

Workstreams:

- WS1 defines engine-facing schemas
- WS2 defines delivery-facing schemas
- WS4 validates end-to-end shape

Exit criteria:

- every team can point to the same contract docs
- no new product code directly depends on package-internal data structures unless explicitly approved

---

### Phase 1: Build the Analyst Runtime Layer on Top of `agent_maxwell/`

Timeline: after Phase 0

Objective:
Create a product runtime that uses `agent_maxwell/` as infrastructure while keeping all Analyst behavior outside the framework packages.

What to build:

- Analyst agent configuration layer
- system prompts for Analyst and Sales modes
- tool registration for macro questions, draft generation, meeting prep, and regime summaries
- pipeline-shaped context builders for Research / Trader / Sales workflows
- output renderers for Chinese research and channel-safe drafts

Where it should live:

- new product-owned folder: `analyst-runtime/`

What should stay in `agent_maxwell/`:

- generic tool interface improvements
- generic memory/rendering improvements
- provider or streaming fixes
- generic agent lifecycle features

What should not be added to `agent_maxwell/`:

- China macro prompts
- RM-specific workflow logic
- WeCom rules
- product-specific compliance text

Exit criteria:

- Analyst runtime can run the same agent loop using `@maxwell/agent-core`
- switching models does not require editing Analyst business logic; the current memory implementation is already product-owned inside `src/analyst/`

---

### Phase 2: Build the Analyst Information Adapter Layer on Top of `information/`

Timeline: in parallel with late Phase 1

Objective:
Turn the raw information sources into a product-facing interface for the macro engine.

What to build:

- adapter layer that reads from `information/` outputs
- unified query API for macro data, official releases, news, and parsed documents
- derived features for regime scoring and event interpretation
- source freshness and confidence metadata
- product-safe filters for what can reach downstream generation

Where it should live:

- new product-owned folder: `analyst-information/`

What should stay in `information/`:

- crawlers
- parsers
- exporters
- catalog/index logic
- source-specific fetch behavior

What should move into Analyst-owned code:

- cross-source fusion logic
- regime features
- signal ranking
- engine retrieval recipes
- prompt-ready context assembly for Analyst workflows

Exit criteria:

- the engine no longer reaches directly into random package internals inside `information/`
- all engine reads go through a stable Analyst adapter boundary

---

### Phase 3: Stand Up `analyst-engine/` as the WS1 Product Surface

Timeline: after Phases 1 and 2 are minimally usable

Objective:
Make WS1 a real product module rather than a loose combination of scripts.

What to build:

- scheduled jobs for pre-market, event-driven, and closing outputs
- regime update pipeline
- engine API surface for Q&A, draft, and meeting-prep requests
- output persistence for research notes and structured JSON
- evaluation harness for note quality and factual grounding

Inputs:

- `analyst-runtime/`
- `analyst-information/`

Outputs:

- `ResearchNote`
- `RegimeState`
- `CalendarItem[]`
- `DraftResponse`

Exit criteria:

- WS1 has a single runnable service boundary
- WS2 and WS4 integrate against service contracts, not internal scripts

---

### Phase 4: Connect Delivery Through Stable Service Interfaces

Timeline: after `analyst-engine/` exists

Objective:
Make WS2 and WS4 consume the engine through narrow APIs rather than direct code coupling.

What to build:

- request/response API between delivery shell and engine
- routing layer for Q&A, draft, meeting prep, regime, and calendar requests
- delivery-specific formatting and disclaimers
- interaction logging and trace IDs

Where it should live:

- delivery shell logic in `analyst-delivery/`
- routing and orchestration in `analyst-integration/`

Important rule:

- delivery code should not read directly from `information/`
- delivery code should not construct macro reasoning itself
- delivery code should only call stable engine endpoints

Exit criteria:

- WeCom or any future surface can be swapped without changing WS1 internals

---

### Phase 5: Consolidate Shared Analyst Product Stores

Timeline: after real usage validates schemas

Objective:
Materialize the storage boundaries implied by the product vision.

Stores to add:

- Research Store
- Market State Store
- Interaction Log
- User Context Store

These stores should be product-owned. They are not the same thing as `information/output/` or package-level SQLite files.

Important separation:

- `information/` remains the grounding and ingestion layer
- Analyst stores hold product-ready state and product interaction history

Exit criteria:

- the product can answer, draft, and publish from stable stores without coupling to raw crawler storage

---

### Phase 6: Optional Repository Consolidation

Timeline: only after Phases 1-5 are working

Objective:
Decide whether physical repo consolidation is worth the cost.

Recommended default:

- keep `agent_maxwell/` and `information/` as separate foundations
- keep Analyst product modules as sibling repos/folders in the same workspace

Only consolidate if at least one is true:

- the separate repos create daily developer friction
- version coordination becomes a constant problem
- deployment and testing are materially simpler in a monorepo

If consolidation happens, use this order:

1. move Analyst product modules together first
2. keep foundations vendored or linked as dependencies
3. only then consider deeper monorepo integration

Do **not** begin by moving `agent_maxwell/` or `information/` wholesale under `analyst-project/`.

---

## Current Repo Mapping to Future Analyst Modules

| Current area | Current role | Future role |
|---|---|---|
| `agent_maxwell/packages/agent-core` | generic loop/runtime | dependency of `analyst-runtime/` |
| `agent_maxwell/packages/memory` | generic memory system | historical reference only; not used by current `analyst-project/` |
| `information/data/macro_data_layer` | structured time-series source | dependency of `analyst-information/` |
| `information/gov_report` | official report ingestion | dependency of `analyst-information/` |
| `information/news` | news ingestion and classification | dependency of `analyst-information/` |
| `information/doc_parser` | PDF/report parsing | dependency of `analyst-information/` |
| `analyst-project/code-toolkit` | prototype/reference code | mine for ideas or one-off utilities, not source of truth |

---

## Ownership by Workstream

### WS1

- define engine contracts
- build `analyst-runtime/`
- build `analyst-information/`
- stand up `analyst-engine/`

### WS2

- define delivery-safe response contracts
- build `analyst-delivery/`
- keep channel logic outside engine internals

### WS3

- validate workflow requirements that affect prompts, memory, and delivery formats
- identify compliance constraints that change response templates or storage

### WS4

- enforce narrow interfaces across runtime, engine, and delivery
- own routing, observability, and failure handling

### WS5

- feed back which outputs and workflows actually matter commercially

---

## Major Risks

1. Polluting `agent_maxwell/` with Analyst-specific business logic.
That will slow framework work and make future changes harder.

2. Treating `information/` storage as the product storage model.
Crawler outputs and product stores have different purposes and lifecycles.

3. Moving folders before contracts are stable.
That creates churn without improving delivery speed.

4. Letting WS2 call raw information sources directly.
That bypasses the engine and creates multiple inconsistent reasoning paths.

5. Keeping prototype code as production dependency.
`analyst-project/code-toolkit/` should inform implementation, not become the architecture by accident.

---

## Recommended Next Actions

1. Create contract docs for `Event`, `RegimeState`, `ResearchNote`, `DraftResponse`, and `CalendarItem`.
2. Create empty product-owned folders: `analyst-runtime/`, `analyst-information/`, `analyst-engine/`, `analyst-delivery/`, `analyst-integration/`.
3. Build one thin end-to-end slice:
   macro question in -> Analyst runtime -> Analyst information adapter -> engine response out.
4. After that slice works, decide which generic improvements belong back in `agent_maxwell/` or `information/`.

This sequence keeps the current repos usable while creating a clear path from today's implementation to the future Analyst product.
