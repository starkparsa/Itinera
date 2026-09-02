# Architecture: how everything is linked and interacts

**A visual companion to [`decisions.md`](../decisions.md)'s Architecture
section — that section is the prose source of truth for *why* things are
built this way; this document is the *how it's wired* map, for orienting
quickly in a codebase this size. Written 2026-08-30. If the two ever
disagree, trust the code, then flag the mismatch rather than trusting
either doc blindly (same rule `CLAUDE.md` states about itself).**

## 1. System overview — every service and what talks to what

```mermaid
flowchart TB
    subgraph Browser
        U[User]
    end

    subgraph Vercel["Frontend (Next.js, Vercel)"]
        FE[App Router pages/components]
        SA["Server Actions (lib/backend.ts)"]
        AuthJS["Auth.js (auth.ts)"]
    end

    subgraph CloudRun["Backend (FastAPI, Cloud Run)"]
        API["POST /trips/generate\n+ /conversations/*\n+ /auth/*"]
        Auth["auth.py: JWT verify"]
        LLM[llm_service.py]
        Agent[agent_service.py\n3 tool-calling loops]
        Tools[tools.py]
        Weather[weather_service.py]
        DateR[date_resolver.py]
        Cal[calendar_export.py]
        GCal[google_calendar.py]
    end

    subgraph External["External services"]
        Gemini[(Gemini API)]
        Groq[(Groq — Gemini fallback)]
        Google[(Google OAuth /\nCalendar API)]
        OpenMeteo[(Open-Meteo)]
        Frankfurter[(Frankfurter)]
        Wikipedia[(Wikipedia API)]
    end

    subgraph Data
        Neon[(Neon Postgres)]
    end

    U -->|HTTPS| FE
    FE --> SA
    SA -->|"mints short-lived JWT\n(mintBackendJwt.ts)"| API
    AuthJS -->|OAuth login/consent| Google
    AuthJS -->|"stores session,\nmints backend JWT"| SA

    API --> Auth
    Auth -->|verified user| API
    API --> LLM
    API --> Agent
    API --> Weather
    API --> DateR
    API --> Cal
    API --> GCal

    LLM -->|structured output +\nfunction calling| Gemini
    LLM -.->|on 429 quota| Groq
    Agent --> Tools
    Tools -->|convert_currency| Frankfurter
    Tools -->|get_place_context| Wikipedia
    Weather --> OpenMeteo
    GCal -->|push events,\nrefresh tokens| Google

    API <-->|SQLAlchemy| Neon
```

## 2. The single request-router: `POST /trips/generate`

Every user message — new trip, edit, follow-up question, off-topic — goes
through **one** handler ([`routers/trips.py`](../backend/app/routers/trips.py)).
There is no separate chat/message endpoint. This is the fork point for
the entire backend:

```mermaid
flowchart TD
    Start(["POST /trips/generate\n{prompt, conversation_id?}"]) --> AuthCheck["auth.get_current_user\n(verify JWT, 401 if invalid)"]
    AuthCheck --> Resolve["Resolve/create Conversation\n(ownership-scoped to this user)"]
    Resolve --> Classify["llm_service.classify_intent\n(ONE Gemini call, before anything\nelse runs — principle #1)"]

    Classify -->|off_topic| OffTopic["Fixed decline string\n(no LLM, no further work)"]
    Classify -->|question| QBranch
    Classify -->|new_trip / edit_trip| PBranch

    subgraph QBranch["question branch"]
        direction TB
        Q1["Gather grounding:\ncached agent_context (currency/place)\n+ live weather (weather_service)\n+ on-demand date_resolver if needed"]
        Q2["agent_service.answer_question_with_tools\n(QA tool loop — get_place_context,\nbrief-by-default, tour-guide persona\naware)"]
        Q3{"Got a reply?"}
        Q4["Fallback:\nllm_service.answer_question\n(no tools, plain chat completion)"]
        Q5["Prepend 'Tour guide mode on.'\nif this turn activated it\n(deterministic, not LLM-worded)"]
        Q1 --> Q2 --> Q3
        Q3 -->|no| Q4 --> Q5
        Q3 -->|yes| Q5
    end

    subgraph PBranch["new_trip / edit_trip branch"]
        direction TB
        P0["conversation.tour_guide_mode = False\n(unconditional — talking about\nplanning again always clears it)"]
        P1["llm_service.generate_itinerary\n_infer_trip_meta (destination, day count)\n+ concurrent gather step:\n  currency loop, place-context loop\n(both agent_service.py, once per\nconversation, cached after)"]
        P2["_generate_chunk per CHUNK_SIZE_DAYS\nwindow (structured output,\nresponse_schema)"]
        P3["date_resolver.resolve_trip_start_date"]
        P4["Create Trip + ItineraryItem rows"]
        P5["weather_service: fetch + cache\nper-day forecast for the trip"]
        P0 --> P1 --> P2 --> P3 --> P4 --> P5
    end

    OffTopic --> Persist
    Q5 --> Persist
    P5 --> Persist["Append user + assistant Message rows,\ncommit. This IS the memory —\nno separate store."]
    Persist --> Response(["TripResponse JSON"])
```

