"""Dark Video Edit engine: kill detection, reel building, YouTube section download."""
import base64, os, random, re, shutil, subprocess, sys, tempfile
import numpy as np

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_real_run = subprocess.run
def _run(args, **kw):
    kw.setdefault("stdin", subprocess.DEVNULL); kw.setdefault("creationflags", NOWIN)
    return _real_run(args, **kw)
def res(*p):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *p)

def _ffmpeg():
    p = shutil.which("ffmpeg")
    if p: return p
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()
def _normalize_ffmpeg(ff):
    """yt-dlp only recognises a program literally named ffmpeg / ffmpeg.exe, but imageio-ffmpeg ships a name like
    ffmpeg-win-x86_64-v7.1.exe (-> "ffmpeg is not installed"). So copy it to ~/.darkvideoedit/bin/ffmpeg(.exe)
    and put that folder first on PATH."""
    if os.path.basename(ff).lower() in ("ffmpeg", "ffmpeg.exe"): d = os.path.dirname(os.path.abspath(ff))
    else:
        d = os.path.join(os.path.expanduser("~"), ".darkvideoedit", "bin"); os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(ff): shutil.copy2(ff, dst)
        try: os.chmod(dst, 0o755)
        except OSError: pass
        ff = dst
    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    return ff
FF = _normalize_ffmpeg(_ffmpeg())

def run(args, **kw):
    return _run([FF, "-v", "error", "-y", *args], capture_output=True, text=True, creationflags=NOWIN, **kw)

def info(path):
    return _run([FF, "-i", path], capture_output=True, text=True, creationflags=NOWIN).stderr

def duration(path):
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info(path))
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0

def video_size(path):
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", info(path))
    return (int(m[1]), int(m[2])) if m else (1920, 1080)

HAS_TEXT = "drawtext" in _run([FF, "-hide_banner", "-filters"], capture_output=True, text=True, creationflags=NOWIN).stdout

# ---------- finding clips: many detectors, pick any combination ----------
PRI = {"KILL": 10, "BEST": 9, "MAIN": 8, "FLASH": 7, "DAMAGE": 6, "JUMP": 5, "MOTION": 4, "ACTION": 3, "SCENE": 2, "PART": 1, "CLIP": 0}
WIN = {"kill": (2.5, 1.5, "KILL"), "action": (2.0, 2.0, "ACTION"), "jump": (2.5, 2.5, "JUMP"), "motion": (2.0, 3.0, "MOTION"),
       "flash": (2.0, 2.5, "FLASH"), "damage": (2.0, 3.0, "DAMAGE"), "scene": (0.5, 6.0, "SCENE"), "best": (3.0, 4.0, "BEST")}
_CACHE = {}
def _cached(key, path, fn):
    k = (key, path, os.path.getmtime(path))
    if k not in _CACHE: _CACHE[k] = fn(path)
    return _CACHE[k]

