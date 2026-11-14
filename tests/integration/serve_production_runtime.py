"""Disposable full-flow stack. Fake supplier HTTP, real application and media tools."""

from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from verify_video_runtime import configure

OUT = Path("/verification")
ROOT = Path("/workspace")
PREFIX = "comicflow_verify_flow"
BASE = "http://127.0.0.1:18099"
COLORS = ["red", "lime", "blue", "yellow", "magenta", "cyan"]


def story_fixture():
    paragraphs = [
        "暴雨落在街道上，林青抱着一把损坏的雨伞寻找避雨的地方。便利店透出温暖的灯光，她走近玻璃门，伸手握住门把手，将门推开后迈过门槛。雨水顺着蓝色外套滴落，她站在门内收好雨伞，望向柜台后的年轻店员。",
        "陈明听到门铃声，放下手中的货物转过身来。他看见林青湿透的袖口，从柜台下面找出毛巾，示意她先擦掉雨水。林青低声道谢，把坏掉的雨伞递给他。两人检查弯曲的伞骨，发现它已经无法重新撑开。",
        "街上的雨越下越大，林青担心赶不上回家的末班车。陈明看了一眼挂钟，拿起自己的备用雨伞。他走到门口，先观察路面的积水，再招呼林青一起出去。两人依次穿过店门，停在屋檐下确认车站的方向。",
        "陈明举起雨伞，等伞面完全展开后才走下台阶。林青靠近伞下，扶稳肩上的背包。两人沿着街边向车站走去，便利店的灯光在身后渐渐变远。林青再次向陈明道谢，陈明点了点头，放慢脚步让她跟上。",
    ]
    return {
        "kind": "story_text",
        "version": 1,
        "mode": "automatic",
        "task": "story_expansion",
        "content": {
            "title": "雨夜便利店",
            "logline": "雨夜陌生人的援手让归途多了一份温暖。",
            "setting": "暴雨中的城市街道和仍在营业的便利店。",
            "characters": [
                {"name": "林青", "goal": "赶车回家"},
                {"name": "陈明", "goal": "帮助客人"},
            ],
            "text": "\n\n".join(paragraphs),
            "beats": [
                {"type": kind, "text": paragraph}
                for kind, paragraph in zip(
                    ("setup", "development", "turn", "ending"), paragraphs, strict=True
                )
            ],
        },
    }


def script_fixture():
    actions = ["推门入店", "店员转身", "递交雨伞", "走到街边", "举起雨伞", "共同离开"]
    shots = []
    for i, action in enumerate(actions, 1):
        shots.append(
            {
                "id": f"s{i}",
                "sceneId": "inside" if i <= 3 else "street",
                "order": i,
                "title": action,
                "action": action,
                "actionBefore": "林青站定，面向行动方向。",
                "actionMiddle": action + "，动作连续完成。",
                "actionAfter": action + "已完成，双脚站稳。",
                "emotion": "平静",
                "shotSize": "中景",
                "durationSec": 5,
                "visualDescription": f"林青在便利店内{action}。"
                if i <= 3
                else f"林青和陈明在街边{action}。",
                "dialogue": "林青：“谢谢你。”",
                "narration": "",
                "characters": ["林青"] if i == 1 else ["林青", "陈明"],
                "cameraMovement": "缓慢跟随",
                "visualStyle": "写实电影",
                "soundscape": "雨声",
                "music": "无音乐",
                "generationMode": "t2va",
            }
        )
    scenes = [
        dict(
            id=sid,
            title=title,
            time="夜晚",
            location=title,
            narrativeGoal="帮助避雨",
            conflict="雨势渐大",
            turningPoint="共同离开",
            shotIds=ids,
        )
        for sid, title, ids in [
            ("inside", "便利店内", ["s1", "s2", "s3"]),
            ("street", "店外街道", ["s4", "s5", "s6"]),
        ]
    ]
    return {
        "kind": "script",
        "version": 1,
        "mode": "automatic",
        "task": "script_split",
        "content": {"title": "隔离验证：雨夜便利店", "scenes": scenes, "shots": shots},
    }


