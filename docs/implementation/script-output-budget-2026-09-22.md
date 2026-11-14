# 剧本拆分输出预算调整

本次用户重试后，日志明确记录 `script_response_failure reason=output_truncated`，预览返回502；后续另有一次504。与前一次无法还原的通用502不同，本次已确认模型输出被截断，不再将其归因于可选场景说明。

用户已自行把剧本拆分绑定切换为 `deepseek-v4-flash-ga-260731`（doubao-chat），模型库revision32。该模型仅用于script，自定义请求body未设置max_tokens，timeoutMs为120000。

依据火山方舟[Chat API文档](https://docs.volcengine.com/docs/ark/chat-api?lang=zh)和[模型列表](https://docs.volcengine.com/docs/ark/model-list?lang=zh)，当前Flash默认回答上限为4K token。通过已有模型库API保留原配置，只增加 `request.body.max_tokens: 16384`，将 `timeoutMs` 改为300000，保存至revision33。模型、绑定、Key、故事、目标时长和提示词不变，不新增自动重试，不修改thinking或response_format。

这是回答长度上限，不是固定消耗；实际计费按供应商用量规则。300秒为请求读取等待配置，不保证供应商必定在该时间内成功返回。其他用途模型配置不受本次调整影响。

## 验证与边界

先用原配置经真实TemplateTextProvider/TemplateTransport和MockTransport断言，确认出站请求缺max_tokens；提议配置和保存后的配置均通过：max_tokens=16384、read timeout=300秒、模型不变、单次假调用，合成60秒/3场景/8镜剧本可解析。进程阻断真实供应商网络，真实模型调用0。

最终只读核查模型库revision33及两个参数已生效，API health=ok。无需重启，本次没有业务代码修改。项目prj_f9f6e04d5dd7故事仍保留，不保存失败拆分结果。用户下一次点击拆分才会发起新的真实请求；离线验证不代表真实生成已成功。

私有证据位于 `var/verification/script-output-budget-20260922/`：config-before.json、config-proposed.json、config-after.json、verify_budget.py、before-check.txt、proposed-check.txt和saved-check.txt。目录受Git忽略，不上传。备份仅含该模型配置和绑定，不含API Key。目录中的HTTP下载文档为SPA壳；参数依据来自浏览器读取的官方正文。

如需回退，读取当前模型库revision，使用已有更新API仅恢复config-before.json中该模型的config；不要回滚整个模型库或覆盖用户后续修改。未提交、推送、部署或迁移；固定任务顺序不变。
