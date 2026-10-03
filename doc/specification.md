# IGCSE Model Question Paper RAG System: Specification

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-10-03 |
| **Status** | Draft, approved for build |
| **Target syllabus** | Cambridge IGCSE (CAIE) |

---

## 1. Purpose

Build an AI agent that:

1. Ingests previous Cambridge IGCSE question papers, mark schemes and subject notes from a local folder.
2. Extracts questions and notes, then cleans, chunks, embeds and stores them in Pinecone with rich metadata.
3. Generates exam-ready **Model Question Papers**, with an optional mark scheme, using **only** questions extracted from the provided documents. Papers can be downloaded as PDF or DOCX.
4. Provides a **chatbot** that answers subject questions from the ingested documents first. If nothing relevant is found, it falls back to an internet search and clearly labels that answer as externally sourced.

---

## 2. Technology Decisions

| Concern | Decision | Notes |
|---|---|---|
| LLM | OpenAI | `gpt-5.5` for extraction and chat. `gpt-5.4-mini` for bulk classification. All three are configurable in `.env`. |
| Embeddings | Pinecone integrated inference | Model `llama-text-embed-v2`, cosine similarity. Pinecone embeds the text server-side. |
| Vector DB | Pinecone (serverless, AWS us-east-1) | One index (`igcse-rag`), two namespaces: `questions` and `notes`. |
| Reranker | Pinecone `bge-reranker-v2-m3` | Used by the chatbot to score how relevant retrieved chunks are. |
| Metadata catalog | SQLite (`data/catalog.db`) | Source of truth for full question text, mark schemes, image paths, ingestion log and file hashes. |
| Web search fallback | Tavily | Used only when local retrieval falls below the relevance threshold. |
| UI | Streamlit | Three tabs: Ingest, Generate Paper, Chatbot. |
| Difficulty classifier | LLM + heuristics | Uses marks, command words and the question part. No training data needed. |
| Section assignment | Automatic, by question type and marks | A = short, B = long/structured, C = application/case-based. |
| Diagrams | Kept as images | Cropped from the PDF, stored on disk and rendered in the generated paper. |
| Export formats | PDF (ReportLab), DOCX (python-docx), mark scheme | |
| Deployment | Local Windows PC | Python 3.12+ venv. Pinecone, OpenAI and Tavily run in the cloud. |
| Expected scale | Under 500 files, mostly digital | The OpenAI vision model handles image files. No Tesseract OCR needed. |

---

## 3. Architecture

