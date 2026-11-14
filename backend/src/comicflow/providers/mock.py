from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from comicflow.domain.models import JsonObject


class MockTextProvider:
    async def stream_story_text(
        self, story: str, project_id: str, target_duration_sec: int = 60
    ) -> AsyncIterator[str]:
        text = await self.generate_story_text(story, project_id, target_duration_sec)
        for offset in range(0, len(text), 48):
            await asyncio.sleep(0)
            yield text[offset : offset + 48]

    async def generate_story_text(
        self, story: str, project_id: str, target_duration_sec: int = 60
    ) -> str:
        del project_id
        seed = _story_seed(story)
        paragraphs = [
            f"{seed['subject']}在{seed['setting']}中，因为{seed['conflict']}而被迫行动。",
            f"起初，{seed['subject']}试图{seed['goal']}，但{seed['obstacle']}让计划不断失控。",
            f"当{seed['clue']}出现时，{seed['subject']}终于意识到真正的代价，必须在留下和离开之间选择。",
            f"最后，{seed['subject']}带着新的答案{seed['ending']}，结尾保留一处可以继续发展的余波。",
        ]
        minimum = 300 if target_duration_sec <= 30 else 600 if target_duration_sec <= 60 else 900
        text = "\n\n".join(paragraphs)
        while len(text) < minimum:
            text += f"\n\n{seed['subject']}回望{seed['setting']}，把这次选择写进了接下来的路。"
        return text[:8000]

    async def split_script(
        self, story_text: str, project_id: str, target_duration_sec: int = 60
    ) -> JsonObject:
        return await self.generate_script(story_text, project_id, target_duration_sec)

    async def generate_script(
        self, story: str, project_id: str, target_duration_sec: int = 60
    ) -> JsonObject:
        seed = _story_seed(story)
        scene_count, shot_count = _scale(target_duration_sec)
        durations = _durations(target_duration_sec, shot_count)
        scene_titles = [f"{seed['setting']}的开端", "线索浮现", "选择逼近", "余波与答案"][
            :scene_count
        ]
        shots: list[JsonObject] = []
        scenes: list[JsonObject] = []
        for scene_index, title in enumerate(scene_titles, start=1):
            scene_id = f"{project_id}_scene_{scene_index}"
            scene_shots = _scene_shot_count(shot_count, scene_count, scene_index)
            shot_ids: list[str] = []
            for _ in range(scene_shots):
                order = len(shots) + 1
                shot_id = f"{project_id}_shot_{order}"
                shot_ids.append(shot_id)
                is_turn = order == min(3, shot_count)
                shots.append(
                    {
                        "id": shot_id,
                        "sceneId": scene_id,
                        "order": order,
                        "title": f"{title} · 镜头{order}",
                        "action": "追寻线索" if is_turn else "观察并前进",
                        "emotion": "紧张" if is_turn else "克制",
                        "shotSize": "近景" if is_turn else "中景",
                        "durationSec": durations[order - 1],
                        "visualDescription": (
                            f"{seed['subject']}在{seed['setting']}中{seed['clue']}，"
                            f"{title}的动态漫画画面"
                        ),
                        "dialogue": (
                            f"我一定要{seed['goal']}。"
                            if order == 1
                            else "你终于来了。"
                            if is_turn
                            else ""
                        ),
                        "narration": f"{seed['subject']}继续{seed['goal']}。" if order != 1 else "",
                        "characters": [seed["subject"]] if order == 1 or is_turn else [],
                    }
                )
            scenes.append(
                {
                    "id": scene_id,
                    "title": title,
                    "time": "夜晚" if scene_index % 2 else "凌晨",
                    "location": seed["setting"],
                    "narrativeGoal": f"推动{seed['subject']}{seed['goal']}",
                    "conflict": seed["conflict"],
                    "turningPoint": seed["clue"] if scene_index == scene_count else seed["ending"],
                    "shotIds": shot_ids,
                }
            )
        title = (
            "雨夜的最后一班车"
            if seed["subject"] == "主角"
            else f"{seed['subject']}的{seed['clue']}"
        )
        return {
            "kind": "script",
            "version": 1,
            "mode": "guided",
            "task": "script_outline",
            "content": {"title": title, "scenes": scenes, "shots": shots},
        }

    async def generate_guided_question(
        self,
        story: str,
        script: JsonObject,
        transcript: list[JsonObject],
        project_id: str,
        target_duration_sec: int = 60,
    ) -> JsonObject:
        del story, script, project_id, target_duration_sec

        targets = [
            ("goal", "主角目标", "主角最想得到什么，失败会付出什么代价？"),
            ("conflict", "核心冲突", "核心冲突：谁或什么力量会阻止主角实现目标？"),
            ("turn", "关键转折", "哪个线索或事件会迫使主角改变选择？"),
            ("ending", "结尾情绪", "结尾希望观众留下哪种情绪或画面？"),
        ]
        answered: set[str] = set()
        for index, item in enumerate(transcript):
            if not isinstance(item, dict):
                continue
            question_type = item.get("questionType")
            question = str(item.get("question", ""))
            if isinstance(question_type, str):
                answered.add(question_type)
            elif "目标" in question:
                answered.add("goal")
            elif "冲突" in question:
                answered.add("conflict")
            elif "转折" in question:
                answered.add("turn")
            elif "结尾" in question:
                answered.add("ending")
            elif index < len(targets):
                answered.add(targets[index][0])
        for question_type, label, question in targets:
            if question_type not in answered:
                return {
                    "questionId": f"{question_type}-1",
                    "questionType": question_type,
                    "question": question,
                    "missingFields": [label],
                    "options": [],
                    "done": False,
                }
        return {
            "questionId": "complete",
            "questionType": "ending",
            "question": "",
            "missingFields": [],
            "options": [],
            "done": True,
        }

    async def generate_detailed_script(
        self,
        story: str,
        script: JsonObject,
        transcript: list[JsonObject],
        project_id: str,
        target_duration_sec: int = 60,
    ) -> JsonObject:
        del story, project_id, target_duration_sec

        # Handle both envelope format and plain content
        if isinstance(script, dict) and script.get("kind") == "script":
            content = script.get("content", {})
        else:
            content = script

        detailed = {"title": content.get("title", "未命名剧本"), "scenes": [], "shots": []}
        answers = [str(item.get("answer", "")) for item in transcript if isinstance(item, dict)]
        answer_text = "；".join(answer for answer in answers if answer)
        for scene in content.get("scenes", []):
            copied = dict(scene)
            if answer_text:
                copied["conflict"] = f"{copied.get('conflict', '')}（用户确认：{answer_text}）"
                copied["turningPoint"] = f"{copied.get('turningPoint', '')}，因此主角选择继续追查"
            detailed["scenes"].append(copied)
        for shot in content.get("shots", []):
            copied = dict(shot)
            if answer_text and copied.get("order") == 1:
                copied["dialogue"] = answer_text
            detailed["shots"].append(copied)
        return {
            "kind": "script",
            "version": 1,
            "mode": "guided",
            "task": "detailed_script",
            "content": detailed,
        }


