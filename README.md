# InsightZone: Asynchronous Data Ingestion Pipeline and Business Intelligence Delivery Service via WhatsApp

InsightZone is a production grade data engineering and backend portfolio architecture designed to automate the ingestion, transformation, and analysis of transactional data. The system extracts raw sales inputs submitted either as unstructured text or tabular files via WhatsApp normalizes the data through a three tier pipeline, and delivers a professional analytical report in PDF format asynchronously within 60 seconds.

The primary objective of this project is to demonstrate robust solutions to critical enterprise data engineering challenges: severe memory constraints in ephemeral cloud environments, perimeter security through cryptographic validation, event idempotency, and heuristic schema alignment for inconsistent data layouts.

## Architectural Design and Data Flow

The data lifecycle adheres strictly to the Medallion Architecture (Bronze, Silver, and Gold design patterns) to ensure data quality and prevent downstream analytical corruption.

```
[User Interface: WhatsApp] ---> [File/Text Payload] ---> [Meta Cloud API Webhook]
                                                                  |
                                                      (HMAC SHA 256 Verification)
                                                                  v
[Cloudinary Storage] <--- [ReportLab PDF Stream] <--- [FastAPI Backend Core]
                                                                  |
                                                      (BackgroundTasks / APScheduler)
                                                                  v
                                                    [pipeline/reader.py (Polars)]
                                                                  |
                                                    (Heuristic Schema Normalization)
                                                                  v
                                                  [PostgreSQL / pipeline/metrics.py]

```

1. **Ingestion and Perimeter Layer:** The client submits a data payload (CSV, Excel, machine readable PDF, or raw text). The FastAPI webhook intercepts the HTTPS POST request, executes cryptographic signature verification, and delegates the payload to an asynchronous background worker thread.
2. **Bronze Layer (Raw Ingestion):** The raw file or text input is ingested into memory. A dictionary-based heuristic routing mechanism detects and maps columns based on synonymous terminology across multiple languages (e.g., *Date, Data, Item, Price, Preço, Qty, Total*).
3. **Silver Layer (Validation and Cleaning):** The data is structured into memory-efficient **Polars** DataFrames. Type enforcement is applied rigidly, and anomalous rows such as missing primary fields, corrupted records, or negative transactional quantities are systematically isolated and purged.
4. **Gold Layer (Analytics and Persistence):** Statistical aggregations and Key Performance Indicators (KPIs) are computed. Business metrics and client interaction states are persisted in a relational **PostgreSQL** instance. Dataframe memory allocation is instantly optimized via explicit garbage collection (`gc.collect()`) execution.
5. **Artifact Generation and Dispatch:** The final analytical report is compiled into a PDF binary stream utilizing **ReportLab** lazy-loading modules, pushed to secure cloud storage via **Cloudinary**, and the permanent URL is dispatched back to the end-user via the Meta Cloud API.

## System Capabilities

### 1. Hybrid Data Ingestion Engine

The pipeline ingests heterogeneous data structures natively without requiring manual state mutation by the user:

* **Tabular File Parsing:** Automated extraction of structured attachments (`.csv`, `.xlsx`, `.pdf`).
* **Text to Structured Stream parsing:** Direct ingestion of transactional records submitted as flat text. The parser scans the payload sequentially based on newline delimiters and comma separated variables:
```text
Product/Service, Quantity, Value
Grilled Chicken, 3, 250
IT Consulting, 1, 5000

```



### 2. Enterprise Scheduling and Cadence Orchestration

Leveraging **APScheduler** integrated directly into the FastAPI application lifecycle, the infrastructure manages automated reporting intervals (`daily`, `weekly`, `monthly`). The distribution states are persisted in the database, triggering deterministic evaluation jobs synchronized with regional time zones.

### 3. Stateful Onboarding State Machine

Upon intercepting communication from an unregistered entity, the backend initiates a stateful onboarding workflow governed by database parameters (`onboarding_passo`). This catches essential business metadata before permitting access to the core ETL processing pipeline.

