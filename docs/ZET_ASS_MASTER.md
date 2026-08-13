# ZET ASS — AUTONOMOUS PERSONAL AI OPERATING SYSTEM
## MASTER SPECIFICATION (Unified)

> This document merges three source prompts into one canonical spec for the ZET project: (1) the core architecture prompt, (2) the natural-command example library, (3) the autonomous-operator deep-dive. Overlapping sections have been consolidated; nothing from the three sources has been dropped, only de-duplicated and re-ordered into a single build reference.

---

## PART 0 — WHAT ZET ASS IS (AND IS NOT)

ZET ASS is **not**:
- a chatbot
- a command bot
- a collection of hard-coded commands
- a dashboard with AI features
- a simple command executor
- an AI that waits for every step to be spelled out

ZET ASS **is**:
- my private AI operating system and personal digital workforce
- a private autonomous AI operator
- an outcome-driven system, not a command-driven one

Mental model:
- I am the owner.
- ZET is the executive intelligence.
- Agents are employees/specialists.
- Capabilities are departments.
- Tools are instruments.
- Memory is organizational knowledge.
- Missions are objectives.
- Tasks are work.
- Permissions are authority.
- Verification is quality control.
- Automation is operations.

I should be able to speak to ZET naturally, in Uzbek or English, like speaking to a highly capable human executive assistant. I explain **what I want**; ZET figures out **how to do it**. I should never need to know which agent, tool, API, workflow, or integration is required, or in what sequence — ZET discovers and orchestrates that itself.

**The core distinction that must be reflected throughout the entire architecture:**

```
USER SAYS:  WHAT THEY WANT
ZET DECIDES: HOW TO ACHIEVE IT
```

---

## PART 1 — THE CENTRAL PIPELINE

Do NOT build the system around:

```
USER COMMAND → FUNCTION
```

Build it around:

```
USER REQUEST
  → UNDERSTAND INTENT
  → UNDERSTAND DESIRED OUTCOME
  → COLLECT CONTEXT
  → DISCOVER REQUIRED CAPABILITIES
  → CREATE MISSION
  → DECOMPOSE INTO TASKS
  → SELECT AGENTS
  → SELECT TOOLS
  → CHECK PERMISSIONS
  → EXECUTE
  → VERIFY
  → RECOVER IF NECESSARY
  → REMEMBER
  → REPORT
```

Full architectural view (target system diagram):

```
                         USER
                          │
                          ▼
                    NATURAL INPUT
                          │
                          ▼
                 🧠 ZET ASS CORE
                          │
              ┌───────────┴───────────┐
              │                       │
        CONTEXT ENGINE          MEMORY ENGINE
              │                       │
              └───────────┬───────────┘
                          │
                          ▼
                    MISSION ENGINE
                          │
                          ▼
                     PLANNER
                          │
                          ▼
                   TASK GRAPH
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
           AGENTS       TOOLS      SERVICES
              │           │           │
              └───────────┼───────────┘
                          ▼
                       EXECUTE
                          │
                          ▼
                       VERIFY
                          │
                    ┌─────┴─────┐
                    ▼           ▼
                  FIX         APPROVE
                    │           │
                    └─────┬─────┘
                          ▼
                       COMPLETE
                          │
                          ▼
                       MEMORY
                          │
                          ▼
                         USER
```

**Implementation requirement:** do not implement this as one giant monolithic "AI prompt." Build it as real software components — Intent Engine, Context Engine, Memory Engine, Mission Engine, Planner, Task Graph, Agent Registry, Agent Runtime, Agent Factory, Tool Registry, Permission Engine, Approval Engine, Execution Engine, Verification Engine, Recovery Engine, Integration Providers, Device Registry, Automation Engine, Notification Engine, Audit Engine. The LLM is the reasoning component; the application code owns permissions, execution, state, tools, security, memory, verification, and limits. **The model itself must never become the security boundary.**

---

## PART 2 — CAPABILITY ARCHITECTURE

A capability is a high-level ability of ZET. Each capability should expose metadata:

- name, description, supported outcomes, required context
- actions, tools, agents, permissions
- risk level, verification strategy, failure strategies, dependencies

Target capability set:

```
WebsiteCapability        SMMCapability          ContentCapability
InstagramCapability       CameraCapability       DesignCapability
TelegramCapability        ComputerCapability     DeploymentCapability
GitHubCapability          ObsidianCapability     SecurityCapability
ResearchCapability        CommunicationCapability FinanceCapability
BusinessCapability        AutomationCapability   SalesCapability
                          ProjectCapability
```

The system must discover capabilities **dynamically** — not via hard-coded phrase matching.

### Capability composition (critical)

A single request can require multiple capabilities composed together.

```
"Prepare my business for online launch."
  → BusinessCapability + BrandingCapability + WebsiteCapability
    + InstagramCapability + TelegramCapability + SalesCapability
    + AnalyticsCapability + AutomationCapability

"Fix and deploy my project."
  → GitHubCapability + DeveloperCapability + QACapability
    + SecurityCapability + DeploymentCapability + MonitoringCapability
```

Do not create a separate hard-coded workflow per possible sentence — compose capabilities dynamically.

### Agents vs. Tools

- **Agents are workers, not the UI.** The user never thinks "use the SMM agent" — they say "manage my Instagram," and ZET selects SMM Agent, Content Agent, Research Agent, Analytics Agent, Design Agent, etc., based on capability + task requirements.
- **Tools are lower-level execution capabilities** that sit underneath capabilities (e.g. Instagram Capability may use the Instagram API, a browser provider, image generation, an analytics provider, storage). The user never needs to know which tool was selected.

### Instagram as a full capability (example depth)

Must evolve toward: account management, content research, content strategy, post/carousel/reel/story creation, caption creation, visual creation, content calendar, scheduling, publishing, analytics, audience analysis, competitor analysis, engagement analysis, growth strategy, sales content, campaigns, performance optimization.

Do not implement fake integrations. Always clearly distinguish: **REAL / MOCK / PARTIAL / REQUIRES API / REQUIRES AUTHORIZATION / REQUIRES USER APPROVAL / REQUIRES EXTERNAL SERVICE.**

---

## PART 3 — MISSION ENGINE & TASK GRAPH

Every complex request becomes a **Mission**:

```
mission_id
objective
context
constraints
required_outcome
tasks
agents
tools
permissions
risk_level
approval_requirements
deadline
verification_rules
memory_updates
status
priority
```

Mission states:

```
RECEIVED → UNDERSTANDING → DISCOVERING → PLANNING → WAITING_APPROVAL
  → EXECUTING → VERIFYING → RECOVERING → COMPLETED / FAILED / CANCELLED
```

**Task graph** requirements: tasks must support dependencies, parallel execution, sequential execution, retries, timeouts, cancellation, approval, recovery, and verification. Independent tasks run in parallel; dependent tasks run in sequence, e.g.:

```
Research → Strategy → Design → Development → QA → Deployment
```

**Mission memory / continuity:** ZET must remember mission state across sessions. Example — Day 1: "Saytni yarat." Day 2: "Kecha qilgan saytni davom ettir." ZET must know which project/site is meant from mission memory.

**Cross-system reasoning:** ZET must combine information across Obsidian + GitHub + Telegram + Web + Database + Calendar + SMM into a single mission when needed (e.g. "Shu projectni launchga tayyorla.").

**Cross-agent reasoning:** agents contribute results to a shared mission (Research → SMM → Developer → QA → Security), with structured results — avoid uncontrolled agent-to-agent loops.

---

## PART 4 — CONTEXT DISCOVERY ENGINE

Before executing a complex request, search all connected knowledge sources: memory, Obsidian, database, project files, GitHub, Telegram, connected services, device state, previous tasks, current conversation, calendar, connected websites.

Rule: **the engine takes a USER REQUEST and produces RELEVANT CONTEXT** — targeted retrieval, never a full dump.

### Obsidian as the business brain

Obsidian is not just note-taking — it is a primary knowledge source. Potential content: project/business info, brand identity (logo, colors, fonts), contact info (phone, email, address, socials), products/services, pricing, target audience, competitors, decisions, strategy, documentation, research, ideas.

When a request relates to a project, retrieve relevant knowledge automatically via **semantic/targeted retrieval** — never dump the whole vault into a model call.

### Project Profile

Every project should have a structured profile:

```
project_name, description, purpose, owner, business,
target_audience, products, services, brand, logo, colors,
typography, contact_information (phone, email, address,
social_links), website, repository, assets, competitors,
pricing, business_goals, marketing_goals,
technical_requirements, current_status, tasks, deadlines
```

If information is missing, classify it as: **can be discovered / can be safely inferred / must ask the user.** Never invent business facts.

### Reference resolution

ZET must resolve deictic references — "shu", "bu", "o'sha", "mening loyiham", "biznesim", "saytim", "Telegramim", "kechagi loyiha", "oxirgi project", "mana shu" — using conversation context, project memory, Obsidian, task history, recent activity, GitHub, files. If multiple candidates remain ambiguous → ask.

### Source-of-truth priority (on conflicting information)

```
Explicit current user instruction
  → Current project data
  → Authoritative connected source
  → Recent memory
  → Older memory
  → Inference
```
Never silently overwrite conflicting facts.

---

## PART 5 — CLARIFICATION, INFERENCE & APPROVAL INTELLIGENCE

**Rule: SEARCH FIRST. ASK SECOND.** Never ask for information the system already has access to.

Three categories:

| Category | Behavior |
|---|---|
| **A — Info can be found** | Do NOT ask. Retrieve it (e.g. phone number already in Obsidian). |
| **B — Info can be safely inferred** | Infer low-risk operational defaults (responsive, mobile-first, modern, SEO basics, accessibility, performance, clear CTA). |
| **C — Critical info genuinely missing/ambiguous** | Ask — but only the minimum number of questions (e.g. which of two matching projects). |

**Never infer:** phone numbers, addresses, pricing, legal claims, testimonials, business statistics — these must come from real sources, never be fabricated.

### Autonomy levels

```
LEVEL 0  Observe
LEVEL 1  Recommend
LEVEL 2  Prepare
LEVEL 3  Execute
LEVEL 4  Execute + verify
LEVEL 5  Execute + verify + continuously monitor
```
Default for safe actions → **Level 4**. High-risk actions always require approval.

### Risk-based approval

```
LOW RISK    → execute automatically
             (research, draft, analyze, summarize, create private files)
MEDIUM RISK → configurable approval
HIGH RISK   → explicit confirmation required
             (delete data, publish content, send sensitive messages,
              change permissions, financial operations, destructive
              server operations, security configuration changes,
              credential changes, permission escalation, irreversible actions)
```
Never bypass approval requirements.

### Plan visibility

Simple tasks → execute directly. Complex tasks → show a short plan first, e.g.:

> "Men buni 5 bosqichda qilaman: 1) Loyihani topaman 2) Ma'lumotlarni yig'aman 3) Saytni yarataman 4) Test qilaman 5) Tayyor holatini beraman."

Then execute. Don't overwhelm the user with internal technical detail.

---

## PART 6 — EXECUTION, VERIFICATION, SELF-RECOVERY

### Continuous execution

Never stop after the first successful sub-step of a multi-step task.

```
BAD:      "Created repository. DONE."
CORRECT:  Created repository → Built website → Tested → Fixed issues
          → Built production version → Deployed → Verified URL → Reported
```
The task ends only when the requested outcome is actually achieved.

### Verification is mandatory

Never say "Done" just because code executed. Examples:

```
WEBSITE:   build → deploy → HTTP check → page check → links → forms
           → errors → final verification
INSTAGRAM: draft → asset check → caption check → brand check
           → publishing status → verify published result if supported
GITHUB:    modify → tests → typecheck → lint → build → security → verify
TELEGRAM:  send → confirm delivery where possible
CAMERA:    request → receive → analyze
DATABASE:  write → read → verify
```
If verification fails → **do not claim success.**

### Self-recovery

```
FAIL → DIAGNOSE → FIX → RETRY → VERIFY
```
If recovery still fails, report honestly. Guard against uncontrolled loops with hard limits: max iterations, max tool calls, max execution time, max retry count, budget limits, recursion limits.

### Never fake autonomy

If ZET cannot access something, say so — plainly, every time:
- missing credential → say so
- unsupported API operation → say so
- unavailable hardware → say so
- OS restriction blocking an action → say so

Then propose the correct next step. **Never pretend an external action happened when it didn't.**

---

## PART 7 — MEMORY

ZET must remember: projects, decisions, preferences, important facts, workflows, tasks, agents, successful strategies, previous failures, user instructions.