class Supplier(BaseHTTPRequestHandler):
    text_calls = []
    images = []
    videos = []
    polls = 0
    downloads = 0
    failed_download = False
    ready = False
    restart = threading.Event()
    restart_count = 0

    def log_message(self, *_args):
        pass

    def reply(self, data, status=200, mime="application/json"):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        cls = type(self)
        if self.path == "/test-control/restart":
            cls.ready = False
            cls.restart.set()
            self.reply({"accepted": True}, 202)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/chat/completions"):
            cls.text_calls.append(body)
            fixture = script_fixture()
            system = body["messages"][0]["content"]
            # Follow the adapter's explicit requested envelope, never alter application results.
            import re

            match = re.search(r"本次任务标识：mode=(\w+)，task=(\w+)", system)
            if match:
                if match[2] == "story_expansion":
                    fixture = story_fixture()
                fixture.update(mode=match[1], task=match[2])
            if body.get("stream"):
                content = json.dumps(fixture, ensure_ascii=False)
                chunks = [content[: len(content) // 2], content[len(content) // 2 :]]
                events = "".join(
                    "data: "
                    + json.dumps({"choices": [{"delta": {"content": chunk}}]}, ensure_ascii=False)
                    + "\n\n"
                    for chunk in chunks
                )
                self.reply((events + "data: [DONE]\n\n").encode(), mime="text/event-stream")
                return
            self.reply(
                {"choices": [{"message": {"content": json.dumps(fixture, ensure_ascii=False)}}]}
            )
        elif self.path == "/minimax/v2/video_generation":
            cls.videos.append(body)
            self.reply({"task_id": f"video-{len(cls.videos)}"})
        elif "/services/" in self.path:
            from PIL import Image, ImageDraw

            number = len(cls.images) + 1
            size = body.get("parameters", {}).get("size", "720*1280")
            width, height = map(int, size.split("*"))
            img = Image.new("RGB", (width, height), COLORS[(number - 1) % 6])
            ImageDraw.Draw(img).rectangle((30, 30, 160, 250), fill="white")
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            (OUT / f"image-{number}.png").write_bytes(buffer.getvalue())
            cls.images.append(body)
            self.reply({"output": {"task_id": f"image-{number}"}})
        else:
            self.reply({"unexpected": self.path}, 500)

    def do_GET(self):
        cls = type(self)
        if self.path == "/test-control/status":
            report = {
                "ready": cls.ready,
                "restarts": cls.restart_count,
                "textCalls": len(cls.text_calls),
                "images": len(cls.images),
                "videos": len(cls.videos),
                "polls": cls.polls,
                "downloads": cls.downloads,
                "failedDownload": cls.failed_download,
                "realModelCalls": 0,
                "imageRequests": cls.images,
                "videoRequests": cls.videos,
            }
            self.reply(report)
        elif self.path.startswith("/minimax/v2/query/video_generation/"):
            cls.polls += 1
            num = int(self.path.rsplit("-", 1)[1])
            self.reply(
                {
                    "task": {
                        "id": f"video-{num}",
                        "status": "succeeded",
                        "content": {"url": f"{BASE}/video-{num}.mp4"},
                    }
                }
            )
        elif "/tasks/image-" in self.path:
            cls.polls += 1
            name = self.path.rsplit("/", 1)[1]
            url = f"{BASE}/{name}.png"
            self.reply(
                {
                    "output": {
                        "task_status": "SUCCEEDED",
                        "results": [{"url": url}],
                        "choices": [{"message": {"content": [{"image": url}]}}],
                    }
                }
            )
        elif self.path.endswith((".png", ".mp4")):
            assert not self.headers.get("Authorization"), "Secret leaked to media download"
            cls.downloads += 1
            if self.path == "/video-3.mp4" and not cls.failed_download:
                cls.failed_download = True
                self.reply({"error": "controlled download failure"}, 503)
                return
            path = OUT / self.path.lstrip("/")
            if path.parent != OUT or not path.is_file():
                self.reply({}, 404)
                return
            self.reply(
                path.read_bytes(), mime="image/png" if path.suffix == ".png" else "video/mp4"
            )
        else:
            self.reply({"unexpected": self.path}, 404)


async def serve():
    import boto3
    import httpx
    from comicflow.infrastructure.database import (
        SqlAlchemyProjectRepository,
        create_session_factory,
    )
    from comicflow.worker.celery_app import publish_to_celery
    from comicflow.worker.outbox import OutboxDispatcher

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        aws_access_key_id="verification",
        aws_secret_access_key="verification-only",
    )
    s3.create_bucket(Bucket="comicflow-verify")
    engine, sessions = create_session_factory(os.environ["DATABASE_URL"])
    dispatcher = OutboxDispatcher(SqlAlchemyProjectRepository(sessions), publish_to_celery)
    processes = []
    logs = []

    def stop():
        for proc in reversed(processes):
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(5)
        processes.clear()
        for log in logs:
            log.close()
        logs.clear()

    async def start():
        commands = {
            "api": [
                "-m",
                "uvicorn",
                "comicflow.api.app:app",
                "--host",
                "0.0.0.0",
                "--port",
                "18098",
            ],
            "worker": [
                "-m",
                "celery",
                "-A",
                "comicflow.worker.celery_app:celery_app",
                "worker",
                "--pool=solo",
                "--concurrency=1",
                "--loglevel=INFO",
                "-Q",
                f"{PREFIX}.tasks",
                "--without-gossip",
                "--without-mingle",
            ],
        }
        for name, args in commands.items():
            log = (OUT / f"{name}-{Supplier.restart_count}.log").open("w")
            logs.append(log)
            # Test supervisor starts two local processes before dispatching any work.
            proc = subprocess.Popen([sys.executable, *args], stdout=log, stderr=log)  # noqa: ASYNC220
            processes.append(proc)
        async with httpx.AsyncClient() as client:
            for _ in range(100):
                try:
                    if (await client.get("http://127.0.0.1:18098/health")).status_code == 200:
                        Supplier.ready = True
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.2)
        raise RuntimeError("Isolated API did not start")

    try:
        await start()
        while True:
            if Supplier.restart.is_set():
                stop()
                Supplier.restart_count += 1
                Supplier.restart.clear()
                await start()
            if any(p.poll() is not None for p in processes):
                raise RuntimeError("Isolated API/worker exited")
            await dispatcher.dispatch_once()
            await asyncio.sleep(0.2)
    finally:
        stop()
        await engine.dispose()


def main():
    assert Path.cwd() == OUT
    configure()
    os.environ.update(
        {
            "COMICFLOW_REDIS_NAMESPACE": PREFIX,
            "MINIMAX_BASE_URL": BASE,
            "COMICFLOW_COMPOSITION_PROVIDER": "ffmpeg",
            "S3_PUBLIC_ENDPOINT": "http://127.0.0.1:4184",
        }
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "upgrade", "head"],
        cwd=ROOT,
        check=True,
    )
    for number, color in enumerate(COLORS, 1):
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=s=360x640:r=30:d=5,drawbox=x=0:y=0:w=100:h=100:color={color}:t=fill",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={330 + 110 * number}:duration=5",
                "-c:v",
                "libx264",
                "-threads",
                "2",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(OUT / f"video-{number}.mp4"),
            ],
            check=True,
        )
    server = ThreadingHTTPServer(("0.0.0.0", 18099), Supplier)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        asyncio.run(serve())
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
