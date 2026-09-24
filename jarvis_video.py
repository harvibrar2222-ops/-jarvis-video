#!/usr/bin/env python3
"""
Jarvis Video Generator
----------------------
Usage:
    python jarvis_video.py "How black holes work"

Requirements:
    pip install anthropic pillow gtts

Also required:
    ffmpeg installed and available in PATH.

Environment:
    ANTHROPIC_API_KEY=your_api_key

Output:
    jarvis-video-<topic>/
        script.json
        scene_01.png
        scene_01.mp3
        ...
        final.mp4
"""

import os
import sys
import json
import re
import shutil
import subprocess
from pathlib import Path

try:
    from anthropic import Anthropic
    from PIL import Image, ImageDraw, ImageFont
    from gtts import gTTS
except ImportError as e:
    print(f"Missing Python package: {e}")
    print("Run: pip install anthropic pillow gtts")
    sys.exit(1)


WIDTH, HEIGHT = 1280, 720
FPS = 30


def slugify(text):
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return text[:60] or "topic"


def find_font(bold=False):
    candidates = []
    if sys.platform == "darwin":
        candidates += [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial Bold.ttf" if bold
            else "/Library/Fonts/Arial.ttf",
        ]
    elif sys.platform.startswith("win"):
        candidates += [
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        ]
    else:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]

    for path in candidates:
        if Path(path).exists():
            return path
    return None


def font(size, bold=False):
    path = find_font(bold)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def wrap_text(draw, text, fnt, max_width):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        trial = word if not current else current + " " + word
        if draw.textbbox((0, 0), trial, font=fnt)[2] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_text_box(draw, xy, text, fnt, fill, max_width, line_spacing=10):
    x, y = xy
    lines = wrap_text(draw, text, fnt, max_width)
    bbox = draw.textbbox((0, 0), "Ag", font=fnt)
    line_h = bbox[3] - bbox[1] + line_spacing

    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += line_h
    return y


def make_slide(scene, index, total, output):
    img = Image.new("RGB", (WIDTH, HEIGHT), (12, 18, 32))
    d = ImageDraw.Draw(img)

    # Simple animated-slide visual system:
    # gradient-like horizontal bands + circles/lines + content cards.
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        c = (
            int(12 + 12 * ratio),
            int(18 + 18 * ratio),
            int(32 + 25 * ratio),
        )
        d.line((0, y, WIDTH, y), fill=c)

    # Decorative shapes
    d.ellipse((WIDTH - 270, -100, WIDTH + 80, 250), fill=(35, 75, 125))
    d.ellipse((-130, HEIGHT - 230, 220, HEIGHT + 120), fill=(30, 90, 100))
    d.line((0, 105, WIDTH, 105), fill=(80, 130, 170), width=2)

    # Scene indicator
    small = font(26, bold=True)
    d.text((60, 45), f"SCENE {index}/{total}", font=small, fill=(190, 215, 235))

    title = scene.get("title", f"Scene {index}")
    body = scene.get("visual_text", scene.get("narration", ""))

    title_font = font(58, bold=True)
    body_font = font(31)

    # Main card
    card = (65, 145, WIDTH - 65, HEIGHT - 70)
    d.rounded_rectangle(card, radius=28, fill=(20, 30, 48), outline=(75, 120, 155), width=2)

    d.text((105, 190), title, font=title_font, fill=(245, 250, 255))

    draw_text_box(
        d,
        (105, 285),
        body,
        body_font,
        (205, 220, 232),
        WIDTH - 270,
        line_spacing=12,
    )

    # Visual keyword / concept
    concept = scene.get("visual", "Key idea")
    pill_font = font(24, bold=True)
    pill_text = concept[:48]
    pb = d.textbbox((0, 0), pill_text, font=pill_font)
    pw = pb[2] - pb[0] + 40
    ph = 50
    d.rounded_rectangle(
        (105, HEIGHT - 125, 105 + pw, HEIGHT - 125 + ph),
        radius=25,
        fill=(45, 100, 125),
    )
    d.text((125, HEIGHT - 113), pill_text, font=pill_font, fill="white")

    path = output / f"scene_{index:02d}.png"
    img.save(path)
    return path