After completing an important mission, store structured results (e.g. for a website: project, technology, repository, deployment, design decisions, important content) — but do **not** store irrelevant temporary detail, and memory must remain privacy-aware and controlled, not a blind log of everything.

---

## PART 8 — PRODUCTION PRINCIPLE (NON-NEGOTIABLE)

This is a real private system, not a demo.

- Never simulate an integration and call it complete.
- Never claim an external action happened unless it actually happened.
- Never fabricate data or sources.
- Never pretend access to devices/APIs that aren't actually connected.
- Always report capability status honestly (REAL / MOCK / PARTIAL / missing).

---

## PART 9 — NATURAL LANGUAGE EXAMPLES (BEHAVIOR SPEC, NOT HARD-CODED PHRASES)

These illustrate the *level of reasoning* ZET must generalize to **any** phrasing of the same intent — Uzbek or English. Never hard-code the literal strings below; they are demonstrations, not a command table.

### 9.1 Website

> "I need a website for this project." / "Menga shu loyiham uchun professional sayt kerak." / "Shu loyiham uchun zo'r sayt kerak. Yasab ber."

ZET must NOT just answer "Sure, I can build a website." It must run the full discovery → build → verify chain:

```
DISCOVER CONTEXT
  Obsidian → project/business/brand/contact info, decisions, docs
  GitHub   → existing repo, code, assets, architecture
  Files    → logos, images, brand assets
  Memory   → prior conversations, decisions, preferences, history
        ↓
DETERMINE WHAT'S MISSING → research externally only if necessary & permitted
        ↓
DETERMINE
  purpose, audience, pages, information architecture, navigation,
  content structure, CTAs, visual direction, brand consistency,
  responsive behavior, SEO requirements, technical architecture,
  integrations, analytics, forms, deployment requirements
        ↓
PLAN → DESIGN → DEVELOP → TEST → QA → SECURITY CHECK → BUILD
  → DEPLOY IF AUTHORIZED → VERIFY (HTTP/pages/links/forms/mobile/
    desktop/accessibility/performance) → SAVE PROJECT INFO → REPORT
```
One sentence in → ZET discovers the entire workflow. This behavior must be a **general system capability**, not a website-specific hack.

### 9.2 Instagram — carousel

> "Instagramimga mana shu mavzu bo'yicha chiroyli carousel tayyorla." / "Prepare a beautiful carousel for my Instagram about this topic."

```
Connected account → brand identity → existing content → audience
  → topic → content strategy → carousel structure → hook → slides
  → CTA → visual direction → design → brand consistency → QA → draft
```
Retrieve real brand colors/fonts/logo/tone/audience/past performance/product info first — never invent business facts. If publishing is requested and permitted: `CREATE → REVIEW → APPROVAL → PUBLISH → VERIFY → MONITOR PERFORMANCE`.

### 9.3 Instagram — daily post

> "Bugun Instagramga post tayyorlab qo'y."

Determine today's content objective, current calendar, recent posts, audience, brand tone, relevant products, trends, available assets, then: `IDEA → HOOK → COPY → VISUAL → CTA → QA → DRAFT`.

### 9.4 Instagram — reels

> "Instagramim uchun shu mavzuda viral reels tayyorla."

```
Topic → audience → trend research → hook → concept → script
  → scene breakdown → voiceover → on-screen text → CTA
  → editing instructions → caption → hashtags → QA
  → (actual production if editing tools are connected)
```

### 9.5 Instagram — stories

> "Bugungi storylarimni o'zing tayyorla."

Business context → today's objective → recent stories → audience → offer → coherent story **sequence** (not isolated slides) → interactive elements → CTA → visual design → QA.

### 9.6 Instagram — weekly management

> "Instagramimni shu hafta o'zing boshqar." / "Manage my Instagram this week."

```
Account audit → recent content analysis → audience analysis
  → competitor research → trend research → weekly strategy
  → content calendar → posts/carousels/reels/stories → schedule
  → performance monitoring
```
Publishing always respects approval permissions.

### 9.7 Instagram — audit

> "Instagramimda nima xato ekanini top."

Review profile, bio, visual identity, content, engagement, posting frequency, hooks, captions, CTA, reels, stories, audience, competitors, growth → classify **CRITICAL / HIGH / MEDIUM / LOW** → propose fixes → if authorized: `AUDIT → PLAN → FIX → VERIFY`.

