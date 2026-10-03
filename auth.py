"""Access control for deployed use.

1. Sign-in (Google, Microsoft or any OIDC provider) when .streamlit/secrets.toml has an [auth]
   section, restricted to ALLOWED_EMAILS / ALLOWED_EMAIL_DOMAINS if those are set.
2. Otherwise a shared APP_PASSWORD, if set.
3. Otherwise open (local development).
"""
from __future__ import annotations

import hmac

import streamlit as st

import config


def _oidc_configured() -> bool:
    try:
        return "auth" in st.secrets
    except Exception:  # no secrets.toml at all
        return False


def _email_allowed(email: str) -> bool:
    if not config.ALLOWED_EMAILS and not config.ALLOWED_EMAIL_DOMAINS:
        return True
    email = email.lower()
    return email in config.ALLOWED_EMAILS or email.rsplit("@", 1)[-1] in config.ALLOWED_EMAIL_DOMAINS


def _login_screen(body: str):
    _, mid, _ = st.columns([1, 2, 1])
    with mid, st.container(border=True):
        st.title(":material/school: IGCSE Paper Agent")
        st.write(body)
        inner = st.container()
    return inner


def require_access() -> None:
    """Stop the script unless the visitor is allowed in."""
    if _oidc_configured():
        if not st.user.is_logged_in:
            box = _login_screen("Sign in with your organisation account to continue.")
            box.button("Sign in", icon=":material/login:", type="primary", on_click=st.login)
            st.stop()
        email = str(st.user.get("email") or "")
        if not _email_allowed(email):
            box = _login_screen(f"**{email or 'This account'}** doesn't have access to this app. "
                                "Ask the app owner to add you, or sign in with another account.")
            box.button("Sign out", icon=":material/logout:", on_click=st.logout)
            st.stop()
        return

    if config.APP_PASSWORD and not st.session_state.get("password_ok"):
        box = _login_screen("Enter the team password to continue.")
        with box.form("password"):
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Enter", type="primary"):
                if hmac.compare_digest(pw.encode(), config.APP_PASSWORD.encode()):
                    st.session_state.password_ok = True
                    st.rerun()
                st.error("Incorrect password.")
        st.stop()


def sidebar_account() -> None:
    """Signed-in user and a sign-out button, when sign-in is enabled."""
    if _oidc_configured() and st.user.is_logged_in:
        st.caption(f":material/account_circle: {st.user.get('email') or st.user.get('name') or 'Signed in'}")
        st.button("Sign out", icon=":material/logout:", on_click=st.logout)
    elif config.APP_PASSWORD and st.session_state.get("password_ok"):
        if st.button("Lock", icon=":material/lock:"):
            st.session_state.password_ok = False
            st.rerun()
