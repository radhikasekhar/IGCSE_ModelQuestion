"""Streamlit entry point: Ingest | Generate Paper | Chatbot."""
import streamlit as st

import auth
import config
from store import catalog

st.set_page_config(page_title="IGCSE Model Paper Agent", page_icon=":material/school:", layout="wide")
auth.require_access()
catalog.init_db()

page = st.navigation(
    [
        st.Page("app_pages/ingest.py", title="Ingest", icon=":material/upload_file:"),
        st.Page("app_pages/generate.py", title="Generate Paper", icon=":material/description:", default=True),
        st.Page("app_pages/chat.py", title="Chatbot", icon=":material/forum:"),
    ],
    position="top",
)

with st.sidebar:
    st.header(":material/school: IGCSE Paper Agent")
    st.caption("Model question papers and subject tutor, built from your own past papers and notes.")
    stats = catalog.stats()
    c1, c2 = st.columns(2)
    c1.metric("Files", stats["files"])
    c2.metric("Questions", stats["questions"])
    c1.metric("Note chunks", stats["notes"])
    c2.metric("Mark schemes", stats["mark_schemes"])
    missing = config.missing_keys()
    if missing:
        st.warning("Missing settings: " + ", ".join(f"`{k}`" for k in missing), icon=":material/key_off:")
    else:
        st.caption(":material/check_circle: API keys configured")
    st.caption(f"Pinecone index: `{config.PINECONE_INDEX}`")
    auth.sidebar_account()

page.run()