def detect_kills(path, fps=5, thr=6, gap=3.0):
    """Red skull badge, top centre of the screen."""
    p = _run([FF, "-v", "error", "-i", path, "-vf",
        f"fps={fps},crop=iw*0.16:ih*0.14:iw*0.42:ih*0.093,scale=48:24:flags=area",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    n = len(p.stdout) // (24 * 48 * 3)
    if n < 1: return []
    a = np.frombuffer(p.stdout[:n * 24 * 48 * 3], np.uint8).reshape(n, 24, 48, 3).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = ((r > 170) & (g < 90) & (b < 100) & (r - g > 100)).sum((1, 2))
    ev, on = [], False
    for i, x in enumerate(red):
        if x >= thr and not on: on, s = True, i
        if x < thr and on: on = False; ev.append([s / fps, i / fps])
    if on: ev.append([s / fps, len(red) / fps])
    out = []
    for s, e in ev:
        if out and s - out[-1][1] < gap: out[-1][1] = e
        else: out.append([s, e])
    return out

def _audio(path):   # loudness (dB) every 0.25 s
    p = _run([FF, "-v", "error", "-i", path, "-vn", "-af",
        "aresample=22050,asetnsamples=n=5512,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
        "-f", "null", "-"], capture_output=True, text=True)
    v = []
    for l in p.stdout.splitlines():
        if "RMS_level" in l:
            x = l.split("=")[1].strip(); v.append(-90.0 if "inf" in x else float(x))
    return np.array(v, float)

def _stats(path, fps=10):   # tiny 32x18 frames: brightness, motion, red amount
    p = _run([FF, "-v", "error", "-i", path, "-vf", f"fps={fps},scale=32:18:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    n = len(p.stdout) // (32 * 18 * 3)
    if n < 3: return None
    a = np.frombuffer(p.stdout[:n * 32 * 18 * 3], np.uint8).reshape(n, 18, 32, 3).astype(np.int16)
    return dict(fps=fps, luma=(a[..., 0] * .299 + a[..., 1] * .587 + a[..., 2] * .114).mean((1, 2)),
                motion=np.r_[0, np.abs(np.diff(a, axis=0)).mean((1, 2, 3))],
                red=((a[..., 0] > 150) & (a[..., 1] < 90) & (a[..., 2] < 90)).mean((1, 2)))

def _peaks(x, rate, thr, min_gap, win=1.0):
    x = np.asarray(x, float); w = max(1, int(win * rate)); out = []
    for i in np.where(x > thr)[0]:
        if x[i] >= x[max(0, i - w):i + w + 1].max():
            t = i / rate
            if not out or t - out[-1] >= min_gap: out.append(t)
    return [[t, t] for t in out]

def audio_peaks(path, rise_db=6.0, min_gap=5.0):      # gunfire, blasts, shouting
    v = _cached("aud", path, _audio)
    return _peaks(v, 4, np.median(v) + rise_db, min_gap, 1.5) if len(v) > 8 else []

def sudden_loud(path):                                  # quiet -> suddenly loud (jump scares, funny reactions)
    v = _cached("aud", path, _audio)
    if len(v) < 12: return []
    prev = np.array([v[max(0, i - 8):i].mean() if i else v[0] for i in range(len(v))])
    return _peaks(np.where(v > np.median(v) + 3, v - prev, 0), 4, 10.0, 6.0, 1.5)

def motion_peaks(path):                                 # chaos: lots of movement on screen
    s = _cached("st", path, _stats)
    if not s: return []
    m = s["motion"]; return _peaks(m, s["fps"], max(np.percentile(m, 96), np.median(m) * 2.5), 6.0, 1.0)

def flashes(path):                                      # explosions / bright flashes
    s = _cached("st", path, _stats)
    if not s: return []
    d = np.r_[0, np.diff(s["luma"])]; return _peaks(d, s["fps"], max(16.0, float(np.percentile(d, 99.5))), 5.0, 0.5)

def damage(path):                                       # red screen (taking damage / dying)
    s = _cached("st", path, _stats)
    if not s: return []
    r = np.convolve(s["red"], np.ones(5) / 5, mode="same")
    return _peaks(r, s["fps"], max(0.02, float(np.percentile(r, 98))), 6.0, 1.5)

def scene_cuts(path):                                   # hard visual cuts
    s = _cached("st", path, _stats)
    return _peaks(s["motion"], s["fps"], 35.0, 6.0, 0.5) if s else []

def best_moments(path, dur):                            # AI score = loudness + motion + kills, top moments only
    v = _cached("aud", path, _audio); s = _cached("st", path, _stats)
    if len(v) < 12: return []
    z = lambda x: (x - x.mean()) / (x.std() + 1e-6)
    t = np.arange(len(v)) / 4.0; sc = z(v)
    if s: sc = sc + z(np.interp(t, np.arange(len(s["motion"])) / s["fps"], s["motion"]))
    sc = np.convolve(sc, np.ones(12) / 12, mode="same")
    for k, _ in _cached("kill", path, detect_kills): sc[max(0, int(k * 4) - 6):int(k * 4) + 7] += 1.5
    picked = []
    for i in np.argsort(sc)[::-1]:
        if all(abs(i / 4.0 - q) >= 8 for q in picked): picked.append(i / 4.0)
        if len(picked) >= max(3, int(dur / 20)): break
    return [[q, q] for q in sorted(picked)]

def main_clips(path, dur, min_len=8.0, max_len=40.0):
    """Main clips: the long stretches where most is happening (loud + moving), not single peaks."""
    v = _cached("aud", path, _audio); st = _cached("st", path, _stats)
    if len(v) < 16: return []
    z = lambda x: (x - x.mean()) / (x.std() + 1e-6); t = np.arange(len(v)) / 4.0; sc = z(v)
    if st: sc = sc + z(np.interp(t, np.arange(len(st["motion"])) / st["fps"], st["motion"]))
    sc = np.convolve(sc, np.ones(20) / 20, mode="same")
    on = sc > np.percentile(sc, 60); runs, i = [], 0
    while i < len(on):
        if on[i]:
            j = i
            while j < len(on) and on[j]: j += 1
            runs.append([i / 4.0, j / 4.0]); i = j
        else: i += 1
    merged = []
    for a, b in runs:
        if merged and a - merged[-1][1] <= 3.0: merged[-1][1] = b
        else: merged.append([a, b])
    out = []
    for a, b in merged:
        if b - a < min_len: continue
        if b - a > max_len:   # keep the strongest max_len seconds of a very long stretch
            w = int(max_len * 4); k = int(np.argmax(np.convolve(sc[int(a * 4):int(b * 4)], np.ones(w) / w, mode="valid"))); a = a + k / 4.0; b = a + max_len
        out.append((max(0.0, a - 1.0), min(dur - 0.1, b + 1.0)))
    return out

def scene_segments(path, dur, min_len=3.0, max_len=25.0):
    """Cut-scene clips: the stretch between one hard cut and the next."""
    st = _cached("st", path, _stats)
    if not st: return []
    m = st["motion"]; cuts = [0.0] + [t for t, _ in _peaks(m, st["fps"], max(30.0, float(np.percentile(m, 97))), 2.0, 0.5)] + [dur]
    return [(a, min(b - 0.1, a + max_len)) for a, b in zip(cuts[:-1], cuts[1:]) if b - a >= min_len]

def thumb(path, t):
    p = _run([FF, "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-vf", "scale=160:-1",
              "-f", "mjpeg", "-"], capture_output=True)
    return "data:image/jpeg;base64," + base64.b64encode(p.stdout).decode() if p.stdout else ""

def finalize(path, shots, merge=True, max_len=14.0):
    """Sort, merge overlapping windows (never longer than max_len), count kills, add thumbnails."""
    merged = []
    for s in sorted(shots, key=lambda x: x["start"]):
        host = next((m for m in reversed(merged) if merge and s["start"] >= m["start"] - 0.01 and s["end"] <= m["end"] + 0.01), None)
        if host:   # window lies completely inside an earlier shot: add its kills/tag to that shot
            host["hits"] = sorted(set(host["hits"] + s["hits"]))
            if PRI[s["tag"]] > PRI[host["tag"]]: host["tag"] = s["tag"]
            continue
        if merge and merged and ((s["start"] <= merged[-1]["end"] + 0.3 and max(merged[-1]["end"], s["end"]) - merged[-1]["start"] <= max_len) or s["end"] <= merged[-1]["end"]):
            m = merged[-1]; m["end"] = max(m["end"], s["end"]); m["hits"] = sorted(set(m["hits"] + s["hits"]))
            if PRI[s["tag"]] > PRI[m["tag"]]: m["tag"] = s["tag"]
        else:
            s = dict(s)
            if merge and merged and s["start"] < merged[-1]["end"]:   # no overlapping footage between shots
                s["start"] = min(merged[-1]["end"], (min(s["hits"]) - 0.5) if s["hits"] else merged[-1]["end"])
            merged.append(s)
    for m in merged:
        m["k"] = len(m["hits"]); m["t"] = thumb(path, m["hits"][0] + 0.1 if m["hits"] else (m["start"] + m["end"]) / 2)
    return merged

def build_shots(path, modes="kill,action", dur=None, split_len=8, cb=lambda t: None):
    """modes (list or 'a,b,c'): kill action main best scene jump motion flash damage | split (every split_len s) | whole (entire clip)"""
    if isinstance(modes, str): modes = [m for m in modes.split(",") if m]
    if "all" in modes: modes = ["kill", "action"]
    dur = dur or duration(path)
    if "whole" in modes: return finalize(path, [dict(path=path, start=0.0, end=dur, hits=[], tag="CLIP")], merge=False)
    if "split" in modes:
        L = float(split_len or 8)
        return finalize(path, [dict(path=path, start=float(a), end=min(dur, a + L), hits=[], tag="PART")
                               for a in np.arange(0, dur, L) if min(dur, a + L) - a > 1], merge=False)
    names = {"kill": "kills", "action": "loud action", "main": "main clips", "best": "best clips", "scene": "cut-scene clips",
             "jump": "sudden loud moments", "motion": "high motion", "flash": "explosions / flashes", "damage": "damage"}
    peaks = {"kill": lambda: _cached("kill", path, detect_kills), "action": lambda: audio_peaks(path), "best": lambda: best_moments(path, dur),
             "jump": lambda: sudden_loud(path), "motion": lambda: motion_peaks(path), "flash": lambda: flashes(path), "damage": lambda: damage(path)}
    ranges = {"main": (lambda: main_clips(path, dur), "MAIN"), "scene": (lambda: scene_segments(path, dur), "SCENE")}
    sh = []
    for kind in [m for m in names if m in modes]:
        cb(f"Finding {names[kind]}…")
        if kind in ranges:
            fn, tag = ranges[kind]
            sh += [dict(path=path, start=a, end=b, hits=[], tag=tag) for a, b in fn() if b - a > 0.5]
            continue
        before, after, tag = WIN[kind]
        for st_, e in peaks[kind]():
            if kind == "kill": a, b, hits = max(0, st_ - before), min(dur - 0.1, max(e + after, st_ + 2.0)), [st_]
            else: a, b, hits = max(0, st_ - before), min(dur - 0.1, st_ + after), []
            if b - a > 0.5: sh.append(dict(path=path, start=a, end=b, hits=hits, tag=tag))
    return finalize(path, sh)

# ---------- reel builder ----------
def _ff_path(p): return p.replace("\\", "/").replace(":", "\\:")
def _txt(s): return re.sub(r"[:'%\\]", "", s)
MUSIC = {1: "phonk.mp3", 2: "bass.mp3", 3: "lofi.mp3"}   # drop royalty-free files into app/assets/music/

def build_reel(shots, out, opt, progress=lambda p, t: None):
    """shots: [{path,start,end,hits,cap,sp,fx{shake,flash,zoom,slow,neon,vig,glitch,boom,counter},au{gv,mu,mv,ms},voice}]"""
    tmp = tempfile.mkdtemp(prefix="dve_"); boom = os.path.join(tmp, "boom.wav")
    run(["-f", "lavfi", "-i", "aevalsrc='(sin(2*PI*55*t)*exp(-5*t)*1.1+sin(2*PI*1800*t)*exp(-40*t)*0.3)':d=0.9:s=44100", "-ac", "2", boom])
    F = _ff_path(res("assets", "Poppins-Bold.ttf")); n, files = 0, []
    for i, s in enumerate(shots):
        progress(int(100 * i / len(shots)), f"Building shot {i + 1}/{len(shots)}…")
        fx, au = s.get("fx") or {}, s.get("au") or {}
        sp = float(s.get("sp") or 1)
        if fx.get("slow") and sp == 1: sp = 0.5
        sp = min(2.0, max(0.5, sp))
        D = s["end"] - s["start"]; Do = D / sp
        hits = [(h - s["start"]) / sp for h in s.get("hits", []) if s["start"] <= h <= s["end"]]; k = len(hits)
        gv = 0.0 if au.get("mu") else au.get("gv", 80) / 100.0
        shake = "+".join(f"between(t,{h:.2f},{h + .4:.2f})" for h in hits) if fx.get("shake") and hits else ""
        flash = "+".join(f"between(t,{h:.2f},{h + .08:.2f})" for h in hits) if fx.get("flash") and hits else ""
        Z = 1360 if fx.get("zoom") else 1220; base = (Z - 1080) // 2
        dx = f"'{base}+if(gt({shake},0),sin(t*90)*35,0)'" if shake else str(base)
        dy = f"'{base}+if(gt({shake},0),cos(t*80)*35,0)'" if shake else str(base)
        parts = []
        if HAS_TEXT and s.get("cap"):
            parts.append(f"drawtext=fontfile='{F}':text='{_txt(s['cap'])}':fontsize=60:fontcolor=white:borderw=5:bordercolor=black:x=(w-text_w)/2:y=230:enable='between(t,0.2,{Do:.2f})'")
        if HAS_TEXT and fx.get("counter") and hits:
            for h in hits:
                n += 1
                parts.append(f"drawtext=fontfile='{F}':text='KILL {n}':fontsize=130:fontcolor=#ff2a2a:borderw=8:bordercolor=white:x='(w-text_w)/2+if(lt(t,{h + .5:.2f}),sin(t*100)*14,0)':y=1560:enable='between(t,{h:.2f},{h + 1.4:.2f})'")
        else: n += k
        if fx.get("glitch"): parts += ["hue=h='sin(t*50)*70'", "noise=alls=10:allf=t"]
        eq = ["contrast=1.18", "saturation=1.8"] if fx.get("neon") else []
        if flash: eq += [f"brightness='if(gt({flash},0),0.55,0)'", "eval=frame"]
        if eq: parts.append("eq=" + ":".join(eq))
        if fx.get("vig"): parts.append("vignette=PI/5")
        parts += ["fade=t=in:d=0.1", "setsar=1", "format=yuv420p"]
        vf = (f"[0:v]setpts=PTS/{sp:.3f},split[a][b];[a]scale=108:192:force_original_aspect_ratio=increase,crop=108:192,boxblur=5:2,eq=brightness=-0.2,scale=1080:1920:flags=bilinear[bg];"
              f"[b]scale=-2:1080,crop=1080:1080,scale={Z}:{Z},crop=1080:1080:{dx}:{dy}[fg];[bg][fg]overlay=0:420," + ",".join(parts) + "[v]")
        # ---- audio ----
        has_a = "Audio:" in info(s["path"])
        tempo = f",atempo={sp:.3f}" if sp != 1 else ""
        chains = [(f"[0:a]atrim=0:{D:.2f},asetpts=PTS-STARTPTS{tempo},volume={gv * 0.9:.2f}[ga]" if has_a else f"anullsrc=r=44100:cl=stereo,atrim=0:{Do:.2f}[ga]")]
        labels = ["[ga]"]; extra = []; idx = 2
        if fx.get("boom") and hits:
            if k == 1: chains.append(f"[1:a]adelay={int(hits[0] * 1000)}|{int(hits[0] * 1000)}[bd0]")
            else:
                chains.append(f"[1:a]asplit={k}" + "".join(f"[bs{j}]" for j in range(k)))
                chains += [f"[bs{j}]adelay={int(h * 1000)}|{int(h * 1000)}[bd{j}]" for j, h in enumerate(hits)]
            labels += [f"[bd{j}]" for j in range(k)]
        if s.get("voice") and os.path.exists(s["voice"]):
            extra += ["-i", s["voice"]]; chains.append(f"[{idx}:a]atrim=0:{Do:.2f},asetpts=PTS-STARTPTS,volume=1.4[vo]"); labels.append("[vo]"); idx += 1
        mp = res("assets", "music", MUSIC.get(int(au.get("ms", 0)), "none"))
        if os.path.exists(mp):
            extra += ["-stream_loop", "-1", "-i", mp]; chains.append(f"[{idx}:a]atrim=0:{Do:.2f},asetpts=PTS-STARTPTS,volume={au.get('mv', 40) / 100 * 0.6:.2f}[mu]"); labels.append("[mu]"); idx += 1
        chains.append("[ga]anull[aout]" if len(labels) == 1 else "".join(labels) + f"amix=inputs={len(labels)}:normalize=0,alimiter=limit=0.95[aout]")
        o = os.path.join(tmp, f"s{i:03d}.mp4"); files.append(o)
        r = run(["-ss", f"{s['start']:.2f}", "-t", f"{D:.2f}", "-i", s["path"], "-i", boom, *extra, "-filter_complex", vf + ";" + ";".join(chains),
                 "-map", "[v]", "-map", "[aout]", "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                 "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-t", f"{Do:.2f}", o])
        if r.returncode: raise RuntimeError(r.stderr[-400:])
    lst = os.path.join(tmp, "list.txt")
    open(lst, "w").write("".join("file '" + f.replace("\\", "/") + "'\n" for f in files))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out])
    shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode: raise RuntimeError(r.stderr[-400:])
    progress(100, "Reel ready"); return out

# ---------- crop ----------
RATIOS = {"9:16": (9, 16, 1080, 1920), "1:1": (1, 1, 1080, 1080), "4:5": (4, 5, 1080, 1350), "16:9": (16, 9, 1920, 1080)}
def crop_video(src, dst, r, z=1.0, cx=.5, cy=.5):
    W, H = video_size(src)
    if r in RATIOS:
        rw, rh, ow, oh = RATIOS[r]; ar = rw / rh; w, h = (W, W / ar) if ar >= W / H else (H * ar, H)
    else: w, h, ow, oh = W, H, 0, 0
    w, h = w * z, h * z; x, y = max(0, min(W - w, cx * W - w / 2)), max(0, min(H - h, cy * H - h / 2))
    w, h, x, y = [int(v) // 2 * 2 for v in (w, h, x, y)]
    vf = f"crop={w}:{h}:{x}:{y}" + (f",scale={ow}:{oh}" if ow else "")
    rr = run(["-i", src, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy", dst])
    if rr.returncode: raise RuntimeError(rr.stderr[-400:])
    return dst

# ---------- YouTube (only the chosen part is downloaded) ----------
# YouTube now needs a JavaScript runtime (Deno) for yt-dlp. The Windows build bundles deno.exe in app/bin.
_BIN = res("bin")
if os.path.isdir(_BIN): os.environ["PATH"] = _BIN + os.pathsep + os.environ.get("PATH", "")

def _hint(msg):
    m = msg.lower()
    if "javascript" in m or "403" in m or "n challenge" in m or "signature" in m or "requested format" in m:
        return " | HINT: YouTube needs a JavaScript runtime. Install Deno (winget install DenoLand.Deno) or use the .exe build, and update yt-dlp: pip install -U \"yt-dlp[default]\""
    if "sign in" in m or "confirm you" in m or "age" in m or "private" in m:
        return " | HINT: this video needs a login. Use Upload tab > YouTube > Connect (browser login)."
    if "cookie" in m: return " | HINT: close the browser or try Firefox/Edge. Chrome often locks its cookie file."
    if "ffmpeg" in m: return " | HINT: FFmpeg was not found. Update to the latest version of the app, or install FFmpeg and add it to PATH."
    return ""

def _clean(e): return re.sub(r"\x1b\[[0-9;]*m", "", str(e)).strip()

class _Log:
    def __init__(self): self.lines = []
    def debug(self, m): pass
    def info(self, m): pass
    def warning(self, m): self.lines.append(_clean(m))
    def error(self, m): self.lines.append(_clean(m))

def yt_info(url, browser=None):
    from yt_dlp import YoutubeDL
    o = {"quiet": True, "noplaylist": True, "skip_download": True, "logger": _Log()}
    if browser: o["cookiesfrombrowser"] = (browser,)
    try:
        with YoutubeDL(o) as y: i = y.extract_info(url, download=False)
    except Exception as e:
        raise RuntimeError(_clean(e)[-300:] + _hint(str(e)))
    return {"title": i.get("title", ""), "dur": i.get("duration") or 0, "live": bool(i.get("is_live")),
            "heat": i.get("heatmap") or [], "chapters": i.get("chapters") or []}

def yt_download(url, start, end, outdir, browser=None, crop=None, progress=lambda p, t: None, max_h=1080):
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import download_range_func
    os.makedirs(outdir, exist_ok=True)
    def hook(d):
        if d["status"] == "downloading":
            tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
            progress(min(99, int(100 * d.get("downloaded_bytes", 0) / tot)), "Downloading selected part…")
    last = None
    for fmt in (f"bv*[height<={max_h}]+ba/b[height<={max_h}]", "bv*+ba/b" if max_h > 360 else "worst", "b"):   # try simpler formats if the first fails
        log = _Log()
        o = {"quiet": True, "noplaylist": True, "logger": log, "download_ranges": download_range_func(None, [(float(start), float(end))]),
             "force_keyframes_at_cuts": True, "format": fmt, "merge_output_format": "mp4", "retries": 5, "fragment_retries": 5,
             "outtmpl": os.path.join(outdir, f"%(title).50s_%(id)s_{int(start)}-{int(end)}.%(ext)s"),
             "ffmpeg_location": os.path.dirname(FF), "progress_hooks": [hook]}
        if browser: o["cookiesfrombrowser"] = (browser,)
        try:
            with YoutubeDL(o) as y:
                i = y.extract_info(url, download=True)
                rd = (i.get("requested_downloads") or [{}])[0]; path = rd.get("filepath") or y.prepare_filename(i)
            if not os.path.exists(path):   # extension may differ after merging
                c = sorted((os.path.join(outdir, f) for f in os.listdir(outdir) if f"_{i.get('id')}_{int(start)}-{int(end)}" in f), key=os.path.getmtime)
                path = c[-1] if c else path
            break
        except Exception as e:
            last = _clean(e) + ((" | " + " ".join(log.lines[-2:])) if log.lines else "")
    else:
        raise RuntimeError(last[-400:] + _hint(last))
    if crop:
        dst = path.rsplit(".", 1)[0] + "_" + crop["r"].replace(":", "x") + ".mp4"
        path = crop_video(path, dst, crop["r"], crop.get("z", 1), crop.get("x", .5), crop.get("y", .5))
    return path

def heat_clips(heat, dur):
    """YouTube 'Most replayed' graph -> the moments viewers replay most (no video download needed)."""
    if not heat: return []
    n, picked = max(3, min(10, int(dur / 120))), []
    for h in sorted(heat, key=lambda x: -x.get("value", 0)):
        c = (h["start_time"] + h["end_time"]) / 2
        if h.get("value", 0) >= 0.45 and all(abs(c - q) >= 25 for q in picked): picked.append(c)
        if len(picked) >= n: break
    return [dict(start=max(0.0, c - 8), end=min(float(dur), c + 12), tag="TOP", hits=[], k=0, cap="") for c in sorted(picked)]

def chapter_clips(chapters):
    return [dict(start=float(c["start_time"]), end=min(float(c["end_time"]), float(c["start_time"]) + 90), tag="CHAPTER", hits=[], k=0, cap=c.get("title", ""))
            for c in chapters or [] if c.get("end_time", 0) - c.get("start_time", 0) > 2]

def yt_candidates(url, modes, start=0, end=0, split_len=8, browser=None, progress=lambda p, t: None):
    """Auto-find clips in a YouTube video. 'heat' and 'chapters' use YouTube's own data (no download).
    Other modes download a small temporary 360p copy of the chosen range, analyse it, then delete it."""
    if isinstance(modes, str): modes = [m for m in modes.split(",") if m]
    info = yt_info(url, browser); dur = info["dur"] or 0; out = []
    if "heat" in modes:
        out += heat_clips(info["heat"], dur)
        if not info["heat"]: progress(-1, "No 'Most replayed' data for this video")
    if "chapters" in modes: out += chapter_clips(info["chapters"])
    deep = [m for m in modes if m not in ("heat", "chapters")]
    if deep:
        a = float(start or 0); b = float(end or dur)
        if b - a > 45 * 60: raise RuntimeError("Range is longer than 45 minutes. Choose a shorter range with the slider.")
        tmp = tempfile.mkdtemp(prefix="dve_an_")
        try:
            progress(1, "Downloading a small temporary copy to analyse…")
            path = yt_download(url, a, b, tmp, browser, None, progress, max_h=360)
            for s in build_shots(path, deep, duration(path), split_len, cb=lambda t: progress(-1, t)):
                out.append(dict(start=s["start"] + a, end=s["end"] + a, tag=s["tag"], hits=[h + a for h in s["hits"]], k=s["k"], t=s["t"], cap=""))
        finally: shutil.rmtree(tmp, ignore_errors=True)
    return sorted(out, key=lambda x: x["start"]), info

# ---------- title / description ----------
TITLES = ["{n} KILLS in ek match - dushman ro pada", "Bhai ne lobby khaali kar di - {n} KILLS", "Ek ek karke sab gaye - {n} KILLS", "Paaji ka aim dekho - {n} KILLS GG"]
def make_title(n):
    return {"title": random.choice(TITLES).format(n=n), "desc": "Dark Video Edit se bani reel. Like aur follow karo!\n#gaming #reels #shorts #gamingreels #kills"}
