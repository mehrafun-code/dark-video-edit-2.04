# Dark Video Edit 2.04

AI reel studio for gamers. Finds every kill in your gameplay, lets you edit each shot (trim, split, speed, effects, audio, captions) with a live 9:16 preview, exports a reel, and can download **only a chosen part** of a YouTube video (with crop).

## Features (this version)
- **Edit tab:** big 9:16 preview that plays your real clip, full-screen 9:16, video-edit toolbar (split, trim start/end, move, remove, speed 0.5x-2x), shot timeline
- **Per-shot effects:** shake, flash, zoom, slow-mo, neon grade, vignette, glitch, boom sound, KILL counter (live preview + exported)
- **Per-shot audio:** game volume, mute, boom sound, voiceover recording (mic), music (drop files in `app/assets/music/`)
- **Captions tab:** funny Hinglish captions per shot, edit any caption, show/hide
- **Find clips (tick any combination):** Kills, Loud action, **Main clips**, **Best clips (AI score)**, **Cut-scene clips**, Sudden loud / funny reactions, High motion / chaos, Explosions / flashes, Damage / red screen, Auto-split every N seconds, or Whole clips to cut yourself.
- **YouTube auto clips:** *Most replayed* moments and *Chapters* (YouTube data, no download), plus deep analysis (kills, main, best, cut-scene, action...) on a small temporary 360p copy of the range you choose. Then download **only the selected clips**.
- **Auto captions ON/OFF:** one switch (Edit tab and Captions tab) adds a caption to every clip automatically, or removes them. Plus **＋ Add shot here**, Split and Trim for fully manual shots
- **YouTube tab:** paste link, watch in app, Mark In/Out or slider or typed time, crop (9:16 / 1:1 / 4:5 / 16:9 / free), download only that part; browser-login for age-restricted videos
- **Upload tab:** title/description generator (templates). Account connect for YouTube = browser login. YouTube/Instagram upload buttons are the next phase.

## Not finished yet (honest list)
- YouTube and Instagram **upload** (needs Google API approval and a Meta Business/Creator app)
- Crop of an edited shot (crop works for YouTube downloads)
- Effects tab and Audio tab are defaults for new scans only; Edit tab is where per-shot settings live
- Music tracks: add `phonk.mp3`, `bass.mp3`, `lofi.mp3` to `app/assets/music/` (royalty-free)
- Zoom punch is exported as a gentle constant zoom; glitch is a colour wobble + noise
- Kill detection is tuned to the game UI in the sample clips; other games need their own region (see `detect_kills` in `app/engine.py`)

## Run from source
```
pip install -r requirements.txt
python app/main.py
```
**YouTube downloads need Deno** (yt-dlp now requires a JavaScript runtime for YouTube): `winget install DenoLand.Deno`. The Windows .exe from GitHub Actions already bundles it. If a download fails, the exact error appears under the Download button. Keep yt-dlp updated: `pip install -U "yt-dlp[default]"`.
FFmpeg is taken from PATH, or from the bundled `imageio-ffmpeg` binary.

## Headless test (no window)
```
python cli.py scan clip.mp4 [kill|action|scene|all|split|whole]
python cli.py reel out.mp4 clip1.mp4 clip2.mp4
python cli.py crop in.mp4 out.mp4 9:16
```

## Build the Windows app (.exe)
Push to GitHub. `.github/workflows/build.yml` builds it. Open **Actions**, pick the run, download **DarkVideoEdit-windows**.

## Put it on GitHub
```
git init && git add . && git commit -m "Dark Video Edit"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/dark-video-edit.git
git push -u origin main
```

## Project layout
```
app/main.py      window + bridge (Api class) + local media server for the preview
app/engine.py    kill detection, reel builder, crop, YouTube section download
app/ui/index.html  the whole interface (HTML/CSS/JS)
app/assets/      logo, icon, font, music/
cli.py           headless tests
```

## Notes
- Use only your own videos/streams or ones you have permission to use. For cookie login, a secondary Google account is safer.
- Output goes to `~/Videos/DarkVideoEdit`.

## If the app crashes
1. Press **Open log folder** in the app, or open `C:\Users\<you>\.darkvideoedit\`. Send `app.log`, `native.log` and `error.log` (if present).
2. In GitHub: Actions > Build Windows app > **Run workflow** > tick **debug**. Download `DarkVideoEdit-debug`; it opens a console window that prints the error.

## Versions
Current version: **2.04** (see `CHANGELOG.md`). When updating, bump the number in: `app/main.py` (VERSION), `app/ui/index.html` (title + header), `VERSION.txt`, `.github/workflows/build.yml`, `README.md`, `CHANGELOG.md`. The app shows its version in the header and window title, so you can always tell which build is running.
