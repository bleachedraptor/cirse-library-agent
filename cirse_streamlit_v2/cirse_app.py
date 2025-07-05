
# cirse_app.py  (v2 - auto‑fixes Playwright launch on Streamlit Cloud)

from __future__ import annotations
import asyncio, importlib, subprocess, sys, os, shutil
from pathlib import Path
from typing import List

import streamlit as st

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
# One‑off: download Playwright browser binaries on first run (Streamlit Cloud
# containers start blank). We also add "--no‑sandbox" arg required in many
# locked‑down Linux containers.
# ---------------------------------------------------------------------------
def _ensure_playwright_browsers():
    # Check if chromium binary already exists
    cache_dir = Path.home() / ".cache" / "ms-playwright"
    chromium_installed = any(p.name.startswith("chromium") for p in cache_dir.glob("*"))
    if not chromium_installed:
        st.info("Downloading headless Chromium (first‑run, takes ~40 s)…")
        subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"], check=True)

_ensure_playwright_browsers()

st.set_page_config(page_title='CIRSE Library Agent', layout='wide')
st.title('📚 CIRSE Library Agent')

with st.expander('Credentials (stored only for this session)'):
    CIRSE_EMAIL    = st.text_input('CIRSE email', value=os.getenv('CIRSE_EMAIL', ''))
    CIRSE_PASSWORD = st.text_input('CIRSE password', type='password', value=os.getenv('CIRSE_PASSWORD', ''))
    OPENAI_API_KEY = st.text_input('OpenAI API key', type='password', value=os.getenv('OPENAI_API_KEY', ''))

query = st.text_input('Search term', placeholder='e.g. mesenteric ischemia')
top_n = st.slider('Max results', 1, 50, 10)

if st.button('Search'):
    if not (CIRSE_EMAIL and CIRSE_PASSWORD and OPENAI_API_KEY and query):
        st.error('Please fill in all fields.')
        st.stop()

    os.environ.update(
        CIRSE_EMAIL=CIRSE_EMAIL,
        CIRSE_PASSWORD=CIRSE_PASSWORD,
        OPENAI_API_KEY=OPENAI_API_KEY,
    )

    async def _launch_browser():
        try:
            return await playwright_async.async_playwright().start().chromium.launch(
                headless=True, args=["--no-sandbox"]
            )
        except Exception as e:
            # If launch failed after browsers supposedly installed, show full traceback
            st.exception(e)
            raise

    async def do_search():
        pw = await playwright_async.async_playwright().start()
        browser = await _launch_browser()
        page = await browser.new_page()
        await cirse_agent.playwright_login(page)
        results: List[cirse_agent.VideoResult] = await cirse_agent.search_videos(page, query, max_results=top_n)
        await browser.close()
        await pw.stop()
        return results

    results = asyncio.run(do_search())

    if not results:
        st.warning('No results.')
        st.stop()

    st.subheader('Results')
    selections = []
    for idx, r in enumerate(results):
        if st.checkbox(f"{r.title} ({r.year or 'n/a'}) – {r.speaker or 'Unknown'}", key=idx):
            selections.append(idx)

    if selections and st.button('Process selected'):
        progress = st.progress(0.0)
        workdir = Path('cirse_notes'); workdir.mkdir(exist_ok=True)

        async def do_process():
            pw = await playwright_async.async_playwright().start()
            browser = await _launch_browser()
            total = len(selections)
            for n, idx in enumerate(selections, 1):
                pct = (n-1)/total
                progress.progress(pct, f'Processing {results[idx].title[:60]}…')
                await cirse_agent.process_video(pw, 'https://library.cirse.org', results[idx], workdir)
            progress.progress(1.0, 'Done!')
            await browser.close()
            await pw.stop()

        asyncio.run(do_process())

        for md in workdir.glob('*.md'):
            st.download_button(
                f'Download {md.name}',
                md.read_bytes(),
                file_name=md.name,
                mime='text/markdown',
            )