```
┌──────────────────────────────── STREAMLIT UI (app.py) ────────────────────────────────┐
│  [1] Ingest tab            [2] Generate Paper tab              [3] Chatbot tab        │
│  folder path, progress     subject/topic/difficulty/#Q,        ask any subject Q      │
│  log, error messages       sections A/B/C, shuffle, download   answers with sources   │
└──────┬───────────────────────────────┬────────────────────────────────┬───────────────┘
       │                               │                                │
┌──────▼────────── INGESTION ──────┐   │                                │
│ Loader (by file extension)       │   │                                │
│  .pdf  → PyMuPDF (text+layout)   │   │                                │
│  .docx → python-docx             │   │                                │
│  .html → BeautifulSoup           │   │                                │
│  .txt  → plain read              │   │                                │
│  .png/.jpg → OpenAI vision       │   │                                │
│ Filename parser (CAIE):          │   │                                │
│  0625_s23_qp_42 → Physics, 2023, │   │                                │
│  May/June, Paper 4, Var 2, qp/ms │   │                                │
│ Cleaner: headers, page numbers,  │   │                                │
│  "[2]" marks, "© UCLES", blanks  │   │                                │
│        │                         │   │                                │
│ ┌──────▼────────────┐            │   │                                │
│ │ OpenAI gpt-5.5    │ structured │   │                                │
│ │ extraction (JSON) │ output     │   │                                │
│ └──┬─────────────┬──┘            │   │                                │
│  questions      notes            │   │                                │
│  + marks, type  + topic, type,   │   │                                │
│  + difficulty    keywords, page  │   │                                │
│  + diagram bbox                  │   │                                │
│  + ms answer link                │   │                                │
│        │                         │   │                                │
│ Diagram cropper (PyMuPDF bbox    │   │                                │
│   → data/images/*.png)           │   │                                │
│ Token chunker (recursive,        │   │                                │
│   200–400 tokens, 40 overlap)    │   │                                │
│ Dedup (hash + similarity ≥0.92)  │   │                                │
└──────┬──────────────────┬────────┘   │                                │
       │                  │            │                                │
┌──────▼──────────────────▼────────────▼────────────────────────────────▼───────────────┐
│                                   STORAGE                                             │
│  Pinecone index "igcse-rag" (integrated embed: llama-text-embed-v2, cosine)           │
│    ns "questions"  |  ns "notes"                                                      │
│  SQLite catalog.db (source of truth)  |  data/images/ (cropped diagrams)              │
└──────┬──────────────────────────────────────────────────────┬────────────────────────┘
       │                                                      │
┌──────▼────── PAPER GENERATOR ──────────┐    ┌───────────────▼───── CHATBOT ───────────────┐
│ Validate inputs                        │    │ 1. Search notes + questions namespaces       │
│ Filters → Pinecone metadata search     │    │ 2. Rerank (bge-reranker-v2-m3)               │
│ No filters → random sample from SQLite │    │ 3. Score ≥ threshold?                        │
│ Similarity dedup (MMR)                 │    │    YES → answer from chunks, cite file+page  │
│ Group into Sections A/B/C              │    │    NO  → Tavily → answer labelled            │
│ Shuffle (optional)                     │    │          "Sourced from external sources"     │
│ Question text copied word-for-word     │    │          + URLs                              │
│ Export: DOCX / PDF / mark scheme       │    │ Conversation memory (session_state)          │
└────────────────────────────────────────┘    └──────────────────────────────────────────────┘
```

### 3.1 Why SQLite alongside Pinecone

- **Random sampling.** Pinecone has no random query, so the app samples question IDs from SQLite.
- **Exact text.** Long questions may be split across chunks. SQLite keeps the full original question so papers reproduce it word for word.
- **Mark schemes.** Each question is linked to its mark-scheme answer by paper code and question number.
- **Incremental ingestion.** A SHA-256 hash per file means re-runs skip unchanged files.

---

## 4. Functional Requirements

### 4.1 Document Ingestion

