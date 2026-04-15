# DataLens Analytics

**White-label AI-powered analytics platform** that connects to your databases and lets users ask questions in natural language. An agentic LLM pipeline translates questions into SQL, executes queries, generates charts, and delivers narrative insights — all in real time via streaming.

![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.12-blue)
![React](https://img.shields.io/badge/react-18-blue)
![TypeScript](https://img.shields.io/badge/typescript-5-blue)

---

## Features

| Feature | Description |
|---|---|
| **Natural Language Analytics** | Ask questions like _"What are the top 5 products by revenue this quarter?"_ and get SQL + charts + narrative |
| **Multi-Database Support** | SQL Server, PostgreSQL, MySQL, Azure Cosmos DB, SQLite, CSV/Excel uploads |
| **Agentic LLM Pipeline** | Multi-step planner → SQL writer → executor → chart recommender → narrative synthesizer |
| **Real-Time Streaming** | Server-Sent Events stream every agent step (thinking, SQL, results, charts) live to the UI |
| **Workspace Intelligence Profiles** | Auto-profiling discovers schema, data nuances, and generates an intelligence playbook |
| **External API Tools** | Managers can add REST APIs as tools — the LLM agent decides whether to query the DB or call an API |
| **4-Layer Guardrails** | Regex filter → Gemini LLM classifier → SQL validator → Response scrubber (no Bedrock needed) |
| **RBAC (3-Tier)** | Admin, Manager, User roles with quota management and approval workflows |
| **Canvas** | Drag-and-drop dashboard builder — pin charts, KPIs, narratives, and tables from chat |
| **Google & GitHub SSO** | OAuth login with auto-provisioning and admin approval flow |
| **GCP Cloud Run Ready** | One-command deployment with included scripts for both Linux and Windows |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│  React 18 + TypeScript + Vite + Zustand + Recharts          │
│  Workspace → Chat (SSE) → Canvas → Admin Dashboard          │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST + SSE
┌──────────────────────────▼──────────────────────────────────┐
│                        Backend                               │
│  FastAPI + LangChain + SSE-Starlette                        │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │  Guardrails  │  │  Agent Graph  │  │  Connection Mgr    │ │
│  │  4 layers    │→ │  Plan → SQL  │→ │  SQL Server,       │ │
│  │              │  │  → Execute   │  │  PostgreSQL, MySQL, │ │
│  │  Regex       │  │  → Chart     │  │  Cosmos DB, SQLite  │ │
│  │  Gemini LLM  │  │  → Narrative │  │                    │ │
│  │  SQL check   │  │  → API tools │  │                    │ │
│  │  Scrubber    │  │              │  │                    │ │
│  └─────────────┘  └──────────────┘  └────────────────────┘ │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │  Profiler    │  │  Auth (JWT)  │  │  Cosmos DB         │ │
│  │  Schema scan │  │  Google SSO  │  │  Persistence:      │ │
│  │  LLM synth   │  │  GitHub SSO  │  │  Users, Workspaces │ │
│  │  Playbook    │  │  RBAC        │  │  Sessions, Canvas  │ │
│  └─────────────┘  └──────────────┘  └────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- An LLM API key (Azure OpenAI, Anthropic via Azure AI Foundry, OpenAI, or use `mock` mode)
- Azure Cosmos DB account (for persistence — users, workspaces, sessions)
- A database to analyze (SQL Server, PostgreSQL, MySQL, Cosmos DB, SQLite, or CSV)

### 1. Clone

```bash
git clone https://github.com/SubhashPavan/DataLens_AINOC.git
cd DataLens_AINOC
```

### 2. Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — fill in your API keys, Cosmos DB credentials, etc.

# Run
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend Setup

```bash
cd frontend
npm install

# Configure
cp .env.example .env
# Edit .env if needed (defaults to http://localhost:8000)

# Run
npm run dev
```

### 4. Open

Navigate to `http://localhost:5174` — log in, create a workspace, connect a database, and start asking questions.

---

## Deployment (Google Cloud Run)

Both a **Bash** script (`deploy.sh`) and a **PowerShell** script (`deploy.ps1`) are included.

### Prerequisites

1. [Install gcloud CLI](https://cloud.google.com/sdk/docs/install)
2. Authenticate: `gcloud auth login`
3. Enable Cloud Run & Cloud Build APIs:
   ```bash
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com
   ```
4. Create your `backend/.env` from `backend/.env.example`

### Deploy

```bash
# Linux/macOS
export GCP_PROJECT_ID=your-project-id
export GCP_REGION=asia-south1  # optional, defaults to asia-south1
chmod +x deploy.sh
./deploy.sh

# Windows PowerShell
$env:GCP_PROJECT_ID = "your-project-id"
.\deploy.ps1
```

The script will:
1. Build & deploy the **backend** as a Cloud Run service
2. Build & deploy the **frontend** (injects `VITE_API_URL` at build time)
3. Print the live URLs

### Post-Deploy

1. Add your frontend URL to **Google OAuth** → Authorized JavaScript Origins & Redirect URIs
2. Optionally lock `CORS_ORIGINS` to your frontend URL

---

## Project Structure

```
DataLens/
├── backend/                    # FastAPI backend
│   ├── app/
│   │   ├── agent/              # LLM agent pipeline
│   │   │   ├── graph.py        # Main orchestration: SSE streaming loop
│   │   │   ├── planner.py      # Multi-step query planner
│   │   │   ├── profiler.py     # Workspace intelligence profiling
│   │   │   ├── prompts.py      # System prompts for each agent role
│   │   │   ├── tools/          # LangChain tools
│   │   │   │   ├── sql_executor.py    # SQL execution with guardrails
│   │   │   │   ├── api_tool_factory.py # Dynamic REST API tools
│   │   │   │   └── ...
│   │   │   └── ...
│   │   ├── api/routes/         # FastAPI route handlers
│   │   │   ├── chat.py         # Chat SSE endpoint
│   │   │   ├── profiles.py     # Profile generation SSE
│   │   │   ├── admin.py        # Admin management
│   │   │   ├── persistence.py  # Workspace/session CRUD
│   │   │   └── ...
│   │   ├── db/                 # Database connectors & query runners
│   │   ├── guardrails/         # 4-layer security pipeline
│   │   │   ├── input_filter.py     # Layer 1: Regex-based filter
│   │   │   ├── llm_classifier.py   # Layer 2: Gemini Flash classifier
│   │   │   ├── sql_validator.py    # Layer 3: SQL output validator
│   │   │   └── response_guard.py   # Layer 4: Response scrubber
│   │   ├── llm/                # LLM provider abstractions
│   │   ├── schemas/            # Pydantic models
│   │   ├── auth/               # Quota management
│   │   └── config.py           # Settings (env-driven via pydantic-settings)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/                   # React + TypeScript + Vite
│   ├── src/
│   │   ├── pages/              # Route-level pages
│   │   │   ├── WorkspaceView.tsx       # Main workspace (chat + canvas)
│   │   │   ├── AdminDashboard.tsx      # Admin management panel
│   │   │   ├── AnalyticsDashboard.tsx  # Usage analytics
│   │   │   └── ...
│   │   ├── components/         # UI components
│   │   │   ├── chat/           # Chat panel, messages, thinking steps
│   │   │   ├── canvas/         # Dashboard canvas with drag-and-drop blocks
│   │   │   ├── workspace/      # Workspace creation, profiles, API tools
│   │   │   └── ...
│   │   ├── hooks/              # React hooks (useChat, useWorkspaceSync)
│   │   ├── store/              # Zustand state management
│   │   ├── services/api.ts     # Backend API client
│   │   └── types/              # TypeScript type definitions
│   ├── Dockerfile
│   ├── nginx.conf
│   └── .env.example
├── data/                       # Utility scripts
├── deploy.sh                   # GCP deployment (Linux/macOS)
├── deploy.ps1                  # GCP deployment (Windows)
├── ARCHITECTURE.md             # Detailed code walkthrough
└── README.md
```

---

## Environment Variables

See [`backend/.env.example`](backend/.env.example) for the full list. Key variables:

| Variable | Required | Description |
|---|---|---|
| `LLM_PROVIDER` | Yes | `anthropic`, `azure`, `openai`, or `mock` |
| `ANTHROPIC_FOUNDRY_KEY` | If anthropic | Azure AI Foundry key for Claude |
| `GOOGLE_API_KEY` | Recommended | Gemini Flash — used for guardrails + quick mode |
| `COSMOS_ENDPOINT` | Yes | Azure Cosmos DB endpoint |
| `COSMOS_KEY` | Yes | Cosmos DB primary key |
| `JWT_SECRET` | Yes | Secret for JWT signing — change in production! |
| `ADMIN_EMAIL` | Yes | Email auto-promoted to admin on first login |
| `GOOGLE_CLIENT_ID` | For SSO | Google OAuth 2.0 Client ID |

---

## API Documentation

Once the backend is running, interactive API docs are available at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Zustand, Recharts, Lucide Icons |
| Backend | Python 3.12, FastAPI, LangChain, SSE-Starlette, Pydantic |
| LLM | Claude (via Azure AI Foundry), GPT-4o (Azure/OpenAI), Gemini Flash |
| Database | Azure Cosmos DB (persistence), SQL Server, PostgreSQL, MySQL, SQLite |
| Auth | JWT + Google OAuth 2.0 + GitHub OAuth |
| Deployment | Docker, Google Cloud Run, nginx |
| Guardrails | Regex filters, Gemini Flash classifier, SQL parser, PII scrubber |

---

## License

MIT
