"""Generate four Russian audio tracks for the Poekhali board.
This uses an unofficial client for Edge Read Aloud. Commercial rights are not confirmed.
"""
import asyncio
import re
from pathlib import Path
import edge_tts

HERE = Path(__file__).resolve().parent

async def main():
    html = (HERE / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"\{title:'[^']*',text:'(.*?)',seconds:\d+\}", html)
    if len(scripts) != 4:
        raise RuntimeError(f"Expected 4 scripts, found {len(scripts)}")
    out = HERE / "audio"
    out.mkdir(exist_ok=True)
    for idx, script in enumerate(scripts, start=1):
        filename = out / f"{idx:02}.mp3"
        print("Creating", filename.name, flush=True)
        for attempt in range(3):
            try:
                voice = edge_tts.Communicate(
                    script, voice="ru-RU-SvetlanaNeural",
                    rate="-11%", pitch="-2Hz", volume="+0%"
                )
                await voice.save(str(filename))
                if filename.stat().st_size < 1000:
                    raise RuntimeError("Audio file too small")
                break
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(3 * (attempt + 1))
        print("Saved", filename.name, filename.stat().st_size, flush=True)

if __name__ == "__main__":
    asyncio.run(main())
