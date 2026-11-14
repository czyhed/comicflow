"""Inspect the actual export downloaded by the full-flow browser test (no providers)."""

import array
import hashlib
import json
import subprocess
from pathlib import Path

OUT = Path("/verification")
VIDEO = OUT / "video.mp4"


def run(*args):
    return subprocess.check_output(args)


def frame(at):
    return run(
        "ffmpeg",
        "-v",
        "error",
        "-ss",
        str(at),
        "-i",
        str(VIDEO),
        "-frames:v",
        "1",
        "-vf",
        "scale=108:192",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    )


def main():
    browser = json.loads((OUT / "browser-report.json").read_text())
    assert browser["status"] == "passed"
    probe = json.loads(
        run("ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(VIDEO))
    )
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (1080, 1920, "30/1")
    assert video["codec_name"] == "h264" and audio["codec_name"] == "aac"
    assert abs(float(probe["format"]["duration"]) - 30) <= 1 / 30
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255)]
    evidence = []
    for i, expected in enumerate(colors):
        first, second = frame(i * 5 + 0.5), frame(i * 5 + 1.5)
        actual = tuple(first[(5 * 108 + 5) * 3 : (5 * 108 + 5) * 3 + 3])
        assert all(abs(a - b) < 20 for a, b in zip(actual, expected, strict=True)), (i, actual)
        assert first != second, f"Shot {i + 1} is frozen"
        samples = array.array(
            "h",
            run(
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(i * 5 + 1),
                "-i",
                str(VIDEO),
                "-t",
                "1",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "48000",
                "-f",
                "s16le",
                "-",
            ),
        )
        assert max(abs(s) for s in samples) > 100
        frequency = sum(a <= 0 < b for a, b in zip(samples, samples[1:], strict=False))
        assert abs(frequency - (440 + 110 * i)) <= 5, (i, frequency)
        evidence.append(
            {
                "shot": i + 1,
                "color": actual,
                "frequencyHz": frequency,
                "motionSampleHashes": [hashlib.sha256(f).hexdigest() for f in (first, second)],
            }
        )
    from PIL import Image

    with Image.open(OUT / "cover.jpg") as cover:
        assert cover.size == (1080, 1920)
        cover.verify()
    subtitles = (OUT / "subtitles.srt").read_text(encoding="utf-8-sig")
    assert subtitles.count(" --> ") == 6
    assert "00:00:30,000" in subtitles and "谢谢你" in subtitles
    report = {
        "status": "passed",
        "durationSec": float(probe["format"]["duration"]),
        "width": video["width"],
        "height": video["height"],
        "fps": video["r_frame_rate"],
        "videoCodec": video["codec_name"],
        "audioCodec": audio["codec_name"],
        "sixOrderedMovingShotsWithNativeAudio": evidence,
        "subtitleEntries": 6,
        "realModelCalls": 0,
        "qualityScope": "synthetic test media, not model quality",
    }
    (OUT / "media-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps({k: v for k, v in report.items() if k != "sixOrderedMovingShotsWithNativeAudio"})
    )


if __name__ == "__main__":
    main()
