# Changelog

## 2.04
- **Fix: YouTube download "ffmpeg is not installed".** The app now gives yt-dlp an FFmpeg named exactly `ffmpeg(.exe)` (copied to `~/.darkvideoedit/bin`) and puts it on PATH.
- "Find clips in this video" loads the video by itself if you forgot to press Load; errors and "no clips found" now show right under the button.

## 2.03
- App version is shown in the header and window title.
- New clip types in Find clips: **Main clips**, **Cut-scene clips** (between hard cuts); "Best clips" (AI score).
- **YouTube tab: Auto clips.** Most replayed moments + Chapters (no download), deep analysis on a temporary 360p copy (kills, main, best, cut-scene, action, funny, motion, flashes), download only the selected clips.
- **Auto captions ON/OFF** switch (Edit tab + Captions tab). Chapter titles become captions for chapter clips.
- Fix: kills inside long clips are now kept with the right clip.

## 2.02
- Many clip-finding types (action, funny/sudden loud, motion, flashes, damage, scenes, split, whole).
- Crash hardening: log files in `~/.darkvideoedit`, debug build option, safer pywebview API, YouTube login picker, Deno bundled for YouTube downloads.
