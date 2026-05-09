# The Oracle Problem: Building a Conversational Agent That Actually Knows Things

## Take-Home Engineering Project — Pedestal AI

**Time Budget:** 5–7 days  
**Submission:** GitHub repository (public or invite-only) with deployed demo link

---

## Context

You're joining a team that builds AI agents for enterprise customers in the customs brokerage and trade analytics space. Our customers rely on these agents to answer complex questions against their import data — questions like "What was my total Section 301 exposure from China in Q1?" or "Which HTS codes drove the most duty spend last quarter?"

The hard part isn't the LLM. The hard part is making the LLM *correct* — grounding it in domain knowledge so it doesn't hallucinate tariff rates, misinterpret column semantics, or silently drop entries from aggregations.

This project asks you to build a working prototype of that system.

---

## What You're Building

A **conversational Q&A agent** with a **knowledge layer** that can answer natural language questions about U.S. customs entry data. The system has two core components:

### 1. Knowledge-Augmented Query Engine
The agent must ingest and use a set of domain knowledge documents (provided as plain text files) to correctly interpret questions and produce accurate answers from a flat-file dataset (provided as CSV).

**The knowledge documents define:**
- Core customs brokerage concepts (entry numbers, dates, ports, BOLs)
- Duty and fee calculation rules (HTS codes, tariff stacking, Section 301, IEEPA, MPF, HMF)
- Customer profiles and QBR metric definitions
- Data dictionary with column semantics and known data quirks
- Business rules for analytics (which date field to use, entry count vs. line count, etc.)

**The dataset is:** ~4,500 tariff line records across ~1,200 customs entries for 3 customers, spanning October 2024 through March 2025.

### 2. Conversational Interface
A chat UI where a user can ask questions in natural language and receive answers grounded in both the data and the knowledge base. The agent should:
- Parse the user's intent
- Retrieve relevant knowledge items to inform its approach
- Query/compute against the CSV data
- Return a clear, accurate answer with supporting context
- Handle follow-up questions and multi-turn conversation

---

## Provided Materials

You'll receive a ZIP containing:

```
interview-project/
├── data/
│   └── customs_entries_oct2024_mar2025.csv    # The dataset (~4,500 rows)
├── knowledge/
│   ├── customs_core_concepts.txt              # Domain terminology
│   ├── duties_fees_tariffs.txt                # Duty/fee rules & business logic
│   ├── customer_profiles_qbr_metrics.txt      # Customer context & KPIs
│   └── data_dictionary.txt                    # Column definitions & quirks
├── CASE_STUDY.md                              # This MARKDOWN file
└── CASE_STUDY.docx                            # DOCX version of this MARKDOWN file
```

---

## Evaluation Questions

Your agent must be able to correctly answer questions like these. We will test with these *and* additional questions not listed here.

**Tier 1 — Direct Retrieval**
1. How many customs entries were filed for Pacific Coast Apparel in January 2025?
2. What is the total entered value for Summit Athletic Gear in Q1 2025?
3. Which port of entry handled the most entries overall?

**Tier 2 — Knowledge-Grounded Computation**
4. What is the total Section 301 duty exposure for all customers combined in December 2024?
5. What is the effective duty rate for Meridian Home Furnishings for goods originating from China in Q1 2025? *(Requires knowing the formula from the knowledge base)*
6. How many entries are currently on hold, and what's the hold rate? Is it above or below the industry benchmark? *(Requires knowing the 5% benchmark from the knowledge base)*

**Tier 3 — Multi-Step Reasoning**
7. Compare the IEEPA duty impact across all three customers for February and March 2025. Which customer has the highest IEEPA exposure as a percentage of their total duty spend?
8. For Pacific Coast Apparel, what are the top 5 HTS codes by total duty contribution (all duty types combined) from China? Include the description and total amount.
9. Generate a mini QBR summary for Summit Athletic Gear covering Q1 2025 — entry volume trend by month, total duty breakdown by program, top sourcing countries, and hold rate.