## 3. The three isolated tool-calling loops

`agent_service.py` runs three **deliberately separate** Gemini
function-calling loops — same underlying mechanism, different flags,
different schemas, different caching rules, on purpose (so flipping one
loop's kill switch can never make another loop's tool reachable, and so
each loop's caching behavior matches what that data actually needs — see
[`decisions.md`](../decisions.md)'s "Place context" entry for the full reasoning):

```mermaid
flowchart LR
    subgraph "gather_trip_context (currency)"
        direction TB
        C1["AGENT_TOOL_CALLING_ENABLED\n(currently False — paused,\nproduct decision)"]
        C2["tools.CURRENCY_TOOL_SCHEMAS\n(convert_currency only)"]
        C3["Cached forever in\nConversation.agent_context\n(once per conversation)"]
        C1 -.-> C2 -.-> C3
    end

    subgraph "answer_question_with_tools (Q&A place context)"
        direction TB
        Q1["QA_TOOL_CALLING_ENABLED\n(True)"]
        Q2["tools.QA_TOOL_SCHEMAS\n(get_place_context only)"]
        Q3["NEVER cached —\nfresh every question turn\n(a different place can be\nasked about each time)"]
        Q1 --> Q2 --> Q3
    end

    subgraph "gather_place_context_for_itinerary (planning)"
        direction TB
        P1["PLANNING_TOOL_CALLING_ENABLED\n(True)"]
        P2["tools.PLANNING_TOOL_SCHEMAS\n(get_place_context only)"]
        P3["Cached forever in\nConversation.agent_context\n(once per conversation,\nsame slot currency uses)"]
        P1 --> P2 --> P3
    end

    Tool["tools.get_place_context()\n(clients/wikipedia_client.py)"]
    Q2 -.->|same underlying tool fn| Tool
    P2 -.->|same underlying tool fn| Tool
```

## 4. Data model

```mermaid
erDiagram
    User ||--o{ Conversation : owns
    User ||--o{ Trip : owns
    User ||--o| GoogleCalendarCredential : "has (0 or 1)"
    Conversation ||--o{ Message : contains
    Conversation |o--o{ Trip : "produced (nullable FK,\nSET NULL on delete)"
    Trip ||--o{ ItineraryItem : contains
    Message }o--o| Trip : "optionally references\n(the trip it produced)"

    User {
        int id PK
        string email
        string google_sub "OIDC sub, real auth join key"
    }
    Conversation {
        int id PK
        int user_id FK
        string title
        text agent_context "cached tool findings"
        bool tour_guide_mode
    }
    Message {
        int id PK
        int conversation_id FK
        string role "user | assistant"
        text content
        int trip_id FK "nullable"
    }
    Trip {
        int id PK
        int user_id FK
        int conversation_id FK "nullable, SET NULL"
        string destination
        date start_date "nullable — resolved deterministically"
        text weather_json "cached forecast"
    }
    ItineraryItem {
        int id PK
        int trip_id FK
        int day_number
        string time_of_day
        text activity
    }
    GoogleCalendarCredential {
        int id PK
        int user_id FK
        text encrypted_access_token
        text encrypted_refresh_token
    }
```

Two relationship details worth calling out because they're easy to miss
reading the models alone:

- `Trip.conversation_id` is `ON DELETE SET NULL`, not cascade — deleting a
  chat unlinks its trips rather than deleting them.
- `Message.trip_id` is only ever set for `new_trip`/`edit_trip` turns —
  a `question`-intent turn's assistant `Message` always has `trip_id =
  NULL`, which is *why* `tour_guide_mode` had to be exposed on
  `ConversationDetail` rather than `TripResponse` (see
  [`progress.md`](../progress.md)'s 2026-08-29 tour-guide-mode-refinements
  entry) — a question-turn message has no trip to attach a field to.

## 5. Auth: the BFF (backend-for-frontend) pattern

Neither service trusts the other's raw session state — Next.js owns the
real Google OAuth session, FastAPI only ever sees a short-lived,
purpose-built JWT:

```mermaid
sequenceDiagram
    participant B as Browser
    participant N as Next.js (Auth.js)
    participant G as Google OAuth
    participant F as FastAPI

    B->>N: Click "Continue with Google"
    N->>G: OAuth redirect (consent screen)
    G->>N: Authorization code
    N->>G: Exchange for tokens
    N->>N: Store session (Auth.js JWT\nsession strategy — its own\ncookie, separate concept)
    N->>N: jwt callback also mints a\nCalendar credential row via\nPOST /auth/google-calendar-token

    Note over B,F: Every later page load / Server Action:
    B->>N: Request (with Auth.js session cookie)
    N->>N: mintBackendJwt(sub, email)\n60-second expiry, HS256,\nsigned with AUTH_BACKEND_SECRET
    N->>F: Authorization: Bearer <jwt>
    F->>F: auth.get_current_user:\nverify signature + algorithm,\ndecode sub, auto-provision\nUser row if new
    F->>N: Response, scoped to that\nverified user only
    N->>B: Rendered page / JSON
```

`AUTH_BACKEND_SECRET` is the one shared secret both services read from
the same root `.env` — a mismatch between them 401s every single backend
call, the most common real misconfiguration in this flow.

## 6. Frontend: component and state ownership

```mermaid
flowchart TD
    Page["app/page.tsx (Server Component)\nredirects to /login if unauthenticated,\nfetches initial conversation list"]
    ChatApp["ChatApp.tsx (Client Component)\nowns: conversations, activeConversationId,\nmessages, pendingPrompt, error, tourGuideMode"]
    Sidebar["Sidebar.tsx\nconversation list, new chat,\nsign out"]
    ChatMessage["ChatMessage.tsx\nrenders one message bubble"]
    TripView["TripView.tsx\nrenders itinerary + weather\n+ agent findings for a message\nwith an attached Trip"]
    CalPush["CalendarPushButton.tsx\n('Export Plan')"]
    ChatInput["ChatInput.tsx\ntextarea + send"]

    Page --> ChatApp
    ChatApp --> Sidebar
    ChatApp --> ChatMessage
    ChatApp --> ChatInput
    ChatApp -->|topExportTrip| CalPush
    ChatMessage --> TripView
    TripView --> CalPush

    subgraph "lib/backend.ts — the ONLY place that calls FastAPI"
        direction LR
        generateTrip
        getConversation
        listConversations
        deleteConversation
        pushTripToCalendar
    end

    ChatApp -.->|Server Actions| generateTrip
    ChatApp -.-> getConversation
    ChatApp -.-> listConversations
    ChatApp -.-> deleteConversation
    CalPush -.-> pushTripToCalendar
```

`tourGuideMode` state (drives the amber accent override, see
`globals.css`'s `[data-tour-guide-mode="true"]` block) is set from
whatever `getConversation` last reported — no separate toggle logic, it
just reflects the backend's `ConversationDetail.tour_guide_mode` field
directly.

## 7. Deployment topology (once `docs/deployment-guide.md` is followed)

```mermaid
flowchart LR
    Browser -->|HTTPS| VercelEdge["Vercel\n(frontend, Next.js)"]
    VercelEdge -->|"BACKEND_URL,\nAuthorization: Bearer JWT"| CloudRun["Cloud Run\n(backend, FastAPI,\nscales 0→N)"]
    CloudRun -->|DATABASE_URL| Neon[(Neon Postgres)]
    VercelEdge -.->|OAuth| GoogleAuth[(Google OAuth)]
    CloudRun -.->|refresh tokens,\npush events| GoogleCal[(Google Calendar API)]
    CloudRun -.-> Gemini[(Gemini API)]
    CloudRun -.-> Groq[(Groq)]
```

Local dev mirrors this topology exactly (same Neon instance, same
external APIs) — the only thing that changes between local and deployed
is where the frontend/backend processes themselves run, per
`docker-compose.yml` vs. the individual `preview_start`/`uvicorn --reload`
paths documented in `README.md`.