def _story_seed(story: str) -> dict[str, str]:
    text = story.strip()
    subject = "主角"
    if "记者" in text:
        subject = "记者"
    elif "守夜人" in text:
        subject = "守夜人"
    elif "姐姐" in text:
        subject = "弟弟"
    setting = "海边灯塔" if "海" in text or "灯塔" in text else "雨夜车站"
    goal = (
        "找到失踪的船员" if "船" in text else "找回姐姐并揭开真相" if "姐姐" in text else "追到答案"
    )
    conflict = "通讯中断和即将到来的风暴" if "海" in text else "一段被掩盖的旧事故"
    obstacle = "无人回应的电话和逐渐上涨的潮水" if "海" in text else "陌生人的阻拦和失真的记忆"
    clue = "一张沾着海盐的旧照片" if "海" in text else "一张被撕碎的旧车票"
    ending = "走进风暴，也终于等到远处的灯光" if "海" in text else "跟随末班车驶向终点"
    return {
        "subject": subject,
        "setting": setting,
        "goal": goal,
        "conflict": conflict,
        "obstacle": obstacle,
        "clue": clue,
        "ending": ending,
    }


def _scale(duration: int) -> tuple[int, int]:
    if duration <= 30:
        return 2, 6
    if duration <= 60:
        return 3, 9
    return 4, 11


def _durations(total: int, count: int) -> list[int]:
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _scene_shot_count(total: int, scenes: int, scene_index: int) -> int:
    base, remainder = divmod(total, scenes)
    return base + (1 if scene_index <= remainder else 0)
