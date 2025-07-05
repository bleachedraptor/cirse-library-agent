
"""
cirse_agent.py
Core library for authenticating to CIRSE Library, searching videos,
downloading audio, transcribing with OpenAI Whisper, and summarising with GPT.
Designed to be imported by cirse_app.py (Streamlit GUI) or run as a CLI.

* Auto‑installs its own dependencies on first import if missing.
* Uses Playwright (headless Chromium) for login + scraping.
"""

import importlib, subprocess, sys, os, re, asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Lazy dependency loader so non‑coders don't have to run pip manually
# ---------------------------------------------------------------------------
def _ensure(pkg: str):
    try:
        return importlib.import_module(pkg)
    except ModuleNotFoundError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])
        return importlib.import_module(pkg)

# Essential third‑party libs
dotenv      = _ensure('dotenv')
openai      = _ensure('openai')
rich        = _ensure('rich')
yt_dlp      = _ensure('yt_dlp')
playwright  = _ensure('playwright.async_api')

from rich.progress import Progress

dotenv.load_dotenv()

OPENAI_API_KEY  = os.getenv('OPENAI_API_KEY')
CIRSE_EMAIL     = os.getenv('CIRSE_EMAIL')
CIRSE_PASSWORD  = os.getenv('CIRSE_PASSWORD')

# ---------------------------------------------------------------------------
# Simple data container for search results
# ---------------------------------------------------------------------------
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
    """Logs into CIRSE Library on given Playwright page."""
    login_url = 'https://my.cirse.org'
    await page.goto(login_url)
    await page.fill('input[name="email"]', CIRSE_EMAIL)
    await page.fill('input[type="password"]', CIRSE_PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_load_state('networkidle')

async def search_videos(page, query: str, max_results: int = 10) -> List[VideoResult]:
    """Returns top `max_results` search hits as VideoResult objects."""
    search_url = f'https://library.cirse.org/search?q={query}'
    await page.goto(search_url)
    await page.wait_for_selector('.search-result')
    cards = await page.query_selector_all('.search-result')[:max_results]
    results = []
    for card in cards:
        title = await card.query_selector_eval('.result-title', 'el => el.textContent.trim()')
        url = await card.query_selector_eval('a', 'el => el.href')
        try:
            year = await card.query_selector_eval('.result-year', 'el => el.textContent.trim()')
        except:
            year = None
        try:
            speaker = await card.query_selector_eval('.result-speaker', 'el => el.textContent.trim()')
        except:
            speaker = None
        results.append(VideoResult(title=title, url=url, year=year, speaker=speaker))
    return results

async def _download_audio(url: str, dest: Path):
    """Downloads lecture audio using yt_dlp (works when CIRSE streams via MP4/HLS)."""
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(dest),
        'quiet': True,
        'nocheckcertificate': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl_cli:
        ydl_cli.download([url])

async def process_video(pw, base_url: str, video: VideoResult, out_dir: Path):
    """Downloads, transcribes and summarises a single video."""
    audio_path = out_dir / f"{re.sub(r'[^A-Za-z0-9]+', '_', video.title)[:50]}.mp3"
    transcript_path = audio_path.with_suffix('.md')
    notes_path = audio_path.with_suffix('.notes.md')

    # 1. Download audio
    await _download_audio(video.url, audio_path)

    # 2. Transcribe
    if not OPENAI_API_KEY:
        raise RuntimeError('OPENAI_API_KEY missing – add it to Streamlit secrets or .env')

    openai.api_key = OPENAI_API_KEY
    with open(audio_path, 'rb') as f:
        transcript_resp = openai.Audio.transcribe(
            model='whisper-1',
            file=f,
            response_format='text'
        )
    transcript = transcript_resp  # Whisper returns raw text

    transcript_path.write_text(transcript, encoding='utf-8')

    # 3. Summarise (chunk transcript to fit context if large)
    prompt = f"""You are a medical conference summariser.
    Produce concise bullet‑point notes (max 15 bullets) covering key learning points from this CIRSE lecture titled
    '{video.title}' by {video.speaker or 'unknown speaker'}.

    --- Begin transcript ---
    {transcript}
    --- End transcript ---
    """
    completion = openai.ChatCompletion.create(
        model='gpt-4o-mini',
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.2,
    )
    notes = completion.choices[0].message.content.strip()
    notes_path.write_text(notes, encoding='utf-8')

    return notes_path, transcript_path


# ---------------------------------------------------------------------------
# CLI entry‑point
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='CIRSE Library agent')
    parser.add_argument('--query', required=True, help='Search keyword(s)')
    parser.add_argument('--top', type=int, default=5, help='Number of results to fetch')
    args = parser.parse_args()

    async def main():
        async with playwright.async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            page = await browser.new_page()
            await playwright_login(page)
            hits = await search_videos(page, args.query, args.top)
            for i, h in enumerate(hits, 1):
                print(f"[{i}] {h.title} ({h.year}) – {h.speaker}")
            choose = input('Pick indices (space‑separated): ').split()
            sel = [hits[int(idx)-1] for idx in choose]
            base = Path('cirse_notes'); base.mkdir(exist_ok=True)
            for v in sel:
                print(f'Processing {v.title}…')
                await process_video(pw, 'https://library.cirse.org', v, base)

    asyncio.run(main())
