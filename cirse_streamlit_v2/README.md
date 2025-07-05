
# CIRSE Library Agent (Streamlit)

A one‑click web app to search the CIRSE video library, transcribe selected lectures
with OpenAI Whisper, and generate concise bullet‑point notes via GPT‑4o-mini.

## Local quick‑start

```bash
pip install -r requirements.txt
playwright install
streamlit run cirse_app.py
```

## Deploy to Streamlit Community Cloud

1. Fork / import this repo to your GitHub account.
2. Sign in at <https://share.streamlit.io> using GitHub.
3. Click **Create app → Paste GitHub URL**, enter `cirse_app.py` as the
   entry‑point file, and hit **Deploy**.
4. Add your secrets (`CIRSE_EMAIL`, `CIRSE_PASSWORD`, `OPENAI_API_KEY`)
   via **App → Edit secrets** (do NOT commit them to the repo).

Done! Your free public URL will look like:
`https://<your‑username>-cirse-library-agent-streamlit-app.streamlit.app`