def ask_claude(topic):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Set it before running the program."
        )

    client = Anthropic(api_key=api_key)

    prompt = f"""
Create a factual 5-7 scene animated-slide explainer about:

TOPIC: {topic}

Return ONLY valid JSON with this structure:
{{
  "title": "short video title",
  "scenes": [
    {{
      "title": "short scene title",
      "narration": "Natural voiceover, around 45-90 words.",
      "visual": "2-6 word visual concept",
      "visual_text": "Short text suitable for a slide, maximum about 35 words."
    }}
  ]
}}

Requirements:
- Use exactly 5 to 7 scenes.
- Start with a strong but factual hook.
- Explain the topic clearly for a general audience.
- Use concrete examples where useful.
- End with a concise takeaway.
- Do not invent facts.
- Keep narration natural for text-to-speech.
- Do not use markdown.
"""

    response = client.messages.create(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5"),
        max_tokens=5000,
        messages=[{"role": "user", "content": prompt}],
    )

    text = "".join(
        block.text for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()

    # Remove accidental markdown fences.
    text = re.sub(r"^```json\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract the outer JSON object.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(text[start:end + 1])
        else:
            raise RuntimeError("Claude returned invalid JSON.")

    scenes = data.get("scenes", [])
    if not 5 <= len(scenes) <= 7:
        raise RuntimeError(f"Claude returned {len(scenes)} scenes; expected 5-7.")

    return data


def make_voiceovers(scenes, output):
    audio_files = []

    for i, scene in enumerate(scenes, 1):
        text = scene.get("narration", "").strip()
        if not text:
            raise RuntimeError(f"Scene {i} has no narration.")

        path = output / f"scene_{i:02d}.mp3"
        print(f"  Creating voiceover {i}/{len(scenes)}...")
        gTTS(text=text, lang="en", slow=False).save(str(path))
        audio_files.append(path)

    return audio_files


def get_audio_duration(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def build_video(slides, audios, output_file):
    # Create one MP4 per scene with its own audio, then concatenate.
    scene_videos = []

    for i, (slide, audio) in enumerate(zip(slides, audios), 1):
        duration = get_audio_duration(audio)
        scene_mp4 = slide.parent / f"scene_{i:02d}.mp4"

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", str(slide),
                "-i", str(audio),
                "-t", f"{duration:.3f}",
                "-vf", f"scale={WIDTH}:{HEIGHT},format=yuv420p",
                "-r", str(FPS),
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "20",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(scene_mp4),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        scene_videos.append(scene_mp4)

    concat_file = output_file.parent / "concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for path in scene_videos:
            # ffmpeg concat demuxer requires escaped single quotes.
            p = str(path.resolve()).replace("'", r"'\''")
            f.write(f"file '{p}'\n")

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_file),
        ],
        check=True,
    )

    return output_file


def check_ffmpeg():
    for program in ("ffmpeg", "ffprobe"):
        if shutil.which(program) is None:
            raise RuntimeError(
                f"{program} was not found. Install FFmpeg and make sure it is in PATH."
            )


def main():
    if len(sys.argv) < 2:
        print('Usage: python jarvis_video.py "your topic"')
        sys.exit(1)

    topic = " ".join(sys.argv[1:]).strip()
    output = Path(f"jarvis-video-{slugify(topic)}")
    output.mkdir(parents=True, exist_ok=True)

    print(f"\nTopic: {topic}")
    print(f"Output: {output.resolve()}\n")

    check_ffmpeg()

    print("1/4 Researching and writing the script with Claude...")
    data = ask_claude(topic)

    with open(output / "script.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    scenes = data["scenes"]

    print(f"2/4 Drawing {len(scenes)} slides...")
    slides = [
        make_slide(scene, i, len(scenes), output)
        for i, scene in enumerate(scenes, 1)
    ]

    print("3/4 Creating voiceovers...")
    audios = make_voiceovers(scenes, output)

    print("4/4 Stitching the MP4...")
    final = output / "final.mp4"
    build_video(slides, audios, final)

    print("\nDONE")
    print(f"Video: {final.resolve()}")
    print(f"Script: {(output / 'script.json').resolve()}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)
    except subprocess.CalledProcessError as e:
        print("\nFFmpeg failed. Make sure FFmpeg is installed and working.")
        sys.exit(e.returncode or 1)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
