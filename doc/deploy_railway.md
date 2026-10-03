# Deploying to Railway

The app runs on Railway as a Docker container, with one **volume** for the catalog, cropped diagrams, generated papers and logs. The repository already contains everything Railway needs:

| File | Purpose |
|---|---|
| `Dockerfile` | Python 3.12 image with fonts for PDF export |
| `docker/entrypoint.sh` | Writes sign-in settings from variables, starts Streamlit on Railway's `PORT` |
| `railway.json` | Tells Railway to build the Dockerfile and use `/_stcore/health` as the health check |
| `.dockerignore` | Keeps `.env`, `.venv` and local data out of the image |

---

## 1. Put the code on GitHub

Railway deploys from a GitHub repository. Create a **private** repository and push the project:

```powershell
cd C:\Asphero\IGCSE_ModelQuestion
git init
git add .
git commit -m "IGCSE model paper agent"
git branch -M main
git remote add origin https://github.com/<you>/igcse-model-paper.git
git push -u origin main
```

`.gitignore` already excludes `.env`, `.venv`, `data/`, `output/` and `logs/`, so keys and local data are not uploaded.

> Alternative without GitHub: install the Railway CLI (`npm i -g @railway/cli`), then `railway login`, `railway init` and `railway up` from the project folder.

## 2. Create the Railway service

1. Sign in at railway.com → **New Project** → **Deploy from GitHub repo** → choose the repository.
2. Railway detects `railway.json` and builds the `Dockerfile`. The first build takes a few minutes.

## 3. Add a volume (required)

Without a volume, the catalog and generated papers are lost on every redeploy.

1. Open the service → right-click on the canvas or use **+ New** → **Volume**, and attach it to the service.
2. Set the **mount path** to `/storage`.

The image already sets `STORAGE_DIR=/storage`. Keep the service at **one replica**: the SQLite catalog and the one-ingestion-at-a-time lock assume a single instance.

## 4. Set the variables

Service → **Variables** → add:

| Variable | Value |
|---|---|
| `OPENAI_API_KEY` | your OpenAI key |
| `PINECONE_API_KEY` | your Pinecone key |
| `TAVILY_API_KEY` | your Tavily key |
| `PINECONE_INDEX` | `igcse-rag-prod` (recommended, see note below) |

Optional: any setting from `.env.example` (models, thresholds) can be added the same way.

**Use a separate Pinecone index for Railway.** The catalog on Railway's volume starts empty. If Railway and your PC share one index, each catalog only knows its own files and the two drift apart. A separate index name keeps them independent. The app creates the index on first ingestion.

## 5. Give it a public address

Service → **Settings** → **Networking** → **Generate Domain**. You get a URL like `https://igcse-model-paper-production.up.railway.app`.

## 6. Restrict access (do this before sharing the URL)

Every visitor spends your OpenAI, Pinecone and Tavily credits, so turn on one of these.

### Option A: shared team password (quickest)

Add the variable `APP_PASSWORD` with a strong password and share it with the team.

### Option B: sign in with Google (recommended)

1. In Google Cloud Console → **APIs & Services** → **Credentials** → **Create credentials** → **OAuth client ID** → type **Web application**. (Set up the OAuth consent screen first if asked; "Internal" limits it to your Google Workspace.)
2. Under **Authorised redirect URIs** add: `https://<your-railway-domain>/oauth2callback`
3. Add these Railway variables:

| Variable | Value |
|---|---|
| `AUTH_CLIENT_ID` | the client ID from Google |
| `AUTH_CLIENT_SECRET` | the client secret from Google |
| `AUTH_COOKIE_SECRET` | a random string; generate one with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ALLOWED_EMAIL_DOMAINS` | e.g. `yourschool.edu` (comma-separated), and/or |
| `ALLOWED_EMAILS` | e.g. `alice@gmail.com,bob@gmail.com` |

The redirect URI is built automatically from Railway's domain. If you use a custom domain, also set `AUTH_REDIRECT_URI=https://<custom-domain>/oauth2callback`.

**Microsoft accounts instead of Google:** register an app in Microsoft Entra ID with the same redirect URI, use its client ID and secret, and add
`AUTH_SERVER_METADATA_URL=https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration`.

If sign-in is configured, `APP_PASSWORD` is ignored. Without `ALLOWED_EMAILS` / `ALLOWED_EMAIL_DOMAINS`, any Google account can sign in, so always set one of them.

## 7. Load papers

Open the app → **Ingest** → **Upload files**. Choose whether the files are papers or notes, drop them in, and click **Upload and ingest**. Keep Cambridge file names (`0620_s23_qp_42.pdf`) so mark schemes link to their papers.

Changing a variable triggers a redeploy; data on the volume is kept.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Deploy fails the health check | Open **Deployments → View logs**. Usually a missing package or a crash at start. |
| Sign-in loops or shows "redirect_uri_mismatch" | The redirect URI in Google/Microsoft must exactly match `https://<domain>/oauth2callback`. |
| "AUTH_CLIENT_ID is set, so ... are required too" in logs | Add `AUTH_CLIENT_SECRET` and `AUTH_COOKIE_SECRET`. |
| Papers and catalog disappear after a redeploy | The volume isn't attached or isn't mounted at `/storage`. |
| Sidebar says "Missing settings" | Add the listed variables in Railway and wait for the redeploy. |

## Testing the image locally (optional)

```powershell
docker build -t igcse-agent .
docker run --rm -p 8501:8080 -e PORT=8080 --env-file .env -v igcse-data:/storage igcse-agent
```

Then open http://localhost:8501.
