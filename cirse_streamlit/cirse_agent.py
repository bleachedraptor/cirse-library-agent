# cirse_streamlit/cirse_agent.py
"""
Core helper for logging into CIRSE Library, searching videos, downloading audio,
transcribing with Whisper, and summarising with GPT‑4o‑mini.

Designed to be imported by cirse_app.py or run via CLI (`python cirse_agent.py --query ...`).

Key features:
* Auto‑installs its own dependencies the first time they’re missing.
* Uses Playwright (headless) to handle login and scraping.
* Keeps code readable for future tweaks.
"""

import importlib, subprocess, sys, os, re, asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Lazy dep loader so non-coders don't need pip on the command line
# ---------------------------------------------------------------------------
def _ensure(pkg: str):
    try:
        return importlib.import_module(pkg)
    except ModuleNotFoundError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])
        return importlib.import_module(pkg)

dotenv     = _ensure('python_dotenv') if _ensure('importlib').util.find_spec('python_dotenv') else _ensure('dotenv')
openai     = _ensure('openai')
rich       = _ensure('rich')
yt_dlp     = _ensure('yt_dlp')
playwright = _ensure('playwright.async_api')

from rich.progress import Progress

dotenv.load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
CIRSE_EMAIL    = os.getenv('CIRSE_EMAIL')
CIRSE_PASSWORD = os.getenv('CIRSE_PASSWORD')

@dataclass
class VideoResult:
    title: str
    url: str
    year: Optional[str] = None
    speaker: Optional[str] = None

# ---------------------------------------------------------------------------
# Playwright helpers
# ---------------------------------------------------------------------------
async def playwright_login(page):
    """Log into myCIRSE using credentials from env vars."""
    await page.goto('https://my.cirse.org')
    await page.fill('input[name="email"]', CIRSE_EMAIL)
    await page.fill('input[type="password"]', CIRSE_PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_load_state('networkidle')

async def search_videos(page, query: str, max_results: int = 10) -> List[VideoResult]:
    search_url = f'https://library.cirse.org/search?q={query}'
    await page.goto(search_url)
    await page.wait_for_selector('.search-result')
    cards = await page.query_selector_all('.search-result')[:max_results]
    results = []
    for card in cards:
        title = await card.query_selector_eval('.result-title', 'el => el.textContent.trim()')
        url   = await card.query_selector_eval('a', 'el => el.href')
        year = await card.query_selector_eval('.result-year', 'el => el.textContent.trim()', force_expr=True) or None
        speaker = await card.query_selector_eval('.result-speaker', 'el => el.textContent.trim()', force_expr=True) or None
        results.append(VideoResult(title=title, url=url, year=year, speaker=speaker))
    return results

async def _download_audio(url: str, dest: Path):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(dest),
        'quiet': True,
        'nocheckcertificate': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

async def process_video(pw, base_url: str, video: VideoResult, out_dir: Path):
    """Download audio, transcribe and summarise."""
    safe_name = re.sub(r'[^A-Za-z0-9]+', '_', video.title)[:50]
    audio_path = out_dir / f'{safe_name}.mp3'
    transcript_path = audio_path.with_suffix('.md')
    notes_path = audio_path.with_suffix('.notes.md')

    await _download_audio(video.url, audio_path)

    if not OPENAI_API_KEY:
        raise RuntimeError('OPENAI_API_KEY missing')
    openai.api_key = OPENAI_API_KEY

    with open(audio_path, 'rb') as f:
        transcript_text = openai.Audio.transcribe('whisper-1', f, response_format='text')

    transcript_path.write_text(transcript_text, encoding='utf-8')

    prompt = f"""Summarise the following CIRSE lecture titled '{video.title}'
by {video.speaker or 'unknown speaker'} into ≤15 bullet points (concise).\n\n{transcript_text}"""
    chat = openai.ChatCompletion.create(
        model='gpt-4o-mini',
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.2,
    )
    notes = chat.choices[0].message.content.strip()
    notes_path.write_text(notes, encoding='utf-8')
    return notes_path, transcript_path

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--query', required=True)
    parser.add_argument('--top', type=int, default=5)
    args = parser.parse_args()

    async def main():
        async with playwright.async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            page = await browser.new_page()
            await playwright_login(page)
            hits = await search_videos(page, args.query, args.top)
            for i, v in enumerate(hits, 1):
                print(f'[{i}] {v.title}')
            indices = input('Pick numbers: ').split()
            out = Path('cirse_notes'); out.mkdir(exist_ok=True)
            for i in indices:
                await process_video(pw, 'https://library.cirse.org', hits[int(i)-1], out)
    asyncio.run(main())
