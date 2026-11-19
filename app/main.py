"""Dark Video Edit 2.04 - desktop app entry point.
A pywebview window shows the UI (app/ui/index.html); this file is the bridge to the Python/FFmpeg engine.
Run:  python app/main.py      Logs: ~/.darkvideoedit/app.log  (and native.log for hard crashes)
"""
import base64, faulthandler, hashlib, http.server, json, logging, mimetypes, os, socketserver, sys, tempfile, threading, time, traceback
if sys.stdout is None: sys.stdout = open(os.devnull, "w")     # windowed .exe has no console
if sys.stderr is None: sys.stderr = open(os.devnull, "w")
LOGDIR = os.path.join(os.path.expanduser("~"), ".darkvideoedit"); os.makedirs(LOGDIR, exist_ok=True)
logging.basicConfig(filename=os.path.join(LOGDIR, "app.log"), level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dve")
_native = open(os.path.join(LOGDIR, "native.log"), "w"); faulthandler.enable(_native)   # records hard crashes
sys.excepthook = lambda t, v, tb: log.error("UNCAUGHT\n" + "".join(traceback.format_exception(t, v, tb)))
threading.excepthook = lambda a: log.error("THREAD CRASH\n" + "".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))
try:
    import webview
    import engine as E
except Exception:
    log.error("IMPORT FAILED\n" + traceback.format_exc()); open(os.path.join(LOGDIR, "error.log"), "w").write(traceback.format_exc()); raise

VERSION = "2.04"   # bump this (and the version in README / CHANGELOG / build.yml) with every update
OUT = os.path.join(os.path.expanduser("~"), "Videos", "DarkVideoEdit")
FILES = {}   # token -> local file path (served to the preview <video> with Range support)


class MediaHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        p = FILES.get(self.path.lstrip("/").split("?")[0])
        if not p or not os.path.exists(p): return self.send_error(404)
        size = os.path.getsize(p); start, end = 0, size - 1; rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            a, b = rng[6:].split("-"); start = int(a) if a else 0; end = int(b) if b else size - 1
            end = min(end, size - 1); self.send_response(206); self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else: self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(p)[0] or "video/mp4")
        self.send_header("Accept-Ranges", "bytes"); self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers()
        try:
            with open(p, "rb") as f:
                f.seek(start); left = end - start + 1
                while left > 0:
                    d = f.read(min(1 << 20, left))
                    if not d: break
                    self.wfile.write(d); left -= len(d)
        except (BrokenPipeError, ConnectionResetError, OSError): pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer): daemon_threads = True
SRV = Server(("127.0.0.1", 0), MediaHandler)
threading.Thread(target=SRV.serve_forever, daemon=True).start()

def media_url(path):
    key = hashlib.md5(path.encode()).hexdigest() + os.path.splitext(path)[1]
    FILES[key] = path
    return f"http://127.0.0.1:{SRV.server_address[1]}/{key}"


