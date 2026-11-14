from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator

import httpx

from comicflow.domain.models import JsonObject
from comicflow.providers.character_prompt import (
    character_prompt_system,
    validate_character_prompt,
)
from comicflow.providers.drama_skills import MANJU_SKILL, XIAOLUO_SKILL, load_stage_skill
from comicflow.providers.h3_errors import H3ResponseError, H3TextResponseError, ResponseReason
from comicflow.providers.message_contract import (
    ScriptContractError,
    normalize_generation_message,
    normalize_guided_question_message,
    normalize_script_message,
    normalize_story_message,
    valid_speech_fields,
)
from comicflow.providers.text_errors import (
    TextRequestError,
    script_response_error,
    text_request_error,
    text_timeout_error,
)
from comicflow.providers.text_progress import report_text_progress, text_progress

SCRIPT_SYSTEM_PROMPT = (
    "你是短视频分镜编剧。根据用户故事，只输出一个合法 JSON 对象，"
    "不要 Markdown、解释或 <think> 内容。\n"
    "顶层格式必须是 {\"kind\":\"script\",\"version\":1,"
    "\"mode\":\"__MODE__\",\"task\":\"__TASK__\",\"content\":{...}}，"
    "不得输出其他字段。\n"
    "content 必须包含 title、scenes、shots。生成 6 到 12 个 shots，"
    "总时长 30 到 90 秒。\n"
    "每个 shot 必须包含：id、title、action、actionBefore、actionMiddle、actionAfter、"
    "emotion、shotSize、durationSec（数字）、visualDescription、dialogue、narration、"
    "characters。action 只能有一个主要动作；actionBefore 写动作开始前的可见位置和姿态，"
    "actionMiddle 写连续发生的关键物理过程，actionAfter 写动作已经完整完成的可见结果，"
    "不能写意图、感受或仍在进行的中间状态。例如“推门进入便利店”应写成："
    "actionBefore 为“角色站在店外门前，手尚未触门”，actionMiddle 为“角色推开玻璃门并跨过门槛”，"
    "actionAfter 为“角色双脚和身体已完全进入店内，玻璃门在身后回摆”。\n"
    "这是供用户编辑的中文剧本，不是英文视频 Prompt。"
    "所有面向用户的描述值必须使用简体中文，包括 title、action、emotion、shotSize、"
    "visualDescription、场景信息、cameraMovement、visualStyle、soundscape、music。"
    "只有 JSON 字段名、id 和 generationMode 使用技术标识；人名和原始对白保留原意。"
    "每个 shot 还要提供 cameraMovement、visualStyle、soundscape、music 和 generationMode。"
    "generationMode 只能是 t2va、i2va、fl2va、l2va、ref2va；没有参考素材时使用 t2va。\n"
    "cameraMovement 写清运镜，visualStyle 保持全剧一致，soundscape 描述环境声，"
    "music 描述非叙事音乐。"
    "后续视频 Prompt 编写阶段使用项目 skills/h3-prompt-writing/SKILL.md，"
    "该 Skill 的英文扩写规则不应用于本次中文剧本，不要输出英文扩写段落或引用占位符。\n"
    "characters 是字符串数组，列出出现在此镜头中的角色名称（从故事中提取）；"
    "如果镜头中没有具体角色出现，输出空数组 []。\n"
    "每个 scene 必须包含：id、title、time、location、narrativeGoal、conflict、"
    "turningPoint、shotIds；"
    "shotIds 必须引用对应 shots 的 id。"
    "scene 可另外提供 lighting（主光方向与色温，如“左侧冷白路灯，车厢顶部暖黄灯管”）"
    "和 weather（如“暴雨”“晴”“室内无天气”），同一场景的镜头沿用这组光线和天气。"
    "必须保留用户文本中的每一句对白，按原意逐句写入对应 shot.dialogue；"
    "多句对白用换行分隔，可在行首保留角色名。没有对白时 dialogue 输出空字符串，"
    "narration只描述实际要读出的画外旁白，环境声写入soundscape，配乐写入music。"
    "故事中的画面描写不需要全文朗读；对白和旁白合计不超过（durationSec−1）×4 个可发音字符，"
    "即 4秒≤12字、5秒≤16字、6秒≤20字、8秒≤28字、10秒≤36字、12秒≤44字、15秒≤56字，"
    "给动作和反应留余量，不能把两者分别占满整个镜头。超出时先删减旁白，原对白逐句保留。\n"
    "竖屏短剧节奏：第1镜前3秒必须出现异常、冲突或悬念画面，不用纯环境空镜开场；"
    "相邻镜头 shotSize 不重复；emotion 写成可见表演（眼神、呼吸、手部、身体距离），"
    "不只写形容词；末镜留下悬念、反转或未完成的动作；"
    "主体居中偏上，画面下方约四分之一留给字幕。"
    "5秒及以内的镜头 cameraMovement 只写一种运镜，不写“随后”“然后”接第二段运镜；"
    "跨空间动作把机位放在终点空间，visualDescription 与 cameraMovement 描述同一机位。"
)


