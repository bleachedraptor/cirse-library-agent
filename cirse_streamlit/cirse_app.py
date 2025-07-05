
# cirse_app.py
"""
Streamlit GUI wrapper for cirse_agent.py

Launch with:
    streamlit run cirse_app.py
"""

from __future__ import annotations
import asyncio, importlib, subprocess, sys, os
from pathlib import Path
from typing import List

import streamlit as st

# ---------------------------------------------------------------------------
# dynamic dependency install for non‑coders
# ---------------------------------------------------------------------------
def _ensure(pkg: str):
    try:
        return importlib.import_module(pkg)
    except ModuleNotFoundError:
        st.warning(f'Installing {pkg}… (first‑run only)')
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])
        return importlib.import_module(pkg)

playwright_async = _ensure('playwright.async_api')
cirse_agent = importlib.import_module('cirse_agent')

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
        st.error('Please fill all fields')
        st.stop()

    os.environ.update(
        CIRSE_EMAIL=CIRSE_EMAIL,
        CIRSE_PASSWORD=CIRSE_PASSWORD,
        OPENAI_API_KEY=OPENAI_API_KEY,
    )

    async def do_search():
        async with playwright_async.async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            await cirse_agent.playwright_login(page)
            res: List[cirse_agent.VideoResult] = await cirse_agent.search_videos(page, query, top_n)
            await browser.close()
            return res

    results = asyncio.run(do_search())

    if not results:
        st.warning('No results.')
        st.stop()

    st.subheader('Results')
    selections = []
    for idx, r in enumerate(results):
        if st.checkbox(f"{r.title} ({r.year or 'n/a'}) – {r.speaker or 'Unknown'}", key=idx):
            selections.append(idx)

    if st.button('Process selected') and selections:
        progress = st.progress(0.0)
        workdir = Path('cirse_notes'); workdir.mkdir(exist_ok=True)

        async def do_process():
            async with playwright_async.async_playwright() as pw:
                total = len(selections)
                for n, idx in enumerate(selections, 1):
                    pct = (n-1)/total
                    progress.progress(pct, f'Processing {results[idx].title[:60]}…')
                    await cirse_agent.process_video(pw, 'https://library.cirse.org', results[idx], workdir)
                progress.progress(1.0, 'Done!')

        asyncio.run(do_process())

        for md in workdir.glob('*.md'):
            st.download_button(
                f'Download {md.name}',
                md.read_bytes(),
                file_name=md.name,
                mime='text/markdown',
            )