**Tier 4 — Edge Cases & Precision**
10. If I ask "how many entries in January?" — which date field should the agent use, and why? *(The knowledge base specifies Release Date as default)*
11. What's the difference between entry count and line count for Meridian Home Furnishings in November 2024? *(Tests whether the agent distinguishes COUNT(DISTINCT entry_number) from COUNT(*))*

---

## Technical Requirements

### Architecture (Mandatory)
- **Backend:** Python (FastAPI or Flask) or Node.js/TypeScript
- **LLM Integration:** Any major LLM provider (OpenAI, Anthropic, etc.)
- **Knowledge Retrieval:** Implement RAG (Retrieval-Augmented Generation) — embed the knowledge documents and retrieve relevant context before answering. You may use any vector store (Pinecone, ChromaDB, pgvector, FAISS, etc.)
- **Data Layer:** Load and query the CSV. You may use pandas, DuckDB, SQLite, or any approach — but the agent must compute answers programmatically, not just pass the entire CSV to the LLM
- **Frontend:** A functional chat interface (React, Next.js, or equivalent)

### Infrastructure & DevOps (Mandatory)
This is not just about the AI — we want to see how you ship and operate software.

- **Deployment:** Deploy the application to **Vercel** (frontend) and **Fly.io** (backend), or an equivalent split. We want to see you work with real cloud deployment, not just localhost
- **CI/CD:** Set up **GitHub Actions** with at least:
  - Lint + type check on PR
  - Run the evaluation questions as an automated test suite
  - Deploy on merge to main
- **Environment Management:** Use environment variables for API keys and configuration. Never commit secrets. Show us your `.env.example`
- **Docker:** Containerize the backend with a Dockerfile. The Fly.io deployment should use this container
- **Security Considerations:** Document in your README what security measures you'd add for a production deployment (auth, rate limiting, input sanitization, CORS, API key rotation, etc.). Implement at least 2 of these in the prototype

### Code Quality
- Clean, well-organized repository structure
- Type hints (Python) or TypeScript (Node)
- Meaningful commit history (not one giant commit)
- README with setup instructions, architecture diagram, and design decisions

---

## Deliverables

1. **GitHub Repository** containing all source code, Dockerfile, GitHub Actions workflow, and documentation
2. **Deployed Demo** — a live URL where we can interact with the agent
3. **README.md** that includes:
   - Architecture overview with diagram
   - How the knowledge layer works (embedding strategy, retrieval approach, prompt design)
   - Infrastructure decisions (why Vercel/Fly.io, how CI/CD works)
   - Security considerations and what you implemented
   - Known limitations and what you'd improve with more time
4. **Evaluation Results** — run the 11 evaluation questions above and include the agent's answers in a file called `EVALUATION.md`. Note any questions where the agent struggled and explain why

---

## How We Evaluate

| Dimension | Weight | What We're Looking For |
|-----------|--------|----------------------|
| **Accuracy** | 30% | Does the agent give correct, grounded answers? Does it use the knowledge base appropriately? |
| **Architecture** | 25% | Is the RAG pipeline well-designed? Is the code clean and modular? Could this scale? |
| **Infrastructure** | 25% | CI/CD pipeline, Docker, deployment, environment management, security awareness |
| **UX & Polish** | 10% | Is the chat interface usable? Does the agent handle ambiguity well? |
| **Communication** | 10% | Quality of README, commit messages, documentation, and self-assessment in EVALUATION.md |

---

## Bonus Points (Not Required)

- Streaming responses in the chat UI
- Citation/source attribution (show which knowledge items informed the answer)
- Query explanation (show the computation the agent performed)
- Conversation memory across page refreshes
- Observability (logging, tracing, or error tracking integration)
- Cost optimization (token usage tracking, caching strategies)

---

## Ground Rules

- You may use any libraries, frameworks, or tools
- You may use AI assistants to help you code — but be prepared to explain every design decision in a follow-up interview
- If something is ambiguous, make a reasonable decision and document it
- We value working software over perfect software. Ship something that works end-to-end, then polish

---

*Questions? Reach out to your interview contact. Good luck.*
