#!/bin/sh
# Container start: prepare storage, write sign-in secrets from environment variables, start Streamlit.
set -e

mkdir -p "${STORAGE_DIR:-/storage}"

# Sign-in (st.login) is enabled when AUTH_CLIENT_ID is set. Streamlit reads it from .streamlit/secrets.toml.
if [ -n "$AUTH_CLIENT_ID" ]; then
  if [ -z "$AUTH_CLIENT_SECRET" ] || [ -z "$AUTH_COOKIE_SECRET" ]; then
    echo "AUTH_CLIENT_ID is set, so AUTH_CLIENT_SECRET and AUTH_COOKIE_SECRET are required too." >&2
    exit 1
  fi
  # Railway provides RAILWAY_PUBLIC_DOMAIN once a public domain is generated.
  REDIRECT_URI="${AUTH_REDIRECT_URI:-https://${RAILWAY_PUBLIC_DOMAIN}/oauth2callback}"
  METADATA_URL="${AUTH_SERVER_METADATA_URL:-https://accounts.google.com/.well-known/openid-configuration}"
  mkdir -p .streamlit
  cat > .streamlit/secrets.toml <<EOF
[auth]
redirect_uri = "${REDIRECT_URI}"
cookie_secret = "${AUTH_COOKIE_SECRET}"
client_id = "${AUTH_CLIENT_ID}"
client_secret = "${AUTH_CLIENT_SECRET}"
server_metadata_url = "${METADATA_URL}"
EOF
  echo "Sign-in enabled; redirect URI: ${REDIRECT_URI}"
fi

exec streamlit run app.py \
  --server.port "${PORT:-8501}" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false