| ID | Requirement |
|---|---|
| ING-1 | Read all files recursively from a user-specified folder (default `data/`). |
| ING-2 | Supported formats: `.pdf`, `.docx`, `.txt`, `.html`/`.htm`, `.png`, `.jpg`/`.jpeg`. Skip other files and log a warning for each. |
| ING-3 | Classify each document as **question paper** (`qp`), **mark scheme** (`ms`), **insert**/**source booklet** (`in`) or **notes**. Use the filename first and the content second. |
| ING-4 | From question papers, extract **only the questions** (with sub-parts), excluding instructions, cover pages, blank answer lines and "BLANK PAGE" sheets. |
| ING-5 | From notes, extract topic content (definitions, explanations, formulas, worked examples, diagram captions). |
| ING-6 | From mark schemes, extract the answer for each question number and link it to the matching question. |
| ING-7 | Clean and normalise text: remove headers and footers, page numbers, `© UCLES` lines, barcodes/candidate boxes, mark annotations such as `[2]` (stored as metadata, not text), repeated whitespace, and "Turn over" markers. Normalise Unicode and math symbols. |
| ING-8 | Detect diagrams, graphs and tables referenced by a question. Crop them from the page using PyMuPDF and save them as PNGs to `data/images/{question_id}_{n}.png`. |
| ING-9 | If the folder is missing, empty, unreadable, or contains no supported files, stop and show a clear error. Nothing is written in that case. |
| ING-10 | Skip files whose hash already exists in the catalog, unless the user ticks "Force re-ingest". |
| ING-11 | If one file fails, log the error and continue with the next file. Never abort the whole run. |

#### 4.1.1 Cambridge filename parsing

Pattern: `{subject_code}_{session}{yy}_{doc_type}_{paper}{variant}.{ext}`

| Example | Subject | Year | Session | Type | Paper | Variant |
|---|---|---|---|---|---|---|
| `0625_s23_qp_42.pdf` | Physics | 2023 | May/June | Question paper | 4 | 2 |
| `0580_w22_ms_21.pdf` | Mathematics | 2022 | Oct/Nov | Mark scheme | 2 | 1 |
| `0620_m24_qp_32.pdf` | Chemistry | 2024 | Feb/March | Question paper | 3 | 2 |

Session codes: `s` = May/June, `w` = Oct/Nov, `m` = Feb/March.

If a filename doesn't match the pattern, the LLM infers the subject and year from the content. If they still can't be found, they are stored as `unknown` and flagged in the ingestion log.

The subject-code map lives in `config.py` and the user can extend it. Initial codes: 0580 Mathematics, 0606 Additional Mathematics, 0625 Physics, 0620 Chemistry, 0610 Biology, 0654 Co-ordinated Sciences, 0455 Economics, 0450 Business Studies, 0452 Accounting, 0478 Computer Science, 0500 First Language English, 0510 English as a Second Language.

#### 4.1.2 Extraction contract (OpenAI structured output)

Each question paper page batch returns:

```json
{
  "questions": [
    {
      "number": "3(b)(ii)",
      "parent_number": "3",
      "stem_context": "A student investigates the resistance of a wire...",
      "text": "Calculate the current in the circuit.",
      "marks": 2,
      "question_type": "calculation",
      "command_word": "calculate",
      "topic": "Electricity - Electric circuits",
      "has_diagram": true,
      "diagram_bbox": [{"page": 5, "x0": 72, "y0": 210, "x1": 520, "y1": 430}]
    }
  ]
}
```

`question_type` is one of: `mcq`, `short_answer`, `calculation`, `structured`, `extended_response`, `data_analysis`, `case_study`, `practical`.

Sub-parts keep their shared stem (`stem_context`) so each one still makes sense when used on its own.

### 4.2 Chunking and Embeddings

| ID | Requirement |
|---|---|
| CHK-1 | Use token-based recursive chunking with a target of **200–400 tokens** per chunk and **40 tokens of overlap**. Use the `cl100k_base` tokenizer as an approximation. |
| CHK-2 | Separator priority: question boundary → paragraph → sentence → word. |
| CHK-3 | A question (stem plus its part) under 400 tokens stays as **one chunk**. Longer questions are split, and every chunk carries the same `question_id`. |
| CHK-4 | Notes are chunked within a topic section only. A chunk never spans two topics. |
| CHK-5 | Pinecone embeds the `chunk_text` field automatically (integrated inference). No local embedding step is needed. |
| CHK-6 | Upsert in batches of 96 records, retrying with exponential backoff (`tenacity`). |
| CHK-7 | Before upserting, drop near-duplicate questions: identical normalised hashes, or cosine similarity ≥ 0.92 to an existing question of the same subject. |

### 4.3 Metadata

#### 4.3.1 Question chunks (`questions` namespace)

| Field | Type | Example | Source |
|---|---|---|---|
| `chunk_text` | string | "A student investigates… Calculate the current…" | extraction (embedded) |
| `question_id` | string | `0625_s23_qp_42_q3bii` | generated |
| `question_text` | string | first 1,000 characters (full text kept in SQLite) | extraction |
| `subject` | string | `Physics` | filename / content |
| `subject_code` | string | `0625` | filename |
| `topic` | string | `Electricity - Electric circuits` | LLM, mapped to syllabus |
| `difficulty` | enum | `easy` / `medium` / `hard` | classifier (§4.3.3) |
| `question_type` | enum | `calculation` | extraction |
| `section` | enum | `A` / `B` / `C` | rules (§4.5.2) |
| `marks` | int | `2` | extraction |
| `year` | int | `2023` | filename |
| `session` | string | `May/June` | filename |
| `paper` | string | `4` | filename |
| `variant` | string | `2` | filename |
| `source_file` | string | `0625_s23_qp_42.pdf` | loader |
| `page` | int | `5` | loader |
| `has_diagram` | bool | `true` | extraction |
| `image_paths` | list[string] | `["data/images/0625_s23_qp_42_q3bii_1.png"]` | cropper |
| `has_mark_scheme` | bool | `true` | MS linker |

#### 4.3.2 Notes chunks (`notes` namespace)

| Field | Type | Example |
|---|---|---|
| `chunk_text` | string | "Ohm's law states that…" |
| `chunk_id` | string | `notes_physics_ch4_p12_c3` |
| `subject` | string | `Physics` |
| `topic` | string | `Electricity - Electric circuits` |
| `content_type` | enum | `definition` / `explanation` / `formula` / `worked_example` / `diagram_caption` / `summary` |
| `keywords` | list[string] | `["ohm's law", "resistance", "current"]` |
| `source_file` | string | `Physics_Notes_Ch4.pdf` |
| `page` | int | `12` |

#### 4.3.3 Difficulty classification (LLM + heuristics)

Rules give a starting score, and a small OpenAI model (`gpt-5.4-mini`) confirms or adjusts it, returning a one-line reason that is stored in SQLite.

| Signal | Easy | Medium | Hard |
|---|---|---|---|
| Marks | 1–2 | 3–4 | 5+ |
| Command word | state, name, identify, define, give | describe, explain, calculate, suggest, compare | evaluate, discuss, justify, deduce, predict, analyse |
| Steps or concepts | one | two | multi-step or cross-topic |
| Paper tier | Core paper | either | Extended paper |

### 4.4 Retrieval

| ID | Requirement |
|---|---|
| RET-1 | Filters: `subject` (required if more than one subject is ingested), `topic` (optional, multi-select), `difficulty` (optional: easy, medium, hard or mixed), `num_questions` (required, 1–60), `year` range (optional). |
| RET-2 | When filters are set, query the Pinecone `questions` namespace with a metadata filter (`$eq` / `$in` / `$gte` / `$lte`). Use a topic-based query text to get relevant results. |
| RET-3 | **When no filters are set**, sample question IDs at random from SQLite (with a seed shown in the UI so the paper can be reproduced) and fetch their records. |
| RET-4 | Fetch three times the requested count, then pick a varied subset using MMR (λ = 0.7). Never pick two questions with similarity ≥ 0.85, two sub-parts of the same parent question, or the same `question_id` twice. |
| RET-5 | Fewer matching questions than requested: generate the paper with what is available and **warn** the user (e.g. "Only 14 hard Physics questions on Thermal Physics were found; generated 14 of 20"). |
| RET-6 | Zero matching questions: return an error and suggest relaxing the filters. |

### 4.5 Model Question Paper Generation

#### 4.5.1 Rules

| ID | Requirement |
|---|---|
| GEN-1 | **No hallucinated questions.** Question text, numbers, marks and diagrams are copied word for word from SQLite. The LLM is never asked to write or rephrase question content. |
| GEN-2 | Questions are shuffled by default. The user can choose ordering by section, topic or difficulty instead. |
| GEN-3 | Questions are renumbered from 1. Sub-parts keep their structure: (a), (b), (i), (ii). |
| GEN-4 | Sections are optional (toggle in the UI). When on, questions are grouped into Sections A, B and C. |
| GEN-5 | Each question shows its marks in brackets, aligned right, e.g. `[3]`. A source reference such as `(0625/42/M/J/23 Q3b)` can be switched on. |
| GEN-6 | Diagrams are placed directly under their question text. |
| GEN-7 | The total marks are calculated and shown in the header. |

#### 4.5.2 Section assignment

| Section | Name | Rule |
|---|---|---|
| A | Short answers | `question_type` ∈ {mcq, short_answer} **or** marks ≤ 3 |
| B | Long answers | `question_type` ∈ {structured, extended_response, calculation} **and** marks ≥ 4 |
| C | Application / Case-based | `question_type` ∈ {data_analysis, case_study, practical} **or** the question relies on a given context, data table or scenario |

The user can override how many questions go in each section. The default split is 40% / 40% / 20%.

#### 4.5.3 Output format

```
                    Model Question Paper – Physics
                    Cambridge IGCSE (0625)
Duration: 1 hour 15 minutes                         Total marks: 80

INSTRUCTIONS
• Answer all questions.
• Write your answers in the spaces provided.
• Show all working where calculations are required.
• The number of marks is given in brackets [ ] at the end of each question.

SECTION A – Short Answers
1  State the unit of electrical resistance.                              [1]
2  ...

SECTION B – Long Answers
...

SECTION C – Application / Case-Based Questions
...
```

- The title is always **"Model Question Paper – [Subject]"**.
- Instructions are optional and can be edited in the UI.
- Duration defaults to 1 minute per mark and can be edited.

#### 4.5.4 Downloads

| Format | Library | Contents |
|---|---|---|
| PDF | ReportLab | Paper, with diagrams embedded |
| DOCX | python-docx | Editable paper, with diagrams embedded |
| Mark scheme (PDF and DOCX) | same | Answers from the linked `ms` files, numbered to match the paper. Questions with no mark scheme are listed as "Mark scheme not available in source documents". |

Downloads are offered through `st.download_button`. Generated files are also saved to `output/{subject}_{timestamp}.{ext}`.

### 4.6 Chatbot

| ID | Requirement |
|---|---|
| CHAT-1 | The user asks any subject question in natural language and can optionally pick a subject to narrow the search. |
| CHAT-2 | Search the `notes` namespace (top_k = 10) and the `questions` namespace (top_k = 5), then rerank all results together with `bge-reranker-v2-m3`. |
| CHAT-3 | **Local answer:** if the best rerank score is at least `RELEVANCE_THRESHOLD` (default 0.35, adjustable), the LLM answers **only** from the retrieved chunks. Each answer ends with a **Sources** list (file name and page). |
| CHAT-4 | **External fallback:** below the threshold, call Tavily (`search_depth="advanced"`, max 5 results). The LLM answers from those results, and the answer begins with: **"⚠ Related information was not found in the ingested documents. The answer below is sourced from external web sources:"**, followed by a list of the source URLs. |
| CHAT-5 | The LLM must not mix local and external content without labelling which part came from where. |
| CHAT-6 | Keep the conversation history in `st.session_state` (last 10 turns) so follow-up questions work. |
| CHAT-7 | The chatbot can also list past-paper questions on a topic (e.g. "Show me past questions on moments"). These come from the `questions` namespace. |

### 4.7 Agent Behaviour

| ID | Requirement |
|---|---|
| AGT-1 | Before and during ingestion or paper generation, explain each step in the UI (e.g. "Parsing 0625_s23_qp_42.pdf: detected Physics, May/June 2023, Paper 4"). |
| AGT-2 | Log ingestion progress live: files found, files processed, files skipped, files failed, questions extracted, notes sections extracted, chunks created, diagrams cropped, duplicates dropped. |
| AGT-3 | At the end of ingestion, show a summary table per file and per subject. |
| AGT-4 | Write logs to `logs/ingest_{timestamp}.log` and record each run in the SQLite `ingestion_runs` table. |
| AGT-5 | Validate every input. Subject must exist in the catalog (suggest the closest match if not). `num_questions` must be an integer from 1 to 60 and no more than the number available. Difficulty must be easy, medium, hard or mixed. The folder path must exist and be readable. |
| AGT-6 | Error messages say what went wrong and how to fix it (e.g. "Folder `D:\papers` is empty: add PDF, DOCX, TXT, HTML or image files and retry."). |

### 4.8 Constraints

- Never generate, invent or paraphrase exam questions. Papers contain only questions extracted from the provided folder.
- Chatbot answers based on local data must be grounded in retrieved chunks.
- External answers are always labelled as such.
- Keep an academic tone, and use Cambridge terminology and command words.
- API keys are read from `.env` only. They are never logged or shown in the UI.

---

## 5. Data Model (SQLite)

```sql
CREATE TABLE files (
  file_id        TEXT PRIMARY KEY,      -- sha256
  path           TEXT NOT NULL,
  doc_type       TEXT,                  -- qp | ms | in | notes
  subject        TEXT, subject_code TEXT,
  year INTEGER, session TEXT, paper TEXT, variant TEXT,
  status         TEXT,                  -- ingested | failed | skipped
  error          TEXT,
  ingested_at    TEXT
);

CREATE TABLE questions (
  question_id    TEXT PRIMARY KEY,
  file_id        TEXT REFERENCES files(file_id),
  number         TEXT, parent_number TEXT,
  stem_context   TEXT,
  text           TEXT NOT NULL,
  marks          INTEGER,
  question_type  TEXT, command_word TEXT,
  topic          TEXT, difficulty TEXT, difficulty_reason TEXT,
  section        TEXT,
  page           INTEGER,
  image_paths    TEXT,                  -- JSON array
  ms_answer      TEXT,                  -- linked mark scheme text
  content_hash   TEXT UNIQUE
);

CREATE TABLE notes (
  chunk_id       TEXT PRIMARY KEY,
  file_id        TEXT REFERENCES files(file_id),
  subject TEXT, topic TEXT, content_type TEXT,
  keywords TEXT, page INTEGER, text TEXT
);

CREATE TABLE ingestion_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT, finished_at TEXT,
  files_found INTEGER, files_processed INTEGER, files_skipped INTEGER, files_failed INTEGER,
  questions_extracted INTEGER, notes_extracted INTEGER,
  chunks_created INTEGER, duplicates_dropped INTEGER
);
```

---

## 6. Non-Functional Requirements

| Area | Requirement |
|---|---|
| Performance | Ingest about 500 digital PDFs in under 1 hour (concurrent OpenAI calls, max 5 at a time). Generate a paper in under 10 s. First chatbot token in under 5 s. |
| Cost control | Use the mini model with low reasoning effort for classification. Keep system prompts fixed so OpenAI's automatic prompt caching applies. Skip unchanged files using their hash. |
| Reliability | All external calls retry up to 3 times with exponential backoff. A failure in one file doesn't affect the others. |
| Reproducibility | Random papers record their seed, and the seed is shown on screen and in the file footer. |
| Security | Keys live in `.env`, which is git-ignored. Only data you choose leaves the machine: document text goes to OpenAI and Pinecone, and chat queries go to Tavily. |
| Portability | Windows 11 and Python 3.12+. No system-level dependencies such as Tesseract or GTK. |

---

## 7. Project Structure

```
IGCSE_ModelQuestion/
├─ app.py                     # Streamlit entry: top navigation + sidebar status
├─ app_pages/
│  ├─ ingest.py               # Ingest page: folder, live log, per-file / per-subject summary
│  ├─ generate.py             # Generate Paper page: filters, preview, PDF/DOCX + mark scheme downloads
│  └─ chat.py                 # Chatbot page: local-first answers, labelled web fallback
├─ config.py                  # env vars, models, thresholds, subject-code map
├─ llm.py                     # OpenAI client: structured output + streaming
├─ ingest/
│  ├─ loaders.py              # pdf/docx/txt/html/image → pages (scanned pages → images)
│  ├─ filename_parser.py      # CAIE filename → metadata + paper_key
│  ├─ cleaner.py              # header/footer/noise removal, marks stripping, hashing
│  ├─ extractor.py            # LLM structured extraction (questions, notes, ms, doc type)
│  ├─ classifier.py           # difficulty (heuristics + mini model) + section rules
│  ├─ images.py               # diagram cropping
│  ├─ chunker.py              # token-based recursive chunking
│  └─ pipeline.py             # orchestrates + progress logging; also a CLI
├─ store/
│  ├─ pinecone_store.py       # index creation, upsert/search/rerank/embed
│  └─ catalog.py              # SQLite access
├─ paper/
│  ├─ retriever.py            # validation, filtered / random retrieval, MMR dedup
│  ├─ assembler.py            # sections, ordering, numbering, mark-scheme linking
│  ├─ export_docx.py
│  └─ export_pdf.py
├─ chat/
│  ├─ rag_chat.py             # local-first answering with rerank threshold
│  └─ web_fallback.py         # Tavily search
├─ data/
│  ├─ papers/                 # qp / ms / in files (keep CAIE filenames)
│  ├─ notes/                  # any file under a folder named "notes" is treated as notes
│  ├─ images/                 # cropped diagrams (generated)
│  └─ catalog.db              # generated
├─ output/                    # generated papers
├─ logs/                      # one log file per ingestion run
├─ doc/specification.md
├─ .env.example               # copy to .env
└─ requirements.txt
```

---

## 8. Installation (Windows, PowerShell)

```powershell
# 1. Python 3.12 or newer
winget install -e --id Python.Python.3.12

# 2. Virtual environment
cd C:\Asphero\IGCSE_ModelQuestion
py -3 -m venv .venv
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # only if Activate.ps1 is blocked
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

# 3. Dependencies
pip install -r requirements.txt

# 4. API keys: copy the template, then edit .env and paste your keys
Copy-Item .env.example .env
notepad .env

# 5. Run the app (the Pinecone index is created automatically on first ingestion)
streamlit run app.py

# Optional: ingest from the command line instead of the UI
python -m ingest.pipeline data            # add --force to re-ingest unchanged files
```

API keys come from platform.openai.com, app.pinecone.io and app.tavily.com.

---

## 9. Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | (required) | OpenAI access |
| `EXTRACTION_MODEL` / `CHAT_MODEL` / `CLASSIFIER_MODEL` | `gpt-5.5` / `gpt-5.5` / `gpt-5.4-mini` | OpenAI models |
| `EXTRACTION_EFFORT` / `CHAT_EFFORT` | `medium` / `low` | Reasoning effort for GPT-5 models |
| `PINECONE_API_KEY` | (required) | Pinecone access |
| `TAVILY_API_KEY` | (required) | Web search fallback |
| `PINECONE_INDEX` | `igcse-rag` | Index name |
| `RELEVANCE_THRESHOLD` | `0.35` | Rerank score below which the chatbot falls back to web search |
| `DEDUP_SIMILARITY` | `0.92` | Similarity at which a question counts as a duplicate during ingestion |
| `PAPER_DIVERSITY_SIMILARITY` | `0.85` | Maximum similarity allowed between two questions in one paper |
| `CHUNK_MIN_TOKENS` / `CHUNK_MAX_TOKENS` | `200` / `400` | Chunk size range |
| `CHUNK_OVERLAP` | `40` | Token overlap between chunks |
| `MAX_CONCURRENCY` | `5` | Parallel OpenAI calls during ingestion |

---

## 10. Acceptance Criteria

1. Ingesting a folder of CAIE PDFs shows live progress and a final summary. Re-running it skips files that haven't changed.
2. Pointing ingestion at an empty or non-existent folder shows a clear error and writes nothing.
3. A generated paper's questions all match text in `catalog.db` exactly. Spot-check 20 of them against the source PDFs.
4. A paper filtered by subject, topic, difficulty and count respects all the filters, or warns when there aren't enough questions.
5. A paper with no filters uses random questions and reproduces exactly from the same seed.
6. No paper contains duplicate or near-duplicate questions.
7. PDF and DOCX downloads open correctly, include diagrams, and show the title "Model Question Paper – [Subject]".
8. The mark scheme download matches the paper's numbering.
9. A chatbot question covered by the notes gets an answer that cites local file names and pages.
10. A chatbot question not covered by the notes gets an answer that starts with the external-source notice and lists URLs.

---

## 11. Assumptions and Open Items

- Past papers keep their original CAIE filenames. Files that don't are still processed, but their metadata depends on the LLM inferring it from the content.
- Topic names follow the current Cambridge syllabus for each subject. A per-subject topic list in `config.py` can be added to standardise the names.
- Multiple-choice papers (Paper 1/2) are ingested as `mcq`, with the options A–D kept in the question text.
- Insert and source booklets (`in`) are linked to their question paper, and their content is attached to Section C questions that depend on them.
- The app runs on one machine. Multiple users and authentication are out of scope for version 1.
