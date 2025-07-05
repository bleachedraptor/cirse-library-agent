# cirse_streamlit/cirse_app.py  (v3 – installs Chromium every time a fresh container starts)

from __future__ import annotations
import asyncio, importlib, subprocess, sys, os
from pathlib import Path
from typing import List
import streamlit as st

# Helper import‑or‑install
def _ensure(pkg: str):
    try:
        return importlib.import_module(pkg)
    except ModuleNotFoundError:
        st.warning(f'Installing {pkg} …')
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])
        return importlib.import_module(pkg)

playwright_async = _ensure('playwright.async_api')
cirse_agent      = importlib.import_module('cirse_streamlit.cirse_agent', package='cirse_streamlit')

# Download browser binaries if missing
def _install_chromium():
    cache_dir = Path.home()/'.cache'/'ms-playwright'
    headless = next(cache_dir.glob('**/headless_shell'), None)
    if headless and headless.exists():
        return
    st.info('Downloading headless Chromium (first‑run, ~40 s)…')
    subprocess.run([sys.executable,'-m','playwright','install','chromium'], check=True)

_install_chromium()

st.set_page_config(page_title='CIRSE Library Agent', layout='wide')
st.title('📚 CIRSE Library Agent')

with st.expander('Credentials (session only)'):
    CIRSE_EMAIL    = st.text_input('CIRSE email')
    CIRSE_PASSWORD = st.text_input('CIRSE password', type='password')
    OPENAI_API_KEY = st.text_input('OpenAI API key', type='password')

query = st.text_input('Search term', placeholder='e.g. mesenteric ischemia')
top_n = st.slider('Max results', 1, 50, 10)

def _browser(pw):
    return pw.chromium.launch(headless=True, args=['--no-sandbox'])

if st.button('Search'):
    if not all([CIRSE_EMAIL, CIRSE_PASSWORD, OPENAI_API_KEY, query]):
        st.error('Fill in every box.')
        st.stop()

    os.environ.update(
        CIRSE_EMAIL=CIRSE_EMAIL,
        CIRSE_PASSWORD=CIRSE_PASSWORD,
        OPENAI_API_KEY=OPENAI_API_KEY,
    )

    async def do_search():
        async with playwright_async.async_playwright() as pw:
            browser = await _browser(pw)
            page = await browser.new_page()
            await cirse_agent.playwright_login(page)
            hits = await cirse_agent.search_videos(page, query, max_results=top_n)
            await browser.close()
            return hits

    results: List[cirse_agent.VideoResult] = asyncio.run(do_search())
    if not results:
        st.warning('No results')
        st.stop()

    st.subheader('Results')
    indices = []
    for i, r in enumerate(results):
        if st.checkbox(f"{r.title} ({r.year or 'n/a'}) – {r.speaker or 'Unknown'}", key=i):
            indices.append(i)

    if indices and st.button('Process selected'):
        progress = st.progress(0.0)
        out_dir = Path('cirse_notes'); out_dir.mkdir(exist_ok=True)

        async def do_process():
            total = len(indices)
            async with playwright_async.async_playwright() as pw:
                for n, idx in enumerate(indices, 1):
                    progress.progress((n-1)/total, f'Processing {results[idx].title[:60]}…')
                    await cirse_agent.process_video(pw, 'https://library.cirse.org', results[idx], out_dir)
                progress.progress(1.0, 'Done!')

        asyncio.run(do_process())

        for md in out_dir.glob('*.md'):
            st.download_button(f'Download {md.name}', md.read_bytes(), file_name=md.name, mime='text/markdown')