### 9.8 Instagram — growth strategy

> "Instagramimni o'stirish kerak. O'zing strategiya qil."

Current state → audience → niche → competitors → content performance → growth opportunities → strategy → content pillars → posting system → engagement system → measurement → executable plan.

### 9.9 Product content / launch

> "Shu mahsulotimni Instagramda sotishga tayyorla." / "Yangi mahsulotni Instagramda launch qilamiz." / "Prepare everything needed to launch this product."

```
Product research → launch positioning → audience → teaser
  → pre-launch → launch content → stories/reels/carousel → CTA
  → DM funnel → analytics
```
For a full product launch, ZET composes capabilities dynamically: `PRODUCT ANALYSIS + BUSINESS + BRANDING + WEBSITE + SMM + CONTENT + SALES + TELEGRAM + ANALYTICS + AUTOMATION`.

### 9.10 Telegram

> "Telegram kanalni yaxshilab yurit." / "Telegramimni yaxshila." / "Check my Telegram."

Channel/inbox audit → audience → content history → engagement → content pillars → weekly strategy → posts → visuals → publishing schedule → analytics. For "check my Telegram": surface unread important messages, business messages, customer requests, urgent items, hidden tasks, opportunities, items needing replies — summarized and prioritized. "Reply to the important ones" → draft responses, respecting send-permission rules.

### 9.11 Telegram — sales post

> "Shu mahsulotni Telegramda sotadigan post qil."

Product → audience → pain point → benefit → offer → trust → CTA → contact/order method → QA, using real product/business info from connected sources only.

### 9.12 GitHub / development

> "Check this project and fix it." / "Shu projectni productionga tayyorla." / "Bu narsani ishlamayapti, tuzat."

```
Repo inspection → architecture understanding → reproduce problem
  → inspect logs/code → identify root cause → implementation plan
  → modify code → tests → regression tests → QA → security
  → build → verification → production-readiness report
```
If the fix needs capabilities beyond the Developer Agent, ZET dynamically brings in the right agent(s). Never ask the user to explain obvious technical context that's discoverable.

### 9.13 Business report / daily ops

> "Check my business and tell me what needs my attention today." / "Bugungi biznesim haqida menga qisqa hisobot ber." / "Bugungi kunimni boshqar."

Gather from tasks, projects, sales, SMM, Telegram, messages, analytics, deadlines, business documents, customer info, research, prior decisions → reason over it → return: **what's important, what's urgent, what's going wrong, what opportunities exist, what I should do, what ZET can do for me, what's already being handled** (plus, for a daily-executive-assistant framing: top priorities, meetings, urgent items, deep work, delegate-to-agents, waiting-for-me).

### 9.14 Research

> "Research whether this idea is worth pursuing." / "Shu g'oyani tekshir, ishlaydimi?"

```
Idea understanding → market research → customer problem
  → competitor research → existing solutions → differentiation
  → demand → business model → pricing → technical feasibility
  → risks → opportunities → recommendation
```
Distinguish facts from assumptions; never fabricate research.

### 9.15 Project management

> "Manage this project." / "Hammasini tartibga sol." / "Loyihamni tekshir."

Understand goal → tasks → deadlines → dependencies → owners → agents → progress → blockers → QA → reporting; remember project state so "Continue." later resumes correctly from memory. For open-ended "tartibga sol" — don't blindly modify everything; determine scope from context first, plan, and get approval for anything destructive. For an audit: assess architecture, code quality, security, performance, UX/UI, SEO, database, API, tests, deployment, dependencies, accessibility, business logic → classify **CRITICAL/HIGH/MEDIUM/LOW** → offer fixes.

### 9.16 Meeting prep

> "Ertangi uchrashuvga tayyorla."

Find meeting → participants → prior conversations → project info → relevant docs → research participants/company if useful → prepare briefing, questions, talking points, action items.

### 9.17 New project kickoff

> "Yangi project boshlaymiz."

Ask only genuinely critical missing info, then create: project → objectives → tasks → milestones → agents → documentation → Obsidian structure → GitHub repo if required → dev environment → workflow.

### 9.18 Competitor monitoring (standing automation)

> "Raqobatchilarimni kuzatib tur." / "ZET, create an agent that monitors my competitors every morning."

