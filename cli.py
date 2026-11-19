"""Headless test:  python cli.py scan clip.mp4 [kill,action,best,jump,motion,flash,damage,scene | split | whole]  |  python cli.py reel out.mp4 clip1.mp4 clip2.mp4  |  python cli.py crop in.mp4 out.mp4 9:16"""
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
import engine as E
if sys.argv[1] == "scan":
    mode = sys.argv[3] if len(sys.argv) > 3 else "all"
    for s in E.build_shots(sys.argv[2], mode):
        print(f"{s['start']:.1f}-{s['end']:.1f}s {s['tag']} kills={s['k']} hits={[round(h, 1) for h in s['hits']]}")
elif sys.argv[1] == "reel":
    shots = []
    for p in sys.argv[3:]: shots += E.build_shots(p, 'all')
    for i, s in enumerate(shots): s["cap"] = "Dushman bola - kon aaya idhar?" if i % 2 == 0 else "Ek shot ek kill"
    print(E.build_reel(shots, sys.argv[2], {}, lambda p, t: print(p, t)))
elif sys.argv[1] == "crop":
    print(E.crop_video(sys.argv[2], sys.argv[3], sys.argv[4]))