def _script_prompt(
    target_duration_sec: int, *, mode: str = "guided", task: str = "script_outline"
) -> str:
    if target_duration_sec <= 30:
        scene_count, shot_min, shot_max = 2, 6, 6
    elif target_duration_sec <= 60:
        scene_count, shot_min, shot_max = 3, 8, 10
    else:
        scene_count, shot_min, shot_max = 4, 10, 12
    contract_prompt = SCRIPT_SYSTEM_PROMPT.replace("__MODE__", mode).replace("__TASK__", task)
    return (
        f"{contract_prompt}\n本次任务标识：mode={mode}，task={task}。必须原样返回这两个字段。\n"
        f"本次目标时长为 {target_duration_sec} 秒，必须生成恰好 {scene_count} 个 scenes，"
        f"以及 {shot_min} 到 {shot_max} 个 shots；所有 durationSec 之和必须等于 "
        f"{target_duration_sec} 秒，单镜头采用4到15秒的整数时长。"
        f"全片所有 dialogue 与 narration 合计尽量不超过 {int(target_duration_sec * 3.5)} "
        "个可发音字符，原对白优先保留，先删减旁白；"
        "故事正文多出的描写写入 visualDescription 和 action，不转成旁白。\n"
        + str(load_stage_skill(MANJU_SKILL, "script")["prompt"])
        + "\n输出前核对本次JSON契约：title为2到80字；shots为统一顶层content.shots数组，"
        "不要嵌套在scenes内。每个shot的id唯一，每个scene的id唯一；每个shot的id"
        "必须恰好出现在一个scene.shotIds中。若写sceneId，必须与所属scene.id一致。"
        "durationSec是正数，不附单位；characters是人名字符串数组，不是对象数组。"
        "dialogue和narration是字符串，不是对象或数组；无对白和旁白时两项都输出空字符串，"
        "不要为填满字段编造人声，也不要把环境声、音效或配乐写入narration；"
        "cameraMovement、visualStyle、soundscape、music均为非空中文字符串，"
        "不需要音乐写“无配乐”，不要输出null。只用前述字段名，不以actionDescription替代action。"
        "参考规则中的英文术语仅用于理解，剧本描述仍须为简体中文。"
    )


def _story_prompt(target_duration_sec: int) -> str:
    minimum = 300 if target_duration_sec <= 30 else 600 if target_duration_sec <= 60 else 900
    return (
        f"{STORY_TEXT_SYSTEM_PROMPT}\n"
        "本次任务标识：mode=automatic，task=story_expansion。必须原样返回这两个字段。\n"
        f"本次目标时长为 {target_duration_sec} 秒，content.text 必须至少 {minimum} 个中文字符，"
        "characters 必须是非空数组，每项包含 name 和 goal；"
        "beats 必须是数组且恰好按 setup、development、turn、ending 四项依次提供，"
        "每项包含 type 和完整的 text 段落。\n"
        + str(load_stage_skill(MANJU_SKILL, "story")["prompt"])
    )


STORY_TEXT_SYSTEM_PROMPT = (
    "你是短视频故事策划。根据用户输入，生成一段可直接交给编剧继续拆分的中文故事文本。"
    "只输出一个 JSON 对象，顶层格式必须是 "
    "{\"kind\":\"story_text\",\"version\":1,\"content\":{...}}。"
    "content 必须包含 title、logline、characters、setting、beats、text；"
    "characters 必须是数组，beats 必须是数组且顺序固定为 setup、development、turn、ending；"
    "不要 Markdown、解释或 <think> 内容。"
    "保留人物、目标、冲突、转折和结尾方向，按目标时长生成不少于 300/600/900 字的 text。"
    "这是竖屏短剧：开头直接进入异常或冲突，用可见动作和简短对白推进，"
    "少用心理独白和大段景物描写；结尾留下悬念或反转。"
    "正文用于阅读和拆分，不会整段作为旁白朗读。"
)


