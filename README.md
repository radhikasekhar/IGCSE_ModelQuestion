# IGCSE Model Question Paper Agent

A web app that turns your own Cambridge IGCSE past papers, mark schemes and notes into:

- **Model question papers.** Choose subject, topics, difficulty and number of questions, and download the paper as PDF or Word, with a matching mark scheme.
- **A subject chatbot.** It answers from your ingested documents first. If they don't cover a question, it searches the web and clearly labels the answer as coming from external sources.

Questions in generated papers are always copied word for word from your documents. The AI never writes or rephrases exam questions.

**Contents**

1. [How it works](#1-how-it-works)
2. [Accounts and API keys you need](#2-accounts-and-api-keys-you-need)
3. [Run it on your own computer (Windows)](#3-run-it-on-your-own-computer-windows)
4. [Using the app](#4-using-the-app)
5. [Preparing documents](#5-preparing-documents)
6. [Deploy to Railway (for the team)](#6-deploy-to-railway-for-the-team)
7. [Updating the deployed app](#7-updating-the-deployed-app)
8. [Settings reference](#8-settings-reference)
9. [Costs](#9-costs)
10. [Security](#10-security)
11. [Troubleshooting](#11-troubleshooting)
12. [Project structure](#12-project-structure)

---

## 1. How it works

```
 Upload papers / notes ──► Ingestion ──────────────────────────────► Storage
                           • read PDF, Word, text, web pages, images   • Pinecone (cloud): searchable text chunks
                           • OpenAI extracts each question, its       • SQLite catalog: full question text, marks,
                             marks, topic and type; or note sections     difficulty, mark-scheme answers
                           • rates difficulty, assigns Section A/B/C  • Diagram images cropped from the papers
                           • crops diagrams, removes duplicates
                                                                          │
              ┌───────────────────────────────────────────────────────────┤
              ▼                                                           ▼
     Generate Paper page                                           Chatbot page
     • filter by subject, topic, difficulty, year                  • searches your notes and past questions
     • random or "focus" (search by meaning) selection             • answers only from them, citing file + page
     • no duplicates, no two parts of the same question            • if nothing relevant: Tavily web search,
     • PDF / Word paper + mark scheme                                answer labelled "external web sources"
```

| Service | Used for |
|---|---|
| **OpenAI** | Reading documents and extracting questions and notes; rating difficulty; chatbot answers |
| **Pinecone** | Storing text chunks so they can be searched by meaning (it creates the embeddings itself) |
| **Tavily** | Web search when your documents don't answer a chatbot question |
| **Streamlit** | The web interface |
| **Railway** | Hosting the app for the team (optional; it also runs on any Windows PC) |

The full functional specification is in [doc/specification.md](doc/specification.md).

---

## 2. Accounts and API keys you need

| Service | Where to get the key | Key looks like | Notes |
|---|---|---|---|
| OpenAI | platform.openai.com → **API keys** | `sk-...` | Needs billing set up. The account must have access to the models in [Settings](#8-settings-reference) (default `gpt-5.5` and `gpt-5.4-mini`). |
| Pinecone | app.pinecone.io → **API Keys** | `pcsk_...` | The free Starter plan is enough to begin. |
| Tavily | app.tavily.com | `tvly-...` | Has a free monthly allowance. |
| GitHub | github.com | — | Only needed to deploy to Railway. |
| Railway | railway.com | — | Only needed to deploy. Sign in with GitHub. |

**Keep keys private.** Never paste them into chat messages, documents or `.env.example`, and never commit them to GitHub.

---

## 3. Run it on your own computer (Windows)

### 3.1 Install the tools

1. **Python 3.12 or newer.** Open PowerShell and run:
   ```powershell
   winget install -e --id Python.Python.3.12
   ```
   Or download it from python.org. During setup, tick **"Add python.exe to PATH"**.
2. **Git:** `winget install -e --id Git.Git`
3. **VS Code** (recommended): `winget install -e --id Microsoft.VisualStudioCode`

Close and reopen PowerShell after installing.

### 3.2 Get the code

```powershell
cd C:\
git clone https://github.com/radhikasekhar/IGCSE_ModelQuestion.git
cd IGCSE_ModelQuestion
```

(If you already have the folder, just `cd` into it.)

### 3.3 Create the Python environment and install packages

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell says running scripts is disabled, run this once and try again:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

When the environment is active, the prompt starts with `(.venv)`. Activate it again each time you open a new terminal.

### 3.4 Add your API keys

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in the first three lines and save:
```
OPENAI_API_KEY=sk-...
PINECONE_API_KEY=pcsk_...
TAVILY_API_KEY=tvly-...
```

Paste each key straight after the `=`, with no quotes or spaces.

A key that is also set as a Windows environment variable overrides the value in `.env`. To change such a key, edit it in Windows: search for **"Edit environment variables for your account"**.

### 3.5 Start the app

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

The app opens at http://localhost:8501. The sidebar should say **"API keys configured"**.

Stop it with `Ctrl+C` in the terminal. Restart it after changing `.env` or `.streamlit/config.toml`.

**Ingesting from the command line** (optional):
```powershell
python -m ingest.pipeline data            # add --force to re-process unchanged files
```

---

## 4. Using the app

### Ingest page: add documents
1. **Upload files.** Choose **"Papers, mark schemes & inserts"** or **"Notes"**, drop in files, and click **Upload and ingest**.
2. Wait until the progress box says it has finished. **Don't click anything on the page while it runs.** Any click reloads the page and stops the run.
3. Check the summary table: questions found, diagrams cropped and duplicates dropped for each file.

**Re-scan the whole data folder** processes everything in the data folder. Unchanged files are skipped automatically; tick **Force re-ingest** to process them again.

Only one ingestion runs at a time. A second one, for example from another browser tab, shows an "already in progress" message.

### Generate Paper page
| Option | What it does |
|---|---|
| Subject | Only subjects with ingested questions are listed |
| Number of questions | 1–60 |
| Difficulty | mixed, easy, medium or hard |
| Chapters / topics | Optional filter |
| Focus | Optional free text, e.g. "moments and levers". Finds questions by meaning instead of picking at random |
| Years | Optional range |
| Sections | Groups questions into **A** (short answers), **B** (long answers) and **C** (application / case-based). Leave the counts at 0/0/0 for the default 40% / 40% / 20% split |
| Ordering | Random, easy → hard, or by topic |
| Paper details | Instructions, duration (default 1 minute per mark), seed, and whether to show source references |

After generating, download **Paper (PDF / DOCX)** and **Mark scheme (PDF / DOCX)**. Copies are also saved in the `output` folder.

**Seed:** every paper shows a seed number. Enter it again with the same settings to get exactly the same paper.

**Warnings:** if fewer questions match than you asked for, the paper is made with what's available and a warning explains why.

### Chatbot page
- **"Answered from ingested documents"** means the answer uses only your files, and the sources (file and page) are listed at the end.
- **"Not found locally, so searched the web"** means the answer starts with a ⚠ notice and lists the website links it used.
- You can ask for past questions too, e.g. "Show me past paper questions on moments".

---

## 5. Preparing documents

**Supported formats:** PDF, Word (`.docx`), text (`.txt`), web pages (`.html`) and images (`.png`, `.jpg`). Scanned PDF pages are read as images.

### Use Cambridge file names for past papers

Cambridge names its files in a fixed pattern. Keeping that pattern lets the app detect subject, year, session and paper automatically, and link each mark scheme to its paper.

```
0620_s23_qp_42.pdf
 │    │   │  ││
 │    │   │  │└─ variant (2)
 │    │   │  └── paper number (4)
 │    │   └───── type: qp = question paper, ms = mark scheme, in = insert
 │    └───────── session + year: s = May/June, w = Oct/Nov, m = Feb/March; 23 = 2023
 └────────────── subject code (0620 = Chemistry)
```

| Subject | Code | Subject | Code |
|---|---|---|---|
| Mathematics | 0580 | Economics | 0455 |
| Additional Mathematics | 0606 | Business Studies | 0450 |
| Physics | 0625 | Accounting | 0452 |
| Chemistry | 0620 | Computer Science | 0478 |
| Biology | 0610 | First Language English | 0500 |
| Co-ordinated Sciences | 0654 | English as a Second Language | 0510 |

To add a subject, add its code to `SUBJECT_CODES` in [config.py](config.py).

**Other file names still work.** The AI works out the document type and subject itself, but the session and paper number aren't detected, and mark schemes can't be linked. You'll see the message *"name isn't a CAIE code; the LLM will infer the details"*. That's information, not an error.

**Upload the question paper and its mark scheme together**, named for the same paper (`..._qp_42` and `..._ms_42`).

**Notes** go under the **"Notes"** upload option, or in `data\notes` locally.

---

## 6. Deploy to Railway (for the team)

Railway runs the app on the internet so the team can use it from a browser, without installing anything. The repository already contains the deployment files: `Dockerfile`, `docker/entrypoint.sh`, `railway.json` and `.dockerignore`.

### 6.1 Push the code to GitHub

Create a **private** repository on GitHub, then from the project folder:

```powershell
git add .
git commit -m "Describe your change"
git branch -M main
git push -u origin main
```

`.gitignore` keeps `.env`, `.venv`, `data`, `output` and `logs` out of GitHub.

> If you see `error: src refspec main does not match any`, your branch is called `master`. Run `git branch -M main` and push again.

Make the repository **private**: on GitHub, open the repo → **Settings** → **General** → **Danger Zone** → **Change visibility**.

### 6.2 Create the Railway service

1. Go to **railway.com** → **New Project** → **Deploy from GitHub repo** → pick the repository.
2. Railway reads `railway.json` and builds the `Dockerfile`. The first build takes a few minutes.

### 6.3 Add a volume (permanent storage). Required!

Without a volume, the catalog, uploaded papers and generated files are **deleted on every redeploy**.

1. On the project canvas, **right-click your app's box** → **Attach Volume**. (Or **+ Create** → **Volume**, or press `Ctrl+K` and type "volume".)
2. If asked, choose your app as the service to attach to.
3. **Mount path:** type exactly
   ```
   /storage
   ```
4. Click **Create**, then **Deploy** in the "Apply changes" bar at the top.

Check: click the app → **Settings** → **Volumes** shows `/storage`, and the app's box on the canvas shows a disk icon.

### 6.4 Add the variables

1. Click your app's box → **Variables** tab → **Raw Editor**.
2. Paste the following, with your own values:
   ```
   OPENAI_API_KEY=your-openai-key
   PINECONE_API_KEY=your-pinecone-key
   TAVILY_API_KEY=your-tavily-key
   PINECONE_INDEX=igcse-rag-prod
   APP_PASSWORD=a-long-team-password
   ```
3. Click **Update Variables**, then **Deploy** in the "Apply changes" bar.

Notes:
- **Separate index (`PINECONE_INDEX=igcse-rag-prod`).** The Railway catalog starts empty. Using a different Pinecone index from your PC's keeps the two from getting out of step. The index is created automatically on first ingestion.
- **`STORAGE_DIR` isn't needed.** The Docker image already sets it to `/storage`.
- **Password ideas:** three random words and a number, e.g. `maple-river-lantern-42`. Don't reuse a password from elsewhere.

### 6.5 Get the app's address

1. Click your app's box → **Settings** tab → scroll to **Networking** → **Public Networking**.
2. If an address is listed (e.g. `igcse-modelquestion-production.up.railway.app`), that's your app.
3. If not, click **Generate Domain**. If asked for a port, enter **8080**, or accept the port Railway suggests.
4. Open the address in a **new browser tab**, adding `https://` at the front if it's missing.

Ignore any address ending in `.railway.internal`. It only works inside Railway.

### 6.6 Check the deployment

1. App → **Deployments**: the newest deployment shows **Active**.
2. Opening the address shows the **password screen**. If it goes straight into the app, `APP_PASSWORD` isn't set: check the spelling and deploy again.
3. After entering the password, the sidebar says **"API keys configured"**.
4. Upload one paper on **Ingest** and generate a short paper.
5. **Check that data survives:** **Deployments** → **⋮** → **Redeploy**. After it restarts, the sidebar counts (Files, Questions) should be unchanged.

### 6.7 Share with the team

Send the address and the password **separately** (for example, the link by email and the password in a chat message). To revoke access, change `APP_PASSWORD` in Railway and deploy again.

### 6.8 Optional: Google or Microsoft sign-in instead of a password

Each person signs in with their own account, and only allowed emails or domains get in.

1. **Google Cloud Console** → **APIs & Services** → **Credentials** → **Create credentials** → **OAuth client ID** → **Web application**. Set up the OAuth consent screen first if asked; choose "Internal" to limit it to your Google Workspace.
2. Under **Authorised redirect URIs** add: `https://<your-railway-address>/oauth2callback`
3. In Railway **Variables**, add:

   | Variable | Value |
   |---|---|
   | `AUTH_CLIENT_ID` | Client ID from Google |
   | `AUTH_CLIENT_SECRET` | Client secret from Google |
   | `AUTH_COOKIE_SECRET` | Random text: run `python -c "import secrets; print(secrets.token_hex(32))"` |
   | `ALLOWED_EMAIL_DOMAINS` | e.g. `yourschool.edu` (comma-separated), **and/or** |
   | `ALLOWED_EMAILS` | e.g. `alice@gmail.com,bob@gmail.com` |

4. Delete `APP_PASSWORD`, then click **Deploy**.

Always set `ALLOWED_EMAIL_DOMAINS` or `ALLOWED_EMAILS`. Without them, *any* Google account can sign in.

- **Microsoft accounts:** register an app in **Microsoft Entra ID** with the same redirect URI, use its client ID and secret, and add `AUTH_SERVER_METADATA_URL=https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration`.
- **Custom domain:** also set `AUTH_REDIRECT_URI=https://<custom-domain>/oauth2callback`.

Detailed notes: [doc/deploy_railway.md](doc/deploy_railway.md).

### 6.9 Rules for the Railway service
- **Keep one instance (replica).** The catalog is a single SQLite file on the volume.
- **Keep the volume.** Deleting it deletes the catalog, uploads and generated papers. The Pinecone index is separate and is not affected.
- **Redeploys are safe.** Changing variables or pushing code redeploys the app, and data on the volume is kept.

---

## 7. Updating the deployed app

1. Make and test changes locally (`streamlit run app.py`).
2. Commit and push:
   ```powershell
   git add .
   git commit -m "Describe the change"
   git push
   ```
3. Railway notices the push and redeploys automatically. Watch **Deployments** until the new one is **Active**.

**Testing the Docker image locally** (optional, needs Docker Desktop):
```powershell
docker build -t igcse-agent .
docker run --rm -p 8501:8080 -e PORT=8080 --env-file .env -v igcse-data:/storage igcse-agent
```
Then open http://localhost:8501.

---

## 8. Settings reference

Set these in `.env` (local) or Railway **Variables** (deployed). Only the three API keys are required; everything else has a default.

### Required
| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | OpenAI access |
| `PINECONE_API_KEY` | Pinecone access |
| `TAVILY_API_KEY` | Web search for the chatbot |

### Models
| Variable | Default | Purpose |
|---|---|---|
| `EXTRACTION_MODEL` | `gpt-5.5` | Reads documents and extracts questions and notes |
| `CHAT_MODEL` | `gpt-5.5` | Chatbot answers |
| `CLASSIFIER_MODEL` | `gpt-5.4-mini` | Difficulty ratings and document-type detection |
| `EXTRACTION_EFFORT` | `medium` | Reasoning effort: `none`, `minimal`, `low`, `medium`, `high` |
| `CHAT_EFFORT` | `low` | Same, for the chatbot |

If your OpenAI account can't use a model, the ingestion log says the model wasn't found. Set these to a model your account has.

### Pinecone
| Variable | Default | Purpose |
|---|---|---|
| `PINECONE_INDEX` | `igcse-rag` | Index name (use `igcse-rag-prod` on Railway) |
| `PINECONE_CLOUD` / `PINECONE_REGION` | `aws` / `us-east-1` | Where a new index is created |

### Behaviour
| Variable | Default | Purpose |
|---|---|---|
| `RELEVANCE_THRESHOLD` | `0.35` | Chatbot: below this relevance score it searches the web instead. Raise it if local answers are off-topic; lower it if it goes to the web too often. |
| `DEDUP_SIMILARITY` | `0.92` | Ingestion: questions this similar to an existing one are treated as duplicates |
| `PAPER_DIVERSITY_SIMILARITY` | `0.85` | Papers: no two questions more similar than this |
| `CHUNK_MIN_TOKENS` / `CHUNK_MAX_TOKENS` / `CHUNK_OVERLAP` | `200` / `400` / `40` | Size of searchable text chunks |
| `MAX_CONCURRENCY` | `5` | Files processed in parallel during ingestion. Lower it if you hit OpenAI rate limits. |

### Deployment and access
| Variable | Default | Purpose |
|---|---|---|
| `STORAGE_DIR` | project folder (`/storage` in Docker) | Where `data`, `output` and `logs` are kept |
| `APP_PASSWORD` | not set | Shared team password. Not set means no password. |
| `AUTH_CLIENT_ID`, `AUTH_CLIENT_SECRET`, `AUTH_COOKIE_SECRET` | not set | Google/Microsoft sign-in (see 6.8) |
| `AUTH_SERVER_METADATA_URL` | Google | Sign-in provider |
| `AUTH_REDIRECT_URI` | `https://<Railway domain>/oauth2callback` | Only needed with a custom domain |
| `ALLOWED_EMAILS`, `ALLOWED_EMAIL_DOMAINS` | not set | Who may sign in |

### Appearance
The colours and fonts are in [.streamlit/config.toml](.streamlit/config.toml): `primaryColor` under `[theme.light]` is the main colour, and `backgroundColor` under `[theme.light.sidebar]` is the sidebar colour. Restart the app after editing.

---

## 9. Costs

| Service | What drives cost | Tips |
|---|---|---|
| OpenAI | **Ingestion** (about one large call per paper, plus a small one per batch of questions) and chatbot answers | Each file is processed once; unchanged files are skipped. Set a monthly budget limit in OpenAI's billing settings. |
| Pinecone | Number of stored chunks and searches | The free plan covers a few thousand papers. |
| Tavily | Web searches (only when local documents don't answer) | The free allowance is usually enough. |
| Railway | Running time, memory and volume size | Check the project's **Usage** page. A volume of under 1 GB is enough for hundreds of papers. |

Re-ingesting files on Railway that you already ingested locally costs OpenAI calls again.

---

## 10. Security

- **Keys:** `.env` is never committed (it's in `.gitignore`) and never copied into the Docker image (it's in `.dockerignore`). On Railway, keys live only in **Variables**.
- **Access:** always turn on `APP_PASSWORD` or sign-in before sharing the deployed address. Every visitor uses your API credits.
- **What leaves your machine:** document text is sent to OpenAI (extraction) and Pinecone (search). Chatbot questions that aren't answered locally are sent to Tavily.
- **If a key leaks:** revoke it at the provider straight away, create a new one, and update `.env` and Railway Variables.

---

## 11. Troubleshooting

### Running locally
| Problem | Fix |
|---|---|
| `running scripts is disabled` when activating | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Sidebar says "Missing settings: …" | Add those keys to `.env` and restart the app |
| `OpenAI rejected the API key` | Check `OPENAI_API_KEY`; a Windows environment variable overrides `.env` |
| `OpenAI model not found` | Set `EXTRACTION_MODEL` / `CHAT_MODEL` / `CLASSIFIER_MODEL` to models your account can use |
| `OpenAI rate limit or quota reached` | Check billing; lower `MAX_CONCURRENCY` |
| Theme or settings changes don't show | Stop (`Ctrl+C`) and restart `streamlit run app.py` |

### Ingestion
| Problem | Fix |
|---|---|
| "name isn't a CAIE code; the LLM will infer the details" | Information only. Rename to the Cambridge pattern ([section 5](#5-preparing-documents)) for full details and mark-scheme linking. |
| "An ingestion run is already in progress" | Another tab is ingesting. Wait for it to finish. |
| Run stopped part-way | Something on the page was clicked during ingestion. Run it again; finished files are skipped. |
| A file shows **failed** | Read the message in the summary table, or the newest file in `logs`. Failed files are cleaned up and retried automatically on the next run. |
| Diagrams missing or cropped wrongly | Diagram cropping is position-based and works best on digital PDFs. Check the images in `data\images`. |
| Extracted question wording differs from the PDF | Re-ingest with **Force re-ingest**. If it persists, try `EXTRACTION_EFFORT=high`. |

### Generating papers
| Problem | Fix |
|---|---|
| "Only N questions found…" warning | Fewer questions match the filters. Widen topics, years or difficulty, or ingest more papers. |
| "Section counts add up to X…" | Make Section A + B + C equal the number of questions, or set all three to 0. |
| "Mark scheme not available" in the mark scheme | Upload the matching `_ms_` file with a Cambridge file name. |

### Railway
| Problem | Fix |
|---|---|
| Deployment **Failed** or **Crashed** | App → **Deployments** → the failed deployment → **View logs**. |
| Address shows "Application failed to respond" | App still starting or crashed: check **Deployments**. Or the domain's port is wrong: set it to the port in the logs ("Local URL: http://localhost:XXXX"), usually 8080. |
| No password screen | `APP_PASSWORD` is missing or misspelled, or the changes weren't deployed. |
| Data disappears after a redeploy | No volume, or the mount path isn't exactly `/storage`. |
| Sign-in error `redirect_uri_mismatch` | The redirect URI in Google/Microsoft must be exactly `https://<address>/oauth2callback`. |
| Logs: "AUTH_CLIENT_ID is set, so … are required too" | Add `AUTH_CLIENT_SECRET` and `AUTH_COOKIE_SECRET`. |

### Git
| Problem | Fix |
|---|---|
| `src refspec main does not match any` | `git branch -M main`, then `git push -u origin main` |
| Push rejected because the remote has commits | `git pull origin main --allow-unrelated-histories`, then push again |

---

## 12. Project structure

```
IGCSE_ModelQuestion/
├─ app.py                  Streamlit entry point (navigation, sidebar, access gate)
├─ app_pages/              Ingest, Generate Paper and Chatbot pages
├─ auth.py                 Team password / Google–Microsoft sign-in
├─ config.py               All settings, read from .env / environment variables
├─ llm.py                  OpenAI calls (structured output, streaming)
├─ ingest/                 Reading, cleaning, extraction, difficulty, diagrams, chunking, pipeline
├─ store/                  Pinecone and SQLite catalog access
├─ paper/                  Question selection, paper assembly, PDF and Word export
├─ chat/                   Chatbot retrieval and web search
├─ .streamlit/config.toml  Theme (colours, fonts)
├─ Dockerfile, docker/, railway.json, .dockerignore   Deployment
├─ doc/specification.md    Functional specification
├─ doc/deploy_railway.md   Detailed Railway notes
├─ .env.example            Settings template (copy to .env)
└─ requirements.txt        Python packages
```

Folders created at runtime (not in Git): `data/` (uploads, `catalog.db`, cropped `images/`), `output/` (generated papers) and `logs/` (one log per ingestion run).
