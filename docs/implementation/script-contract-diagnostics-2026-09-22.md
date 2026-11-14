# 剧本拆分契约失败核查

本次真实请求日志仅保留script_contract_invalid，无原始响应，不能还原具体字段，也不能证明与上一轮场景说明问题同因。不重发付费请求。

本批范围：消除拆分系统提示词中guided/script_outline与automatic/script_split的冲突；为现有契约校验补充规则、字段路径、数量等安全诊断，并让预览API和页面展示这些诊断。保持镜头/场景规模、对白要求、引用完整性等现有规则，不靠放宽校验、填补剧情或自动重试掩盖失败。保留当前模型、输出预算、Skill和故事。

输入为既有文本响应；输出成功时仍为原Script，失败时仍为502/PROVIDER_INVALID_RESPONSE，新增validation详情。路径由代码字段名和数组下标构造，不记录角色名、模型正文、上游任意值或Key。预览失败不写项目、不生成图片或视频。

验证从真实Adapter→假HTTP→预览API接线开始：一致的出站任务标识；缺字段、类型、数量、重复ID、引用、声音等失败能区分；只调用一次、故事不变、不泄露内容。前端验证可读文案及未知诊断安全回退，随后进行后端与构建回归。真实输出质量留待用户验证，不把合成测试当作该次原响应重放。

初始RED：新增17项全部失败，包含两种Adapter接线的提示词冲突和15种诊断缺失。命令：`.venv/Scripts/python.exe -m pytest backend/tests/test_script_preview_response_validation.py -k 'consistent_routing or identifies_safe_field' -q --tb=short`，运行环境memory/mock，所有文本HTTP均MockTransport。

固定任务顺序不变，本批仅处理用户验证阻断；不提交、推送、迁移或部署。