class BailianTextProvider:
    # OpenAI delta.content is incremental; repeated words are legitimate content.
    story_stream_is_delta = True

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = "qwen-plus",
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("BAILIAN_API_KEY_REQUIRED")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._transport = transport

    @staticmethod
    def _http_error_code(error: httpx.HTTPStatusError) -> str:
        status = error.response.status_code
        if status in (401, 403):
            return "PROVIDER_AUTH_FAILED"
        if status == 429:
            return "PROVIDER_RATE_LIMITED"
        if 400 <= status < 500:
            return "PROVIDER_REQUEST_INVALID"
        return "PROVIDER_HTTP_ERROR"

    async def compile_h3_prompt(self, system_prompt: str, input_text: str) -> JsonObject:
        """One text request for Skill execution; no automatic paid retries."""
        provider = self._copy(max_retries=0)
        try:
            return await provider._complete_json(
                system_prompt, input_text, h3_response=True, stage='h3_text',
            )
        except RuntimeError as error:
            if str(error) == 'PROVIDER_RESPONSE_INVALID' and not isinstance(error, H3ResponseError):
                raise H3ResponseError('h3_text', 'invalid_json') from error
            raise

    async def generate_character_prompt(self, context: JsonObject) -> JsonObject:
        skill = load_stage_skill(XIAOLUO_SKILL, "character-prompt")
        result = await self._complete_json_once(
            str(skill["prompt"]) + "\n\n" + character_prompt_system(context),
            json.dumps(context, ensure_ascii=False),
            stage='character_prompt',
        )
        return validate_character_prompt(
            result, purpose=context.get('purpose', 'full'),
            output_fields=context.get('outputFields'),
        )

    async def _complete_json_once(
        self, system_prompt: str, input_text: str, *, stage: str = 'text_request',
    ) -> JsonObject:
        provider = self._copy(max_retries=0)
        return await provider._complete_json(system_prompt, input_text, stage=stage)

    def _copy(self, *, max_retries: int) -> BailianTextProvider:
        return type(self)(
            api_key=self._api_key,
            base_url=self._base_url,
            model=self._model,
            timeout_seconds=self._timeout,
            max_retries=max_retries,
            transport=self._transport,
        )

    async def generate_story_text(
        self, story: str, project_id: str, target_duration_sec: int = 60
    ) -> str:
        del project_id
        system_prompt = _story_prompt(target_duration_sec)
        content = await self._copy(max_retries=0)._complete_text(system_prompt, story)
        if content.lstrip().startswith("{"):
            try:
                normalized = normalize_story_message(
                    self._routed(content, "story_text", "automatic", "story_expansion"),
                    target_duration_sec=target_duration_sec,
                )
                return str(normalized["text"])
            except RuntimeError as error:
                fallback = self._extract_story_text(content, target_duration_sec)
                if fallback:
                    return fallback
                raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error
        text = self._clean_text(content)
        if not text or len(text) > 8000:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        return text

    def _supports_streaming(self) -> bool:
        config = getattr(self._transport, 'config', {})
        body = config.get('request', {}).get('body', {})
        return (config.get('responseTextPath', 'choices[0].message.content')
                == 'choices[0].message.content'
                and not (isinstance(body, dict) and body.get('stream') is False))

    async def stream_story_text(
        self, story: str, project_id: str, target_duration_sec: int = 60,
    ) -> AsyncIterator[str]:
        if not self._supports_streaming():
            await report_text_progress({'type': 'phase', 'phase': 'buffered'})
            yield await self.generate_story_text(story, project_id, target_duration_sec)
            return
        async for delta in self._stream_completion(
            _story_prompt(target_duration_sec), story, stage='story_text',
        ):
            yield delta

    async def _stream_completion(
        self, system: str, user: str, *, stage: str,
    ) -> AsyncIterator[str]:
        payload = {'model': self._model, 'messages': [
            {'role': 'system', 'content': system}, {'role': 'user', 'content': user},
        ], 'stream': True, 'response_format': {'type': 'json_object'}}
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, headers={'Authorization': f'Bearer {self._api_key}'},
                timeout=self._timeout, transport=self._transport,
            ) as client:
                async with client.stream('POST', '/chat/completions', json=payload) as response:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as error:
                        raise await text_request_error(
                            response, self._http_error_code(error), stage=stage,
                        ) from error
                    # Some compatible gateways ignore stream. Consume this same response,
                    # never send a second request to discover/fall back between protocols.
                    if 'application/json' in response.headers.get('content-type', ''):
                        await response.aread()
                        body = response.json()
                        if stage == 'script_split':
                            self._parse_split_response(body)
                        yield self._content_text(body['choices'][0]['message']['content'])
                        return
                    completed = False
                    async for line in response.aiter_lines():
                        if not line.startswith('data:'):
                            continue
                        data = line[5:].strip()
                        if data == '[DONE]':
                            completed = True
                            break
                        chunk = json.loads(data)
                        if not isinstance(chunk, dict) or 'error' in chunk:
                            raise RuntimeError('PROVIDER_RESPONSE_INVALID')
                        choices = chunk.get('choices', [])
                        if not choices:  # Usage-only frames are not generated prose.
                            continue
                        choice = choices[0]
                        finish = choice.get('finish_reason')
                        if finish in {'length', 'content_filter'}:
                            if stage == 'script_split':
                                raise script_response_error(
                                    'output_truncated' if finish == 'length' else 'content_refused',
                                )
                            raise RuntimeError('PROVIDER_RESPONSE_INVALID')
                        if finish == 'stop':
                            completed = True
                        delta = choice.get('delta', {})
                        if delta.get('refusal'):
                            raise RuntimeError('PROVIDER_RESPONSE_INVALID')
                        content = delta.get('content')
                        if content is not None and not isinstance(content, str):
                            raise RuntimeError('PROVIDER_RESPONSE_INVALID')
                        if content:
                            yield content
                    if not completed:
                        raise RuntimeError('PROVIDER_RESPONSE_INVALID')
        except httpx.TimeoutException as error:
            raise text_timeout_error(
                'PROVIDER_TIMEOUT', stage=stage, timeout_ms=self._timeout * 1000,
            ) from error
        except httpx.HTTPError as error:
            raise TextRequestError('PROVIDER_HTTP_ERROR', {
                'stage': stage, 'reason': 'connection_error',
            }) from error
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise RuntimeError('PROVIDER_RESPONSE_INVALID') from error

    async def split_script(
        self, story_text: str, project_id: str, target_duration_sec: int = 60
    ) -> JsonObject:
        system_prompt = _script_prompt(
            target_duration_sec, mode="automatic", task="script_split"
        )
        parsed = await self._complete_json(system_prompt, story_text, stage='script_split')
        try:
            normalized = self._normalize_script(
                self._maybe_route(parsed, "script", "automatic", "script_split"),
                target_duration_sec=target_duration_sec,
            )
            self._validate_split_script(normalized, target_duration_sec=target_duration_sec)
        except RuntimeError as error:
            if str(error) == 'PROVIDER_SCRIPT_LANGUAGE_INVALID':
                raise
            if isinstance(error, ScriptContractError):
                raise script_response_error('script_contract_invalid', error=error) from error
            if str(error) == 'GENERATION_MODE_MISMATCH':
                raise script_response_error('script_contract_invalid', error=ScriptContractError(
                    'routing', 'envelope',
                )) from error
            raise script_response_error('script_contract_invalid') from error
        return normalized

    async def generate_script(
        self, story: str, project_id: str, target_duration_sec: int = 60
    ) -> JsonObject:
        del project_id
        system_prompt = _script_prompt(target_duration_sec)
        parsed = await self._complete_json(system_prompt, story)
        return self._normalize_script(
            self._maybe_route(parsed, "script", "guided", "script_outline"),
            target_duration_sec=target_duration_sec,
        )

    async def generate_guided_question(
        self,
        story: str,
        script: JsonObject,
        transcript: list[JsonObject],
        project_id: str,
        target_duration_sec: int = 60,
    ) -> JsonObject:
        del project_id, target_duration_sec
        round_number = len(transcript) + 1
        confirmed = [
            f"第 {index} 轮：{item.get('question', '')} → {item.get('answer', '')}"
            for index, item in enumerate(transcript, start=1)
            if isinstance(item, dict)
        ]
        prompt = (
            f"当前是第 {round_number} / 9 轮。任务标识：mode=guided，task=guided_question。\n"
            "故事："
            f"{story}\n"
            "当前剧本草稿："
            f"{json.dumps(script, ensure_ascii=False)}\n"
            "已确认信息："
            f"{'; '.join(confirmed) if confirmed else '暂无'}\n"
            "未解决信息：请从角色目标、核心冲突、关键转折、结尾情绪四个维度判断仍缺什么，"
            "不要把已经回答过的内容列为未解决。\n"
            "只输出 JSON："
            '{"kind":"guided_question","version":1,"mode":"guided",'
            '"task":"guided_question","content":{"question":"下一个最关键的问题，最多 80 字",'
            '"done":false}}。'
            '如果已能写出自洽的 30-90 秒短剧本，输出 '
            '{"kind":"guided_question","version":1,"mode":"guided",'
            '"task":"guided_question","content":{"question":"","done":true}}。'
        )
        result = await self._complete_json(
            "你是短视频编剧的剧情收束助手。你的任务是用尽可能少的问答补齐能影响成片的关键信息。\n"
            "每轮只问一个具体问题，问题不超过 80 个中文字符，用户应能用一两句话回答。\n"
            "优先顺序：角色目标与代价 → 核心冲突或对手 → 关键转折 → 结尾事件与结尾情绪；"
            "只有前述信息已明确时，才询问节奏、视角或其他约束。\n"
            "必须结合当前剧本和已确认信息提出高价值问题，不能重复、不能泛问‘还有什么补充’，"
            "也不要询问模型或制作技术细节。\n"
            "当信息已经足够、角色目标、冲突、转折和结尾已能支撑完整剧情时，"
            "立即返回 done=true 且 question 为空；"
            "即使信息仍不完整，也不得超过最多 9 轮。输出必须是合法 JSON，"
            "并且必须包含正确的 mode 和 task。",
            prompt,
        )
        if result.get("kind") == "guided_question":
            try:
                result = normalize_guided_question_message(
                    self._routed(result, "guided_question", "guided", "guided_question")
                )
            except RuntimeError as error:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error
        question = result.get("question")
        done = result.get("done")
        if not isinstance(question, str) or not isinstance(done, bool):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        question = question.strip()
        if done:
            return {"question": "", "done": True}
        if not question:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        return {"question": question[:80], "done": False}

    async def generate_detailed_script(
        self,
        story: str,
        script: JsonObject,
        transcript: list[JsonObject],
        project_id: str,
        target_duration_sec: int = 60,
    ) -> JsonObject:
        del project_id
        prompt = (
            "任务标识：mode=guided，task=script_detail。必须原样返回这两个字段。"
            "根据故事、剧本草稿和问答记录，输出详细剧本 JSON。"
            "必须保留所有已有镜头 id，并补充可执行的画面、动作、对白和旁白。\n"
            f"故事：{story}\n剧本草稿：{json.dumps(script, ensure_ascii=False)}\n"
            f"问答记录：{json.dumps(transcript, ensure_ascii=False)}"
        )
        return self._normalize_script(
            self._maybe_route(
                await self._complete_json(
                    _script_prompt(target_duration_sec, mode="guided", task="script_detail"),
                    prompt,
                ),
                "script",
                "guided",
                "script_detail",
            ),
            target_duration_sec=target_duration_sec,
        )

    async def _complete_json(
        self, system_prompt: str, user_prompt: str, *, h3_response: bool = False,
        stage: str = 'text_request',
    ) -> JsonObject:
        if stage == 'script_split' and text_progress.get() is not None:
            if self._supports_streaming():
                chunks: list[str] = []
                async for delta in self._stream_completion(system_prompt, user_prompt, stage=stage):
                    chunks.append(delta)
                    await report_text_progress({'type': 'delta', 'delta': delta})
                await report_text_progress({'type': 'phase', 'phase': 'validating'})
                return self._parse_split_response({'choices': [{'message': {
                    'content': ''.join(chunks),
                }}]})
            await report_text_progress({'type': 'phase', 'phase': 'buffered'})
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        # A split is one explicitly requested, potentially billed operation.
        # Legacy adapter retry settings must not silently resubmit it.
        retries = 0 if stage == 'script_split' else self._max_retries
        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=self._timeout,
                    transport=self._transport,
                ) as client:
                    response = await client.post("/chat/completions", json=payload)
                response.raise_for_status()
                try:
                    body = response.json()
                except ValueError as error:
                    if h3_response:
                        raise H3TextResponseError('invalid_envelope') from error
                    if stage == 'script_split':
                        raise script_response_error('invalid_envelope') from error
                    raise
                if h3_response:
                    return self._parse_h3_json_response(body)
                if stage == 'script_split':
                    return self._parse_split_response(body)
                return self._parse_json_response(body)
            except httpx.TimeoutException as error:
                if attempt >= retries:
                    failure = text_timeout_error(
                        "PROVIDER_TIMEOUT", stage=stage, timeout_ms=self._timeout * 1000,
                    )
                    if stage in {'script_split', 'character_prompt'}:
                        failure.detail['timeoutPhase'] = (
                            'connect' if isinstance(error, httpx.ConnectTimeout)
                            else 'read' if isinstance(error, httpx.ReadTimeout)
                            else 'write' if isinstance(error, httpx.WriteTimeout)
                            else 'pool' if isinstance(error, httpx.PoolTimeout)
                            else 'unknown'
                        )
                        logging.getLogger(__name__).warning(
                            "text_request_failure stage=%s reason=timeout "
                            "timeout_ms=%s phase=%s attempts=1",
                            stage, failure.detail['timeoutMs'], failure.detail['timeoutPhase'],
                        )
                    raise failure from error
            except httpx.HTTPStatusError as error:
                if attempt >= retries or error.response.status_code < 500:
                    raise await text_request_error(
                        error.response, self._http_error_code(error), stage=stage,
                    ) from error
            except httpx.HTTPError as error:
                if stage in {'script_split', 'character_prompt'}:
                    raise TextRequestError('PROVIDER_HTTP_ERROR', {
                        'stage': stage, 'reason': 'connection_error',
                    }) from error
                if h3_response:
                    raise TextRequestError('PROVIDER_HTTP_ERROR', {
                        'stage': 'h3_text', 'reason': 'connection_error',
                    }) from error
                raise RuntimeError('PROVIDER_RESPONSE_INVALID') from error
            except (
                ValueError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
            ) as error:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error
        raise RuntimeError("PROVIDER_REQUEST_FAILED")

    @staticmethod
    def _routed(body: object, kind: str, mode: str, task: str) -> JsonObject:
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError as error:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error
        if not isinstance(body, dict):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        routed = dict(body)
        routed.setdefault("kind", kind)
        routed.setdefault("version", 1)
        routed.setdefault("mode", mode)
        routed.setdefault("task", task)
        if "content" not in routed:
            routed["content"] = {
                key: value
                for key, value in routed.items()
                if key not in {"kind", "version", "mode", "task"}
            }
        return normalize_generation_message(
            routed,
            expected_kind=kind,
            expected_mode=mode,
            expected_task=task,
        )

    @staticmethod
    def _maybe_route(body: JsonObject, kind: str, mode: str, task: str) -> JsonObject:
        if any(key in body for key in ("mode", "task")):
            return BailianTextProvider._routed(body, kind, mode, task)
        return body

    async def _complete_text(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=self._timeout,
                    transport=self._transport,
                ) as client:
                    response = await client.post("/chat/completions", json=payload)
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("response is not an object")
                content = body["choices"][0]["message"]["content"]
                return self._content_text(content)
            except httpx.TimeoutException as error:
                if attempt >= self._max_retries:
                    raise RuntimeError("PROVIDER_TIMEOUT") from error
            except httpx.HTTPStatusError as error:
                if attempt >= self._max_retries or error.response.status_code < 500:
                    raise RuntimeError(self._http_error_code(error)) from error
            except (
                httpx.HTTPError,
                ValueError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
            ) as error:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error
        raise RuntimeError("PROVIDER_REQUEST_FAILED")

    async def check_connectivity(self) -> str:
        """Confirm the credential and endpoint work, and return the replying model.

        This is deliberately not a generation call. It asks for a single token and
        applies no content contract, so it answers exactly one question: can we
        reach the provider with this key. Routing it through ``generate_script``
        instead made a healthy provider look unreachable, because the model's
        reply was judged against the full script contract and a minimal-but-legal
        reply was rejected.
        """
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get("choices"), list):
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            replying_model = body.get("model")
            return replying_model if isinstance(replying_model, str) else self._model
        except httpx.TimeoutException as error:
            raise text_timeout_error(
                "PROVIDER_TIMEOUT", stage="text_check", timeout_ms=self._timeout * 1000,
            ) from error
        except httpx.HTTPStatusError as error:
            raise await text_request_error(
                error.response, self._http_error_code(error), stage='text_check',
            ) from error
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error

    @staticmethod
    def _clean_text(content: str) -> str:
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    @staticmethod
    def _extract_story_text(content: str, target_duration_sec: int) -> str | None:
        try:
            parsed = BailianTextProvider._decode_json(content)
        except ValueError:
            return None
        nested = parsed.get("content")
        text = nested.get("text") if isinstance(nested, dict) else parsed.get("text")
        if isinstance(text, str) and 0 < len(text.strip()) <= 8000:
            return text.strip()
        return None

    @staticmethod
    def _parse_response(body: object) -> JsonObject:
        parsed = BailianTextProvider._parse_json_response(body)
        return BailianTextProvider._normalize_script(parsed)

    @staticmethod
    def _parse_h3_json_response(body: object) -> JsonObject:
        choices = body.get('choices') if isinstance(body, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(
            choices[0], dict
        ) or not isinstance(choices[0].get('message'), dict):
            raise H3TextResponseError('message_missing')
        message = choices[0]['message']
        finish = choices[0].get('finish_reason')
        content = message.get('content')
        try:
            text = BailianTextProvider._content_text(content)
            text_content = True
        except ValueError:
            text = ''
            text_content = content is None or content == []

        def failure(reason: ResponseReason) -> H3TextResponseError:
            return H3TextResponseError(reason, finish_reason=finish, content_characters=len(text))

        if finish == 'length':
            raise failure('output_truncated')
        if finish == 'content_filter' or message.get('refusal'):
            raise failure('content_refused')
        if not text.strip():
            if not text_content:
                raise failure('content_not_text')
            reasoning = message.get('reasoning_content')
            reason: ResponseReason = (
                'reasoning_only' if isinstance(reasoning, str) and reasoning.strip() else
                'empty_content'
            )
            raise failure(reason)
        try:
            return BailianTextProvider._parse_json_response(body)
        except RuntimeError as error:
            raise failure('invalid_json') from error

    @staticmethod
    def _parse_split_response(body: object) -> JsonObject:
        choices = body.get('choices') if isinstance(body, dict) else None
        if (not isinstance(choices, list) or not choices or not isinstance(choices[0], dict)
                or not isinstance(choices[0].get('message'), dict)):
            raise script_response_error('message_missing')
        choice = choices[0]
        message = choice['message']
        if choice.get('finish_reason') == 'length':
            raise script_response_error('output_truncated')
        if choice.get('finish_reason') == 'content_filter' or message.get('refusal'):
            raise script_response_error('content_refused')
        content = message.get('content')
        try:
            text = BailianTextProvider._content_text(content)
        except ValueError:
            if content is not None and content != []:
                raise script_response_error('content_not_text') from None
            text = ''
        if not text.strip():
            reasoning = message.get('reasoning_content')
            raise script_response_error(
                'reasoning_only' if isinstance(reasoning, str) and reasoning.strip()
                else 'empty_content'
            )
        try:
            return BailianTextProvider._decode_json(text)
        except ValueError as error:
            raise script_response_error('invalid_json') from error

    @staticmethod
    def _parse_json_response(body: object) -> JsonObject:
        if not isinstance(body, dict):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        try:
            content = body["choices"][0]["message"]["content"]
            content_text = BailianTextProvider._content_text(content)
            parsed = BailianTextProvider._decode_json(content_text)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error
        if not isinstance(parsed, dict):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        return parsed

    @staticmethod
    def _content_text(content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    value = item.get("text") or item.get("content")
                    if isinstance(value, str):
                        parts.append(value)
            if parts:
                return "".join(parts)
        raise ValueError("content is not text")

    @staticmethod
    def _decode_json(content: str) -> JsonObject:
        cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        decoder = json.JSONDecoder()
        for offset, character in enumerate(cleaned):
            if character != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(cleaned[offset:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise ValueError("no JSON object in provider response")

    @staticmethod
    def _normalize_script(parsed: JsonObject, *, target_duration_sec: int = 60) -> JsonObject:
        BailianTextProvider._validate_script_language(parsed.get("content", parsed))
        if parsed.get("kind") == "script" and isinstance(parsed.get("content"), dict):
            return normalize_script_message(parsed, target_duration_sec=target_duration_sec)
        title = parsed.get("title") or parsed.get("name")
        raw_scenes = parsed.get("scenes")
        raw_shots = parsed.get("shots")
        if not isinstance(title, str) or not isinstance(raw_scenes, list):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        if raw_scenes == [] and raw_shots == []:
            return {"title": title, "scenes": [], "shots": []}

        nested_shots: list[object] = []
        scenes: list[JsonObject] = []
        for scene_index, raw_scene in enumerate(raw_scenes, start=1):
            if not isinstance(raw_scene, dict):
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            scene_id = str(raw_scene.get("id") or raw_scene.get("scene_id") or scene_index)
            scene_title = raw_scene.get("title") or raw_scene.get("name")
            if not isinstance(scene_title, str) or not scene_title:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            scene_shots = raw_scene.get("shots")
            if isinstance(scene_shots, list):
                nested_shots.extend(scene_shots)
            scene_record: JsonObject = {
                "id": f"scene-{scene_id}",
                "title": scene_title,
                "shotIds": [],
            }
            for field in ("time", "location", "narrativeGoal", "conflict", "turningPoint",
                          "lighting", "weather"):
                value = raw_scene.get(field)
                if isinstance(value, str) and value.strip():
                    scene_record[field] = value.strip()
            scenes.append(scene_record)

        source_shots = raw_shots if isinstance(raw_shots, list) and raw_shots else nested_shots
        if not isinstance(source_shots, list) or not source_shots:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        shots: list[JsonObject] = []
        scene_ids: dict[str, JsonObject] = {}
        for index, (scene, raw_scene) in enumerate(zip(scenes, raw_scenes, strict=True), start=1):
            source_id = raw_scene.get("id") or raw_scene.get("scene_id") or index
            scene_ids[str(source_id)] = scene
        has_explicit_scene_refs = False
        for order, raw_shot in enumerate(source_shots, start=1):
            if not isinstance(raw_shot, dict):
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            shot_id = str(raw_shot.get("id") or raw_shot.get("shot_id") or f"shot-{order}")
            duration = raw_shot.get("durationSec", raw_shot.get("duration"))
            duration = BailianTextProvider._duration_seconds(duration)
            if duration is None:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            description = raw_shot.get("visualDescription") or raw_shot.get("description")
            shot_size = (
                raw_shot.get("shotSize") or raw_shot.get("shot_size") or raw_shot.get("shot_type")
            )
            action = (
                raw_shot.get("action") or raw_shot.get("camera_movement") or raw_shot.get("camera")
            )
            audio = raw_shot.get("audio")
            dialogue = BailianTextProvider._dialogue_value(raw_shot)
            narration = raw_shot.get("narration")
            if isinstance(audio, dict):
                dialogue = dialogue or BailianTextProvider._dialogue_value(audio)
                narration = narration or audio.get("narration") or audio.get("voiceover")
            elif narration is None:
                narration = audio
            if not all(
                isinstance(value, str) and value for value in (description, shot_size, action)
            ):
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            dialogue = BailianTextProvider._text_value(dialogue)
            narration = BailianTextProvider._text_value(narration)
            # Preserve the legacy audio.dialogue=[] spelling of explicit silence.
            explicit_silence = valid_speech_fields(raw_shot) or (
                isinstance(audio, dict) and audio.get('dialogue') == []
            )
            if not (dialogue.strip() or narration.strip()) and not explicit_silence:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            normalized_shot = {
                "id": shot_id,
                "order": order,
                "title": str(raw_shot.get("title") or description),
                "action": action,
                "emotion": str(raw_shot.get("emotion") or "平静"),
                "shotSize": shot_size,
                "durationSec": duration,
                "visualDescription": description,
                "dialogue": dialogue,
                "narration": narration,
                "characters": raw_shot.get("characters", []),
                "characterIds": raw_shot.get("characterIds", []),
                "cameraMovement": str(raw_shot.get("cameraMovement") or "固定镜头"),
                "visualStyle": str(
                    raw_shot.get("visualStyle") or "统一漫画风格，色彩和线条保持连续"
                ),
                "soundscape": str(raw_shot.get("soundscape") or "安静的环境声"),
                "music": str(raw_shot.get("music") or "克制的背景音乐，无突兀变化"),
                "generationMode": str(raw_shot.get("generationMode") or "t2va").lower(),
            }
            if normalized_shot["generationMode"] not in {"t2va", "i2va", "fl2va", "l2va", "ref2va"}:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            shots.append(normalized_shot)
            source_scene_id = raw_shot.get("scene_id") or raw_shot.get("sceneId")
            if source_scene_id is not None and str(source_scene_id) in scene_ids:
                has_explicit_scene_refs = True
                scene_ids[str(source_scene_id)]["shotIds"].append(shot_id)

        if len(scenes) == 1:
            scenes[0]["shotIds"] = [shot["id"] for shot in shots]
        elif not has_explicit_scene_refs:
            offset = 0
            for scene, raw_scene in zip(scenes, raw_scenes, strict=True):
                count = (
                    len(raw_scene.get("shots", []))
                    if isinstance(raw_scene, dict) and isinstance(raw_scene.get("shots"), list)
                    else 0
                )
                scene["shotIds"] = [shot["id"] for shot in shots[offset : offset + count]]
                offset += count
            if offset < len(shots):
                scenes[-1]["shotIds"].extend(shot["id"] for shot in shots[offset:])
        return {"title": title, "scenes": scenes, "shots": shots}

    @staticmethod
    def _validate_script_language(content: object) -> None:
        """Validate generated prose only; never reinterpret a user's saved text."""
        fields = {
            "action", "emotion", "visualDescription", "description", "cameraMovement",
            "visualStyle", "soundscape", "music", "time", "location", "narrativeGoal",
            "conflict", "turningPoint",
        }
        if isinstance(content, list):
            for item in content:
                BailianTextProvider._validate_script_language(item)
        elif isinstance(content, dict):
            for key, value in content.items():
                if key in fields and isinstance(value, str) and value.strip():
                    if (
                        not re.search(r"[\u3400-\u9fff]", value)
                        or len(re.findall(r'[A-Za-z]', value)) > max(
                            12, 2 * len(re.findall(r'[\u3400-\u9fff]', value))
                        )
                        or "\ufffd" in value
                        or re.search(r"\\u[0-9a-fA-F]{4}", value)
                    ):
                        raise RuntimeError("PROVIDER_SCRIPT_LANGUAGE_INVALID")
                elif isinstance(value, (dict, list)):
                    BailianTextProvider._validate_script_language(value)

    @staticmethod
    def _duration_seconds(value: object) -> int | float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return value if value > 0 else None
        if isinstance(value, str):
            match = re.search(r"\d+(?:\.\d+)?", value)
            if match:
                parsed = float(match.group())
                return int(parsed) if parsed.is_integer() else parsed
        return None

    @staticmethod
    def _validate_split_script(script: JsonObject, *, target_duration_sec: int) -> None:
        shots = script.get("shots")
        scenes = script.get("scenes")
        if not isinstance(shots, list) or not isinstance(scenes, list) or not shots:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        shot_ids = {str(shot.get("id")) for shot in shots if isinstance(shot, dict)}
        referenced = {
            str(shot_id)
            for scene in scenes
            if isinstance(scene, dict)
            for shot_id in scene.get("shotIds", [])
        }
        if referenced != shot_ids or any(
            not isinstance(shot, dict)
            or not valid_speech_fields(shot)
            for shot in shots
        ):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        expected_min = 6 if target_duration_sec <= 30 else 8 if target_duration_sec <= 60 else 10
        if len(shots) < expected_min:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        # Match the preview/editor contract: descriptive context is optional.
        # Validate supplied values without rejecting absent or empty metadata.
        context_fields = ("time", "location", "narrativeGoal", "conflict", "turningPoint")
        for index, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                raise ScriptContractError('object_required', f'scenes[{index}]')
            for field in context_fields:
                if scene.get(field) is not None and not isinstance(scene[field], str):
                    raise ScriptContractError('text_type', f'scenes[{index}].{field}')

    @staticmethod
    def _text_value(value: object) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = [item for item in value if isinstance(item, str)]
            return "\n".join(parts)
        return ""

    @staticmethod
    def _dialogue_value(source: dict[str, object]) -> str:
        """Accept the field names commonly emitted by Chinese script models."""
        for key in ("dialogue", "dialogues", "dialogueLines", "对白", "台词", "lines"):
            if key in source:
                value = source[key]
                if isinstance(value, list):
                    lines: list[str] = []
                    for item in value:
                        if isinstance(item, dict):
                            text = BailianTextProvider._text_value(
                                item.get("text") or item.get("content") or item.get("dialogue")
                            )
                            speaker = BailianTextProvider._text_value(
                                item.get("speaker") or item.get("character") or item.get("角色")
                            )
                            if text:
                                lines.append(f"{speaker}：{text}" if speaker else text)
                        elif isinstance(item, str) and item.strip():
                            lines.append(item.strip())
                    return "\n".join(lines)
                return BailianTextProvider._text_value(value)
        return ""
