# IGCSE Model Question Paper Agent: Project Summary

## What it is
A web app that turns a school's own Cambridge IGCSE past papers, mark schemes and notes into ready-to-use model question papers and a subject chatbot for students and teachers.

## What it does
- **Reads and organises documents.** Upload past papers, mark schemes and notes (PDF, Word, text, web pages or images). The app extracts every question, records its marks, topic, difficulty and section, keeps its diagrams, and links it to its mark-scheme answer.
- **Generates model papers.** Teachers choose subject, topics, difficulty, years and number of questions, and get an exam-style paper in Sections A (short), B (long) and C (application). It downloads as PDF or Word with a matching mark scheme. Questions are copied word for word from the source papers, with no AI-written questions and no near-duplicates. Any paper can be reproduced from its seed number.
- **Answers subject questions.** The chatbot answers from the school's own notes and papers first, citing file and page. When those don't cover a question, it searches the web and clearly labels the answer as coming from external sources.

## How it's built

| Part | Technology |
|---|---|
| AI extraction, difficulty rating and chatbot | OpenAI (`gpt-5.5`, `gpt-5.4-mini`) |
| Search by meaning | Pinecone vector database |
| Web search fallback | Tavily |
| Question catalog | SQLite |
| Web interface | Streamlit, with an academic exam-board theme |
| Hosting | Railway (Docker container with a permanent storage volume) |

## Current status
- **Built and tested:** ingestion, paper generation with PDF/Word export, the chatbot, and password protection. The full ingestion run against the live OpenAI and Pinecone services has been tested and its early bugs fixed.
- **Deployment:** being set up on Railway, protected by a shared team password. Google or Microsoft sign-in is ready to switch on.
- **Documentation:** a setup and deployment guide (`README.md`), a functional specification (`doc/specification.md`) and Railway notes (`doc/deploy_railway.md`) are in the repository.

## Next steps
1. Finish the Railway deployment and upload the first set of past papers, renamed to Cambridge file names so mark schemes link.
2. Have the team review generated papers and chatbot answers for accuracy.
3. Review costs after the first week of use, mainly OpenAI usage during ingestion.
4. Optionally, switch to Google or Microsoft sign-in, and fine-tune the chatbot's relevance threshold and difficulty ratings with real papers.