Identify competitors → create monitoring config → Research Agent → scheduled scans → change detection → content/offer/website monitoring → trend detection → notify on important changes.

### 9.19 Camera / device

> "Check my cameras." / "Check the backyard." / "Tell me if something important happens in the backyard."

One-off check: find relevant camera → verify availability → request snapshot/live data if supported → vision analysis → answer. Standing rule: camera → event detection → rule → vision analysis → notification (Telegram/mobile). Never claim capabilities the actual camera/provider doesn't support.

### 9.20 Computer / remote execution

> "Open my project and run it."

Identify the right connected device → `AUTHENTICATION → PERMISSION → PROJECT → ENVIRONMENT → RUN → LOGS → VERIFY`. Never expose unrestricted shell access to every agent.

### 9.21 Standing automation — morning report

> "Har kuni ertalab menga biznesimni aytib tur."

Create an automation: schedule → business data → sales → SMM → tasks → projects → problems → opportunities → AI analysis → executive summary → Telegram notification.

### 9.22 The "do it for me" verb family

Phrases like `o'zing qil`, `hal qilib ber`, `to'g'rila`, `yasab ber`, `tayyorla`, `ishga tushir`, `nazorat qil`, `tekshir`, `yaxshila`, `tartibga sol` must be interpreted **by context**, never as one literal fixed action — resolve to the underlying desired outcome.

### 9.23 Semantic generalization requirement

Different surface phrasings of the same goal must map to the same underlying capability composition, e.g. all of: *"Instagramimga post kerak." / "Bugun Instagramga nimadir chiqaraylik." / "Instagramimni jonlantirish kerak." / "Shu mahsulotni Instagramda ko'rsat." / "Mana shu mavzuni chiroyli kontentga aylantir."* — ZET must understand semantic intent, not exact strings, and must generalize to requests that were never explicitly programmed.

---

## PART 10 — GUARDRAILS

- **Do not overengineer.** No unnecessary microservices, no technology added just because it sounds impressive. Reuse the existing architecture; extend, don't rewrite blindly.
- **Audit before implementation.** Before touching code: read all docs, inspect the full repo, current architecture, existing agents/tools/memory/integrations/tests; run existing tests; inspect deployment. Identify what's real, what's mocked, what's missing, what's duplicated, and architectural risks.
- **Report before major changes.** Produce an audit covering: current state, what already works, real vs. mocked vs. partial vs. broken vs. missing, architecture/security/memory/agent/tool/integration risks, technical debt, duplication, recommended architecture, implementation priorities, test plan.
- **Incremental migration.** If the current architecture doesn't support this model: identify the gaps, find the smallest safe changes, introduce missing abstractions, preserve working functionality, add tests, migrate incrementally — never a blind full rewrite.

### Implementation priority order

```
1. CAPABILITY REGISTRY
2. MISSION ENGINE
3. CONTEXT ENGINE
4. TASK GRAPH
5. AGENT SELECTION
6. TOOL SELECTION
7. PERMISSION ENGINE
8. APPROVAL ENGINE
9. VERIFICATION ENGINE
10. MEMORY INTEGRATION
```

### First deliverable

Before any implementation, produce:

```
/docs/ZET_ASS_AUTONOMY_AUDIT.md
```
containing: current architecture, existing components, reusable components, missing components, duplicates, risks, recommended changes, implementation order, test plan.

---

## PART 11 — DEFINITION OF DONE

ZET ASS is on the right architecture when a single sentence like:

> "Build a website for this project." / "Menga shu loyiham uchun professional sayt kerak."

results in ZET independently: identifying the project, retrieving its context (Obsidian/GitHub/files/memory), understanding the business, finding assets and contact data, understanding requirements, planning the site, delegating the work, building it, testing it, fixing problems, verifying the result, deploying only if authorized, saving the important project info to memory, and reporting what happened — **asking only for genuinely necessary missing information or approvals.**

The same standard applies to any other one-sentence mission: Instagram carousel, project fix, business management, competitor monitoring, launch prep, etc. — the system must generalize this behavior to **new** requests that were never explicitly programmed, not just the examples listed above.

**Final directive:** start by auditing the existing project. Do not rewrite everything. Understand first → then architect → then implement → then test → then verify.
