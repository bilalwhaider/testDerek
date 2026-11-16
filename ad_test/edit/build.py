"""Build edit/final.mp4 from clip01.mov following freecut hard rules:
per-segment extract (grade + crop + punch-in + 30ms fades) -> lossless concat ->
PTS-shifted overlays -> ASS captions LAST -> two-pass loudnorm."""
import json, subprocess, shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
EDIT = ROOT / "edit"
SRC = ROOT / "clip01.mov"
FPS = 30
W, H = 1080, 1920
FONT = "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf"
YELLOW, RED, GREEN, WHITE = (255, 212, 0), (235, 52, 52), (40, 200, 110), (255, 255, 255)

# (src_start, src_end, beat, punch_in_from_src_time or None)
SEGS = [
    (0.00, 4.72, "HOOK", 2.42),
    (6.79, 10.48, "PAIN", 9.24),
    (10.75, 13.80, "SOLUTION", 12.10),
    (19.13, 21.50, "SPEED", None),
    (28.28, 30.22, "PROOF", None),
    (30.47, 32.76, "PROOF", None),
    (43.98, 48.33, "RISK", 46.40),
    (50.39, 51.50, "CTA", None),
    (54.76, 57.32, "SCARCITY", None),
]
GRADE = "eq=contrast=1.07:saturation=1.10:gamma=1.02,colorbalance=rs=0.02:bs=-0.02:rm=0.01"
ZOOM = 1.18

def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