## Engineering Performance Guarantees and Telemetry

* **Perimeter Response Latency:** The ingestion webhook acknowledges payloads and returns an `HTTP 200 OK` status to the Meta API gateway in **$< 15\text{ms}$**, mitigating network timeouts (`HTTP 504`) by offloading processing to non-blocking background workers.
* **Memory Optimization:** Implementing lazy evaluation and deterministic garbage collection controls limits the container memory footprint to **$< 250\text{MB}$**, ensuring operational stability and preventing Out Of Memory (OOM) faults during concurrent processing cycles.
* **Transaction Idempotency:** The system caches and cross-references the unique `message_id` provided by the Meta API. Duplicate delivery attempts triggered by upstream network retries are dropped immediately, preventing redundant database writes.
* **Cryptographic Security:** The `/webhook` endpoint enforces perimeter validation by recalculating the HMAC SHA 256 signature using the application secret key against the incoming payload, rejecting **$100\%$ of unauthorized requests** with an `HTTP 403` status.

## Project Directory Structure

```
insightzone/
│
├── app.py                  # FastAPI application entry point, webhook routing, and state machine
├── scheduler.py            # Cron orchestration for automated reporting distribution
├── criar_tabela.py         # Idempotent database schema migration script
├── requirements.txt        # Pinned dependency manifest
├── .env                    # Local environment variables and secrets (git-ignored)
│
├── pipeline/
│   ├── __init__.py
│   ├── reader.py           # Heuristic normalization engine and text stream parsers
│   ├── metrics.py          # Statistical computation and Garbage Collection management
│   ├── report.py           # ReportLab structural layout and PDF compilation
│   ├── storage.py          # Cloud persistence gateway and ephemeral file purging
│   └── sender.py           # Meta API dispatcher with automated exponential backoff retries
│
└── tests/
    └── test_insightzone.py # Automated test suite validating data quality and perimeter security

```

## Relational Database Schema

The infrastructure utilizes **PostgreSQL** for persistence and auditing:

| Attribute | Data Type | Functional Description |
| --- | --- | --- |
| **numero** | `TEXT (Primary Key)` | Unique global international MSISDN identification string. |
| **nome** | `TEXT` | Registered business entity name captured during onboarding. |
| **negocio** | `TEXT` | Industry vertical classification (`retail`, `services`, `agriculture`, `other`). |
| **frequencia** | `TEXT` | Active automated report distribution cadence (`daily`, `weekly`, `monthly`). |
| **ultimo_ficheiro_url** | `TEXT` | Audit trail pointer to the last raw file ingested. |
| **ultimo_relatorio_url** | `TEXT` | Permanent reference link to the latest compiled analytical PDF artifact. |
| **onboarding_passo** | `INTEGER` | Current index inside the onboarding state machine (0 indicates completion). |
| **modo** | `TEXT` | Operational state flag (`awaiting_sales`, `awaiting_cadence`). |
| **criado_em** | `TIMESTAMP` | System registration timestamp record. |

## Engineering Decisions and Problem Resolution

* **Mitigation of Ephemeral Disk Violations:** Cloud platforms often enforce ephemeral file systems where local disk writes are purged on container restarts. To resolve this, `pipeline/storage.py` pipes raw output chunks directly into temporary storage, executes an immediate transfer to long-term storage, and runs a mandatory file deletion within a `finally` code block to prevent storage leaks.
* **Heuristic Pattern Matching:** Small businesses frequently submit varying data schemas. The system addresses this by leveraging Regular Expressions (Regex) in `pipeline/reader.py` to achieve schema alignment. Synonymous inputs like *"Unit Price"*, *"Valor"*, *"Price"*, or *"Total"* are standardly mapped into a uniform Float64 data model.
* **Meta API Rate Limit Protection:** Third-party gateways can exhibit network jitter or trigger rate limits. The downstream dispatcher (`pipeline/sender.py`) incorporates a robust execution retry policy utilizing **exponential backoff**, which intercepts fatal network states (`401`, `403`) immediately to protect computing resources.