class Api:
    """Public methods are callable from the UI as pywebview.api.<name>(...).
    NOTE: every attribute starts with '_' on purpose; pywebview walks public attributes and a stored window object can crash it."""
    def __init__(self): self._win = None; self._browser = None; self._last = 0.0

    # ---- helpers (private) ----
    def _emit(self, ev, data):
        if ev == "progress":   # don't flood the UI (a flood of evaluate_js calls can freeze the window)
            now = time.time()
            if data.get("p", 0) < 100 and now - self._last < 0.25: return
            self._last = now
        try: self._win.evaluate_js(f"window.onEvent({json.dumps(ev)},{json.dumps(data)})")
        except Exception: log.exception("emit failed")
    def _bg(self, name, fn, *a):
        def w():
            try: log.info("start %s", name); fn(*a); log.info("done %s", name)
            except Exception as e:
                log.exception("%s failed", name); self._emit("error", {"msg": str(e)[-300:]})
        threading.Thread(target=w, daemon=True).start()

    # ---- clips ----
    def pick_files(self):
        try:
            kind = webview.FileDialog.OPEN if hasattr(webview, "FileDialog") else webview.OPEN_DIALOG
            r = self._win.create_file_dialog(kind, allow_multiple=True, file_types=("Video files (*.mp4;*.mov;*.mkv;*.webm)",))
            return [{"path": p, "name": os.path.basename(p), "dur": E.duration(p), "url": media_url(p)} for p in (r or [])]
        except Exception as e:
            log.exception("pick_files failed"); self._emit("error", {"msg": str(e)[-300:]}); return []

    def scan(self, paths, modes="kill,action", split_len=8): self._bg("scan", self._scan, paths, modes, split_len)
    def _scan(self, paths, modes, split_len):
        shots = []
        for i, p in enumerate(paths):
            base = os.path.basename(p)
            ss = E.build_shots(p, modes, E.duration(p), split_len,
                               lambda t, i=i, base=base: self._emit("progress", {"p": int(100 * i / len(paths)), "t": f"{base}: {t}"}))
            for s in ss: s["url"] = media_url(p)
            shots += ss
        self._emit("scan_done", {"shots": shots, "kills": sum(s["k"] for s in shots)})

    # ---- reel ----
    def export(self, shots, opt): self._bg("export", self._export, shots, opt or {})
    def _export(self, shots, opt):
        out = os.path.join(OUT, time.strftime("reel_%Y%m%d_%H%M%S.mp4"))
        E.build_reel(shots, out, opt, lambda p, t: self._emit("progress", {"p": p, "t": t}))
        self._emit("export_done", {"path": out})

    def save_voice(self, b64):
        try:
            p = os.path.join(tempfile.gettempdir(), f"dve_voice_{int(time.time() * 1000)}.webm")
            open(p, "wb").write(base64.b64decode(b64)); return p
        except Exception:
            log.exception("save_voice failed"); return ""

    # ---- YouTube ----
    def info(self, url):
        try: return E.yt_info(url, self._browser)
        except Exception as e: log.exception("info failed"); return {"error": str(e)[-300:]}

    def download(self, req): self._bg("download", self._download, req)
    def _download(self, req):
        p = E.yt_download(req["url"], req["start"], req["end"], os.path.join(OUT, "downloads"), self._browser, req.get("crop"),
                          lambda p, t: self._emit("progress", {"p": p, "t": t}))
        self._done(p, {})

    def _done(self, p, extra):
        d = E.duration(p)
        self._emit("dl_done", {"path": p, "dur": d, "thumb": E.thumb(p, min(1, d / 2)), "url": media_url(p), **extra})

    # auto clips from a YouTube video
    def yt_auto(self, url, modes, start=0, end=0, split_len=8): self._bg("yt_auto", self._yt_auto, url, modes, start, end, split_len)
    def _yt_auto(self, url, modes, start, end, split_len):
        clips, info = E.yt_candidates(url, modes, start, end, split_len, self._browser, lambda p, t: self._emit("progress", {"p": p, "t": t}))
        self._emit("yt_clips", {"clips": clips, "title": info.get("title", "")})

    def yt_get(self, url, clips, crop=None): self._bg("yt_get", self._yt_get, url, clips, crop)
    def _yt_get(self, url, clips, crop):
        for i, c in enumerate(clips):
            p = E.yt_download(url, c["start"], c["end"], os.path.join(OUT, "downloads"), self._browser, crop,
                              lambda p, t, i=i: self._emit("progress", {"p": p, "t": f"Clip {i + 1}/{len(clips)}: {t}"}))
            hits = [round(h - c["start"], 2) for h in c.get("hits", []) if c["start"] <= h <= c["end"]]
            self._done(p, {"hits": hits, "tag": c.get("tag", "CLIP"), "cap": c.get("cap", "")})
        self._emit("progress", {"p": 100, "t": f"Downloaded {len(clips)} clips and added to your shots"})

    def set_browser(self, b): self._browser = b or None; return True

    # ---- misc ----
    def version(self): return VERSION
    def title(self, n): return E.make_title(n)
    def open_folder(self):
        os.makedirs(OUT, exist_ok=True)
        if hasattr(os, "startfile"): os.startfile(OUT)
    def open_logs(self):
        if hasattr(os, "startfile"): os.startfile(LOGDIR)


if __name__ == "__main__":
    try:
        log.info("starting Dark Video Edit %s", VERSION)
        api = Api()
        window = webview.create_window(f"Dark Video Edit {VERSION}", E.res("ui", "index.html"), js_api=api,
                                       width=1480, height=920, min_size=(1100, 700), background_color="#09080b")
        api._win = window
        webview.start(http_server=True, private_mode=False, storage_path=LOGDIR)
        log.info("closed normally")
    except Exception:
        log.error("STARTUP FAILED\n" + traceback.format_exc()); open(os.path.join(LOGDIR, "error.log"), "w").write(traceback.format_exc()); raise
