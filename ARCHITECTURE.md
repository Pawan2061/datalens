# DataLens Architecture & Code Walkthrough

This document provides a deep-dive into the DataLens codebase — how data flows from a user question to a rendered chart, how the agent pipeline works, and how each subsystem is structured.

---

## Table of Contents

1. [High-Level Flow](#1-high-level-flow)
2. [Backend: Agent Pipeline](#2-backend-agent-pipeline)
3. [Backend: Database Layer](#3-backend-database-layer)
4. [Backend: Guardrails](#4-backend-guardrails)
5. [Backend: Authentication & RBAC](#5-backend-authentication--rbac)
6. [Backend: Workspace Intelligence Profiles](#6-backend-workspace-intelligence-profiles)
7. [Backend: External API Tools](#7-backend-external-api-tools)
8. [Frontend: State Management](#8-frontend-state-management)
9. [Frontend: Chat & Streaming](#9-frontend-chat--streaming)
10. [Frontend: Canvas](#10-frontend-canvas)
11. [Frontend: Admin Dashboard](#11-frontend-admin-dashboard)
12. [Deployment Architecture](#12-deployment-architecture)

---

## 1. High-Level Flow

```
User types question
        │
        ▼
[Frontend] ChatInput → useChat hook → POST /api/chat
        │
        ▼
[Backend] chat.py route
        │
        ├── Guardrail Layer 1: Regex input filter (instant)
        ├── Guardrail Layer 2: Gemini LLM classifier (async, 5s timeout)
        ├── Quota check (daily questions / tokens / cost)
        │
        ▼
[Backend] graph.py → Agent orchestration loop
        │
        ├── Load workspace profile (system prompt enrichment)
        ├── Load external API tools (dynamic LangChain tools)
        │
        ▼
[LLM] Claude/GPT-4o decides tool calls:
        │
        ├── write_sql_query → SQL generation
        ├── execute_sql_query → Query runner + Layer 3 SQL validator
        ├── analyze_results → Narrative synthesis
        ├── recommend_chart → Chart type recommendation
        ├── [dynamic API tools] → External REST API calls
        │
        ▼
[Backend] Streams events via SSE:
        │  thinking, sql_generation, sql_result, chart_recommendation,
        │  analysis, final_result, api_call_start, api_call_result, done
        │
        ▼
[Frontend] EventSource listens → updates chat messages in real time
        │
        ├── ThinkingSteps: shows each agent step with icons
        ├── MessageBubble: renders narrative + chart + data table
        └── Canvas: user can pin results as dashboard blocks
```

---

## 2. Backend: Agent Pipeline

### Entry Point: `app/api/routes/chat.py`

The chat endpoint receives a user message, validates it through guardrails, and spawns the agent graph.

**Key flow:**
1. `POST /api/chat` → Validates input → Creates an `asyncio.Queue`
2. Spawns `graph.run_agent_stream()` as a background task
3. Returns `{session_id, status: "streaming"}`
4. Client connects to `GET /api/chat/stream/{session_id}` (SSE)

### Orchestration: `app/agent/graph.py`

This is the core of the system. It runs a LangChain-style tool-calling loop:

```python
# Simplified flow
tools = ALL_TOOLS + dynamic_api_tools  # Built-in + workspace API tools
messages = [system_prompt, user_message]

while True:
    response = await llm.invoke(messages, tools=tools)

    if response.has_tool_calls:
        for tool_call in response.tool_calls:
            result = await execute_tool(tool_call)
            emit_sse_event(tool_call.name, result)
            messages.append(tool_result)
    else:
        # LLM produced final text answer
        break

emit_sse_event("final_result", insight_result)
```

**Built-in tools** (`app/agent/tools/`):

| Tool | File | Purpose |
|---|---|---|
| `get_schema_info` | `schema_tool.py` | Returns database schema (cached) |
| `write_sql_query` | `sql_writer.py` | Generates SQL from natural language |
| `execute_sql_query` | `sql_executor.py` | Runs SQL against the connected DB |
| `analyze_results` | `synthesizer.py` | Generates narrative from query results |
| `recommend_chart` | `chart_tool.py` | Picks optimal chart type + config |
| `clarify_question` | `clarify_tool.py` | Asks user for clarification |

### System Prompts: `app/agent/prompts.py`

The agent's system prompt is dynamically composed:
1. **Base prompt**: Role definition, tool usage instructions
2. **Profile context**: If a workspace intelligence profile exists, it's injected as a data briefing with schema details, data nuances, and query guidance
3. **API tool descriptions**: If external APIs are configured, their descriptions are appended so the LLM knows when to use them

### Analysis Modes

- **Quick mode** (`analysis_mode=quick`): Uses Gemini Flash for simple questions — faster, free tier
- **Deep mode** (`analysis_mode=deep`): Uses Claude/GPT-4o for complex multi-step analysis

The `pre_planner.py` optionally pre-analyzes the question to choose the best approach.

---

## 3. Backend: Database Layer

### Connection Manager: `app/db/connection_manager.py`

Central registry of all database connections. Each connection has:
- A unique ID (UUID)
- Configuration (host, port, database, credentials)
- A connector type (sqlserver, postgresql, mysql, cosmosdb, sqlite, file)

Connections are persisted in Cosmos DB (`connections` container) and restored on server startup.

### Query Runner: `app/db/query_runner.py`

Executes SQL against the connected database. Features:
- **Timeout protection**: Configurable max query timeout
- **Row limit**: Configurable max rows returned
- **Connection pooling**: Uses SQLAlchemy engines with connection pools
- **Cosmos DB**: Uses Cosmos SQL API (not standard SQL)

### Schema Inspector: `app/db/schema_inspector.py`

Introspects database schema (tables, columns, types, row counts). Results are cached with configurable TTL (`SCHEMA_CACHE_TTL`).

---

## 4. Backend: Guardrails

A 4-layer defense system that operates without AWS Bedrock:

### Layer 1: Input Filter (`app/guardrails/input_filter.py`)
- **Cost**: Zero (pure regex)
- **Speed**: < 1ms
- **Detects**: SQL injection patterns (12 regexes), prompt injection (19 regexes), dangerous SQL keywords, PII extraction attempts
- **Action**: BLOCK (immediate reject) or FLAG (log + continue)

### Layer 2: LLM Classifier (`app/guardrails/llm_classifier.py`)
- **Cost**: Free (Gemini Flash 2.0)
- **Speed**: 1-5 seconds
- **Detects**: Semantic attacks that bypass regex — social engineering, indirect injection, obfuscated payloads
- **Action**: Classifies as safe/suspicious/malicious with confidence score
- **Fails open**: If Gemini is unavailable, returns PASS

### Layer 3: SQL Validator (`app/guardrails/sql_validator.py`)
- **Cost**: Zero (SQL parsing)
- **Speed**: < 1ms
- **Validates**: Generated SQL before execution
- **Blocks**: DML/DDL (INSERT, UPDATE, DELETE, DROP), system table access, dangerous functions (xp_cmdshell, EXEC), stacked queries
- **Whitelists**: Only SELECT and EVALUATE (DAX)

### Layer 4: Response Scrubber (`app/guardrails/response_guard.py`)
- **Cost**: Zero (regex)
- **Speed**: < 1ms
- **Scrubs**: Connection strings, API keys (AWS/Google/GitHub/Slack), JWT secrets, SSNs, credit card numbers, Bearer tokens from final output

---

## 5. Backend: Authentication & RBAC

### Auth Flow (`app/api/routes/users.py`)

1. **Login**: Google OAuth or GitHub OAuth → Backend verifies token → Creates/finds user in Cosmos DB → Issues JWT (72h expiry)
2. **Request auth**: `get_current_user` dependency extracts JWT from `Authorization: Bearer <token>` header
3. **Role gates**: `get_admin_user` (admin only), `get_manager_or_admin` (manager + admin)

### Roles

| Role | Permissions |
|---|---|
| **admin** | Full access: manage users, all workspaces, approve accounts, view analytics |
| **manager** | Create workspaces, manage own workspaces, add members, configure API tools |
| **user** | Chat within assigned workspaces only |

### Quota System (`app/auth/quota.py`)

Each user has configurable limits:
- `max_questions_per_day`
- `max_tokens_per_day`
- `max_cost_usd_per_month`

Counters auto-reset daily/monthly. Admins manage limits via the dashboard.

---

## 6. Backend: Workspace Intelligence Profiles

### What It Does

When a workspace is created with a database connection, the profiler automatically:

1. **Discovers schema** — Lists all tables/containers
2. **Profiles each table** — Samples rows, computes statistics (distinct counts, null %, min/max/avg, top values)
3. **Detects data nuances** — Arrays, nested objects, high-null columns, unusual types
4. **LLM synthesis** — Generates an intelligence briefing: executive summary, data architecture, KPIs, directional questions
5. **Formats profile text** — Markdown injected into the agent's system prompt

### Key Files

- `app/agent/profiler.py` — Main generation pipeline (5 steps)
- `app/api/routes/profiles.py` — REST + SSE endpoints for generate/stream/status
- `app/schemas/profile.py` — Pydantic models (DataProfile, DirectionalQuestion, etc.)

### SSE Streaming

Profile generation emits progress events via SSE so the UI shows real-time status. The backend supports two modes:
- **Queue-based** (same instance): Real-time events from an in-memory asyncio.Queue
- **Polling fallback** (Cloud Run multi-instance): Polls Cosmos DB status every 3 seconds

---

## 7. Backend: External API Tools

### Overview

Managers can configure external REST APIs as workspace tools. The LLM agent autonomously decides whether to query the database or call an external API based on the user's question.

### Configuration Flow

1. Manager opens Admin Dashboard → Workspace → "API Tools"
2. Adds an API tool with: name, endpoint URL, method, parameters, auth config, response path
3. Tool is saved to Cosmos DB (`api_tools` array on workspace document)

### Runtime: `app/agent/tools/api_tool_factory.py`

At chat time:
1. Workspace's `api_tools` are loaded from Cosmos DB
2. Each config is converted to a LangChain `StructuredTool` using `pydantic.create_model()` for dynamic input schemas
3. Tools are appended to the agent's tool list
4. System prompt is augmented with API descriptions

**Security features:**
- SSRF protection (blocks private IPs)
- Auth injection (API key / Bearer token added at runtime, not exposed to LLM)
- Response path extraction (dot-notation to extract relevant data from API responses)
- Configurable timeout

---

## 8. Frontend: State Management

Uses **Zustand** with `persist` middleware for offline-capable state:

### Stores

| Store | File | Purpose |
|---|---|---|
| `authStore` | `store/authStore.ts` | User, token, role flags, login/logout |
| `workspaceStore` | `store/workspaceStore.ts` | Workspaces, connections, active workspace |
| `chatStore` | `store/chatStore.ts` | Messages, sessions, streaming state |
| `canvasStore` | `store/canvasStore.ts` | Canvas blocks, layout, pinned insights |

### Key Patterns

- **Persisted to localStorage**: Auth token, workspace list, chat history
- **Synced to Cosmos DB**: `useWorkspaceSync` hook syncs local state with backend
- **Hydration-safe**: API calls read token from localStorage as fallback (handles zustand async hydration)

---

## 9. Frontend: Chat & Streaming

### Hook: `hooks/useChat.ts`

The core chat hook manages the full lifecycle:

1. **Send message**: `POST /api/chat` with session ID, message, connection ID, analysis mode
2. **Connect SSE**: `new EventSource(/api/chat/stream/{session_id})`
3. **Process events**: Each SSE event type updates the message state:

| Event | UI Update |
|---|---|
| `thinking` | Shows agent step in ThinkingSteps |
| `sql_generation` | Shows SQL code block |
| `sql_result` | Shows data table preview |
| `chart_recommendation` | Shows chart config |
| `analysis` | Shows narrative text |
| `api_call_start` | Shows "Calling API..." indicator |
| `api_call_result` | Shows API response summary |
| `final_result` | Renders complete InsightCard (narrative + chart + table) |
| `done` | Closes SSE connection |

### Components

- **ChatPanel** (`components/chat/ChatPanel.tsx`): Container with input + message list
- **MessageBubble** (`components/chat/MessageBubble.tsx`): Renders individual messages with compact insight preview, expand/collapse, follow-up questions
- **ThinkingSteps** (`components/chat/ThinkingSteps.tsx`): Animated step-by-step agent progress
- **ChartRenderer** (`components/insights/ChartRenderer.tsx`): Renders bar, line, pie, area, scatter charts via Recharts

---

## 10. Frontend: Canvas

The canvas is a drag-and-drop dashboard builder where users pin insights from chat.

### Block Types

| Block | Component | Source |
|---|---|---|
| Chart | `blocks/ChartBlock.tsx` | Pinned from chart in chat |
| KPI | `blocks/KpiBlock.tsx` | Pinned metric card |
| Narrative | `blocks/NarrativeBlock.tsx` | Pinned text summary |
| Table | `blocks/TableBlock.tsx` | Pinned data table |
| Deep Analysis | `blocks/DeepAnalysisBlock.tsx` | Full insight with all components |

### Persistence

Canvas state is synced to Cosmos DB via `PUT /api/workspaces/{id}/canvas`. Each block stores its type, position, size, and data payload.

---

## 11. Frontend: Admin Dashboard

### File: `pages/AdminDashboard.tsx`

A full management console with sections:

| Section | Features |
|---|---|
| **Dashboard** | Stats cards (users, workspaces, queries, cost), top workspaces |
| **Workspaces** | Create/delete workspaces, manage members, API tools, open workspace |
| **Managers** | View manager-workspace assignments |
| **Users** | Approve/suspend users, set quotas, change roles, delete accounts |
| **Usage** | Query logs, token usage, cost tracking |

### Analytics: `pages/AnalyticsDashboard.tsx`

Charts showing trends over 7d/30d/90d:
- Query volume trends
- Token usage distribution
- Cost breakdown by user
- Mode distribution (quick vs deep)
- Model distribution

---

## 12. Deployment Architecture

### Docker

Both services use multi-stage Docker builds:

**Backend** (`backend/Dockerfile`):
- Base: Python 3.12
- Installs requirements, copies app code
- Runs uvicorn on port 8080
- Env vars injected at runtime via Cloud Run

**Frontend** (`frontend/Dockerfile`):
- Stage 1: Node 20 Alpine — `npm ci` + `npm run build` (Vite)
- Stage 2: nginx Alpine — serves static files
- Build args (`VITE_API_URL`, `VITE_GOOGLE_CLIENT_ID`) baked into the JS bundle
- nginx on port 8080 with SPA routing

### Google Cloud Run

```
Internet → Cloud Run (Frontend) → nginx → Static React SPA
                                           │
                                           │ AJAX/SSE
                                           ▼
           Cloud Run (Backend) → FastAPI → LLM APIs
                                         → Cosmos DB
                                         → User Databases
```

**Backend service config:**
- Memory: 1 GiB
- CPU: 1 vCPU
- Timeout: 600s (SSE streams need long connections)
- Min instances: 0 (scale to zero)
- Max instances: 3

**Frontend service config:**
- Memory: 512 MiB
- CPU: 1 vCPU
- Min instances: 0
- Max instances: 3

### Environment Variable Flow

1. Secrets stored in `backend/.env` (never committed)
2. Deploy script generates `_deploy_env.yaml` from `.env`
3. `gcloud run deploy --env-vars-file` injects into Cloud Run
4. `pydantic-settings` reads from env vars at runtime
5. Frontend build args baked into JS at Docker build time

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **SSE over WebSocket** | Simpler, works through all proxies/CDNs, one-directional (server→client) is sufficient |
| **In-memory queues for SSE** | No Redis dependency. Polling fallback handles multi-instance |
| **Zustand over Redux** | Simpler API, built-in persist, TypeScript-first |
| **LangChain tools (not raw function calling)** | Structured tool definitions, easy to add new tools, works across LLM providers |
| **Cosmos DB for persistence** | Serverless, global distribution, JSON-native, partition key flexibility |
| **Gemini Flash for guardrails** | Free tier, fast, good enough for classification. No Bedrock dependency |
| **Dynamic API tools via pydantic.create_model** | Tools configured at runtime by managers, no code changes needed |
| **Profile injected into system prompt** | Agent has full data context without repeated schema lookups |