# ---------- 1. segments ----------
def extract():
    d = EDIT / "clips_graded"; d.mkdir(exist_ok=True)
    paths, offsets, t = [], [], 0.0
    for i, (a, b, beat, pz) in enumerate(SEGS):
        dur = b - a
        base = f"scale=-2:{H},crop={W}:{H},{GRADE}"
        if pz is not None:
            zs = pz - a
            zw, zh = int(W * ZOOM) // 2 * 2, int(H * ZOOM) // 2 * 2
            vf = (f"[0:v]{base},split[b][z];"
                  f"[z]scale={zw}:{zh},crop={W}:{H}:(in_w-{W})/2:(in_h-{H})*0.30[zz];"
                  f"[b][zz]overlay=enable='gte(t,{zs:.3f})'[v]")
        else:
            vf = f"[0:v]{base}[v]"
        af = f"afade=t=in:st=0:d=0.03,afade=t=out:st={dur-0.03:.3f}:d=0.03"
        out = d / f"seg_{i:02d}.mp4"
        run(["ffmpeg", "-y", "-ss", f"{a:.3f}", "-i", str(SRC), "-t", f"{dur:.3f}",
             "-filter_complex", vf, "-map", "[v]", "-map", "0:a", "-af", af,
             "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
             "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)])
        paths.append(out); offsets.append(t); t += dur
    lst = EDIT / "concat.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in paths))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(EDIT / "base.mp4")])
    return offsets, t

# ---------- 2. overlays (PIL frame sequences) ----------
def font(sz): return ImageFont.truetype(FONT, sz)
def ease(t): t = max(0, min(1, t)); return 1 - (1 - t) ** 3

def pill(draw, cx, cy, text, sz, fg, bg, pad=(44, 26)):
    while True:
        f = font(sz); bb = draw.textbbox((0, 0), text, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        if tw + 2 * pad[0] <= 960 or sz <= 30: break
        sz -= 2
    x0, y0 = cx - tw / 2 - pad[0], cy - th / 2 - pad[1]
    draw.rounded_rectangle([x0, y0, cx + tw / 2 + pad[0], cy + th / 2 + pad[1]], radius=28, fill=bg)
    draw.text((cx - tw / 2 - bb[0], cy - th / 2 - bb[1]), text, font=f, fill=fg)

def ctext(draw, cx, cy, text, sz, fill, stroke=8):
    f = font(sz); bb = draw.textbbox((0, 0), text, font=f, stroke_width=stroke)
    draw.text((cx - (bb[2] - bb[0]) / 2 - bb[0], cy - (bb[3] - bb[1]) / 2 - bb[1]), text,
              font=f, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))

def render_overlay(name, dur, draw_fn):
    d = EDIT / "animations" / name
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True)
    n = int(round(dur * FPS))
    for i in range(n):
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw_fn(ImageDraw.Draw(im), i / FPS, dur, im)
        im.save(d / f"f_{i:04d}.png")
    return d

def slide_pill(text, fg, bg, y=440, sz=58):
    def fn(dr, t, dur, im):
        k = ease(t / 0.35); cx = W / 2 - (1 - k) * W
        pill(dr, cx, y, text, sz, fg, bg)
    return fn

def counter(name, a, b, label):
    def fn(dr, t, dur, im):
        k = ease((t - 0.15) / 1.0)
        v = round(a + (b - a) * k)
        ctext(dr, W / 2, 330, label, 60, WHITE, 6)
        ctext(dr, W / 2 - 270, 500, f"{a}%", 120, WHITE)
        ctext(dr, W / 2, 500, "→", 110, YELLOW)
        col = GREEN if v == b else YELLOW
        ctext(dr, W / 2 + 280, 500, f"{v}%", int(120 + 20 * (1 if v == b else 0)), col)
    return fn

def badge_24(dr, t, dur, im):
    s = 0.6 + 0.4 * ease(t / 0.3)
    ctext(dr, W / 2, 420, "24/7", int(190 * s), YELLOW, 10)
    if t > 0.35: pill(dr, W / 2, 610, "WHATSAPP SUPPORT", 54, (0, 0, 0), WHITE)

def guarantee(dr, t, dur, im):
    pill(dr, W / 2 - (1 - ease(t / 0.35)) * W, 380, "+1 FULL LETTER GRADE", 66, (0, 0, 0), YELLOW)
    if t > 2.3:
        k = ease((t - 2.3) / 0.3)
        pill(dr, W / 2 + (1 - k) * W, 560, "OR YOU DON'T PAY", 66, WHITE, RED)

def cta_card(dr, t, dur, im):
    a = int(250 * ease(t / 0.3))
    dr.rectangle([0, 0, W, H], fill=(12, 12, 16, a))
    if t < 0.15: return
    k = ease((t - 0.15) / 0.4)
    y = 40 * (1 - k)
    ctext(dr, W / 2, 560 + y, "GET YOUR KID'S", 84, WHITE, 0)
    ctext(dr, W / 2, 670 + y, "FREE STUDY PLAN", 96, YELLOW, 0)
    pill(dr, W / 2, 900 + y, "TAP THE LINK BELOW", 66, (0, 0, 0), YELLOW, pad=(56, 34))
    pulse = 1 + 0.04 * abs(((t * 2) % 2) - 1)
    ctext(dr, W / 2, 1120, "ONLY 5 SEATS LEFT THIS MONTH", int(52 * pulse), (255, 120, 120), 0)
    ctext(dr, W / 2, 1230, "[ placeholder CTA ]", 34, (150, 150, 150), 0)

# ---------- 3. captions (ASS) ----------
FIX = {"they're": "THEY", "great": None, "tanks?": "TANK?", "Tudor": "TUTOR", "Kissel": "KISAH",
       "Johnnevy": "JANAVI", "24": "24-HOUR", "-hour": None}
HL = {"STRAIGHT", "A'S", "TANK?", "EXAM", "MARCH,", "APART.", "PERSONALIZED", "24-HOUR", "WHATSAPP",
      "58", "88.", "70", "90.", "GUARANTEE", "DON'T", "PAY", "DIME", "LINK", "BELOW."}

def ass_t(s):
    cs = int(round(s * 100)); return f"{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}"

def build_ass(offsets, cta_start):
    words = [w for w in json.load(open(EDIT / "transcripts/clip01.json"))["words"] if w.get("type") == "word"]
    toks = []
    for si, ((a, b, *_), off) in enumerate(zip(SEGS, offsets)):
        for w in words:
            if w["end"] > a + 0.1 and w["start"] < b - 0.05:
                w = dict(w, start=max(w["start"], a + 0.05))
                txt = FIX.get(w["text"], w["text"].upper()) if w["text"] in FIX else w["text"].upper()
                if txt is None: continue
                toks.append((w["start"] - a + off, w["end"] - a + off, txt, si))
    chunks, cur = [], []
    for tk in toks:
        if cur and cur[-1][3] != tk[3]:
            chunks.append(cur); cur = []
        cur.append(tk)
        if len(cur) == 3 or (len(cur) >= 2 and tk[2][-1] in ".,?!") or tk[2][-1] in ".?":
            chunks.append(cur); cur = []
    if cur: chunks.append(cur)
    lines = []
    for i, c in enumerate(chunks):
        st = c[0][0]; en = chunks[i + 1][0][0] if i + 1 < len(chunks) else c[-1][1] + 0.2
        en = min(en, c[-1][1] + 0.4)
        if st >= cta_start: break
        en = min(en, cta_start)
        txt = " ".join(("{\\c&H00D4FF&}" + t.rstrip(".,") + "{\\c&HFFFFFF&}") if t in HL else t.rstrip(".,") for _, _, t, _ in c)
        lines.append(f"Dialogue: 0,{ass_t(st)},{ass_t(en)},Cap,,0,0,0,,{{\\fad(40,0)\\t(0,80,\\fscx108\\fscy108)\\t(80,160,\\fscx100\\fscy100)}}{txt.rstrip('.,')}")
    hook = [
        f"Dialogue: 1,{ass_t(0)},{ass_t(offsets[1])},Hook,,0,0,0,,{{\\fad(0,120)\\fs82\\pos(540,400)}}STRAIGHT A'S ALL YEAR...",
        f"Dialogue: 1,{ass_t(2.42)},{ass_t(offsets[1])},Hook,,0,0,0,,{{\\fad(60,120)\\pos(540,600)}}THEN THEY {{\\c&H3434EB&}}TANK{{\\c&HFFFFFF&}}\\NTHE EXAM?",
    ]
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Inter ExtraBold,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,7,3,2,90,90,440,1
Style: Hook,Inter ExtraBold,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,9,4,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    p = EDIT / "master.ass"; p.write_text(head + "\n".join(hook + lines) + "\n"); return p

# ---------- 4. compose ----------
def main():
    offsets, total = extract()
    o = offsets
    cta_start = total - 3.0
    ovs = [
        ("pain", o[1] + 0.1, o[2] - o[1] - 0.2, slide_pill("THE PROBLEM: EXAM-DAY MELTDOWN", WHITE, RED)),
        ("fix", o[2] + 0.1, o[3] - o[2] - 0.2, slide_pill("THE FIX: A PLAN BUILT FOR YOUR KID", (0, 0, 0), GREEN)),
        ("support", o[3] + 0.05, o[4] - o[3] - 0.1, badge_24),
        ("kisah", o[4] + 0.05, o[5] - o[4] - 0.1, counter("kisah", 58, 88, "KISAH")),
        ("janavi", o[5] + 0.05, o[6] - o[5] - 0.1, counter("janavi", 70, 90, "JANAVI")),
        ("guarantee", o[6] + 0.05, o[7] - o[6] - 0.1, guarantee),
        ("cta", cta_start, 3.0, cta_card),
    ]
    inputs, fparts, cur = ["-i", str(EDIT / "base.mp4")], [], "[0:v]"
    for idx, (name, st, dur, fn) in enumerate(ovs, start=1):
        d = render_overlay(name, dur, fn)
        inputs += ["-framerate", str(FPS), "-i", str(d / "f_%04d.png")]
        fparts.append(f"[{idx}:v]format=rgba,setpts=PTS-STARTPTS+{st:.3f}/TB[a{idx}]")
        fparts.append(f"{cur}[a{idx}]overlay=eof_action=pass:enable='between(t,{st:.3f},{st+dur:.3f})'[v{idx}]")
        cur = f"[v{idx}]"
    ass = build_ass(offsets, cta_start)
    fparts.append(f"{cur}subtitles='{ass}':fontsdir=/usr/share/fonts/opentype/inter[outv]")  # LAST
    comp = EDIT / "composite.mp4"
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fparts), "-map", "[outv]", "-map", "0:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "copy", "-movflags", "+faststart", str(comp)])
    # two-pass loudnorm to -14 LUFS (Meta/Reels)
    r = subprocess.run(["ffmpeg", "-i", str(comp), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    m = json.loads(r[r.rindex("{"):r.rindex("}") + 1])
    ln = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    run(["ffmpeg", "-y", "-i", str(comp), "-c:v", "copy", "-af", ln, "-c:a", "aac", "-b:a", "192k",
         "-ar", "48000", "-movflags", "+faststart", str(EDIT / "final.mp4")])
    edl = {"version": 1, "sources": {"clip01": str(SRC)},
           "ranges": [{"source": "clip01", "start": a, "end": b, "beat": bt, "output_start": round(of, 3)}
                      for (a, b, bt, _), of in zip(SEGS, offsets)],
           "grade": GRADE, "overlays": [{"name": n, "start_in_output": round(s, 3), "duration": round(d, 3)} for n, s, d, _ in ovs],
           "subtitles": "edit/master.ass", "total_duration_s": round(total, 3)}
    (EDIT / "edl.json").write_text(json.dumps(edl, indent=2))
    print("total", round(total, 2), "offsets", [round(x, 2) for x in offsets])

if __name__ == "__main__":
    main()
