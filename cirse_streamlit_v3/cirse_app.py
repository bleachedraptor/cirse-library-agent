
# cirse_app.py  (v3 – always downloads Chromium if missing)

from __future__ import annotations
import asyncio, importlib, subprocess, sys, os
from pathlib import Path
from typing import List
import streamlit as st

# --- Helper to import‑or‑install ------------------------------------------
def _ensure(pkg: str):
    try:
        return importlib.import_module(pkg)
    except ModuleNotFoundError:
        st.warning(f'Installing missing package: {pkg} …')
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])
        return importlib.import_module(pkg)

playwright_async = _ensure('playwright.async_api')
cirse_agent      = importlib.import_module('cirse_agent')

# ---------------------------------------------------------------------------
# Force‑install Playwright browsers every time a **fresh** container starts
# (takes ~40 s, but only happens once per Streamlit Cloud instance).
# ---------------------------------------------------------------------------
def _install_chromium():
    CACHE = Path.home() / '.cache' / 'ms-playwright'
    headless_shell = next(CACHE.glob('**/headless_shell'), None)
    if headless_shell and headless_shell.exists():
        return  # already installed
    st.info('Downloading headless Chromium (first‑run, ~40 s)…')
    try:
        subprocess.run(
            [sys.executable, '-m', 'playwright', 'install', 'chromium'],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        st.error('Failed to download Chromium. See logs.')
        st.exception(e)
        raise

_install_chromium()

# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title='CIRSE Library Agent', layout='wide')
st.title('📚 CIRSE Library Agent')

with st.expander('Credentials (these stay only for this session)'):
    CIRSE_EMAIL    = st.text_input('CIRSE email', value=os.getenv('CIRSE_EMAIL', ''))
    CIRSE_PASSWORD = st.text_input('CIRSE password', type='password', value=os.getenv('CIRSE_PASSWORD', ''))
    OPENAI_API_KEY = st.text_input('OpenAI API key', type='password', value=os.getenv('OPENAI_API_KEY', ''))

query = st.text_input('Search term', placeholder='e.g. mesenteric ischemia')
top_n = st.slider('Max results', 1, 50, 10)

def _launch_browser(pw):
    # Streamlit Cloud blocks sandboxing; disable it.
    return pw.chromium.launch(headless=True, args=['--no-sandbox'])

if st.button('Search'):
    if not (CIRSE_EMAIL and CIRSE_PASSWORD and OPENAI_API_KEY and query):
        st.error('Please fill in every box.')
        st.stop()

    os.environ.update(
        CIRSE_EMAIL=CIRSE_EMAIL,
        CIRSE_PASSWORD=CIRSE_PASSWORD,
        OPENAI_API_KEY=OPENAI_API_KEY,
    )

    async def do_search() -> List[cirse_agent.VideoResult]:
        async with playwright_async.async_playwright() as pw:
            browser = await _launch_browser(pw)
            page = await browser.new_page()
            await cirse_agent.playwright_login(page)
            hits = await cirse_agent.search_videos(page, query, max_results=top_n)
            await browser.close()
            return hits

    results = asyncio.run(do_search())

    if not results:
        st.warning('No results.')
        st.stop()

    st.subheader('Results')
    picks = []
    for idx, r in enumerate(results):
        if st.checkbox(f"{r.title} ({r.year or 'n/a'}) – {r.speaker or 'Unknown'}", key=idx):
            picks.append(idx)

    if picks and st.button('Process selected'):
        progress = st.progress(0.0)
        workdir = Path('cirse_notes'); workdir.mkdir(exist_ok=True)

        async def do_process():
            total = len(picks)
            async with playwright_async.async_playwright() as pw:
                for n, idx in enumerate(picks, 1):
                    pct = (n - 1) / total
                    progress.progress(pct, f'Processing {results[idx].title[:60]}…')
                    await cirse_agent.process_video(pw, 'https://library.cirse.org', results[idx], workdir)
                progress.progress(1.0, 'Done!')

        asyncio.run(do_process())

        for md in workdir.glob('*.md'):
            st.download_button(
                f'Download {md.name}',
                md.read_bytes(),
                file_name=md.name,
                mime='text/markdown'
            )
