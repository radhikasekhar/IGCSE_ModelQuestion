"""Chatbot tab: answers from ingested documents first, then from the web (clearly labelled)."""
import streamlit as st

import config
from chat import rag_chat
from store import catalog

st.title("Subject chatbot")
st.caption(
    "Answers come from your ingested notes and past papers first. If nothing relevant is found, "
    "the answer is sourced from the web and clearly marked as external."
)

if "chat" not in st.session_state:
    st.session_state.chat = []

top = st.columns([3, 1])
subject = top[0].selectbox("Subject", ["All subjects", *catalog.list_subjects()])
if top[1].button("Clear chat", icon=":material/delete_sweep:"):
    st.session_state.chat = []
    st.rerun()

for msg in st.session_state.chat:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

SUGGESTIONS = {
    ":material/menu_book: Explain a concept": "Explain the difference between speed and velocity.",
    ":material/quiz: Find past questions": "Show me past paper questions on moments.",
    ":material/functions: Formula help": "What is the formula for the resistance of resistors in parallel?",
}
prompt = st.chat_input("Ask any subject question")
if not st.session_state.chat and not prompt:
    picked = st.pills("Try asking:", list(SUGGESTIONS), label_visibility="collapsed")
    if picked:
        prompt = SUGGESTIONS[picked]

if prompt:
    if config.missing_keys():
        st.error("Configure " + ", ".join(config.missing_keys()) + " in `.env` to use the chatbot.",
                 icon=":material/key_off:")
        st.stop()
    history = list(st.session_state.chat)
    st.session_state.chat.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        try:
            with st.spinner("Searching ingested documents…"):
                retrieval, stream = rag_chat.answer(
                    prompt, history, None if subject == "All subjects" else subject
                )
            if retrieval.local:
                st.caption(f":material/folder_open: Answered from ingested documents (relevance {retrieval.best_score:.2f})")
            else:
                st.caption(":material/public: Not found locally, so searched the web")
            reply = st.write_stream(stream)
        except Exception as exc:
            reply = f"Sorry, something went wrong: {exc}"
            st.error(reply, icon=":material/error:")
    st.session_state.chat.append({"role": "assistant", "content": reply if isinstance(reply, str) else str(reply)})
