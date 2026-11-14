import type { VisualPreflight } from '../../types'
import { preflightError } from '../../visual-preflight'
import { TechDetails } from '../../components/TechDetails'

const roles: Record<string, string> = { first_frame: '严格首帧', last_frame: '严格尾帧', reference_image: '普通参考图' }
const views: Record<string, string> = { 'reference-board': '人物三视图整板', main: '人物主参考图',
  front: '人物正面', 'three-quarter': '人物四分之三侧面', profile: '人物侧面',
  'scene-anchor': '场景参考', 'continuity-anchor': '上一镜头尾帧连续性参考' }

export function VisualPreparation({ data }: { data: VisualPreflight }) {
  const params = data.parameters
  return <div className="visual-preparation">
    <p className="preflight-status" role="status">{data.ready ? '本地准备检查通过' : '请先补齐生成条件'}</p>
    {data.errors.map(code => <p role="alert" key={code}>{preflightError(code)}</p>)}
    <dl>
      <dt>视频模型</dt><dd>{data.model ?? '未知'}</dd>
      <dt>分辨率</dt><dd>{String(params.resolution ?? params.size ?? '未提供')}</dd>
      <dt>画幅</dt><dd>{String(params.ratio ?? (data.mode === 'i2v' ? '随首帧' : '未提供'))}</dd>
      <dt>时长</dt><dd>{params.duration ? `${params.duration} 秒` : '未提供'}</dd>
      <dt>项目风格</dt><dd>{data.style ? data.style.name : '未统一设置'}</dd>
    </dl>
    <h3>参考素材 · {data.references.length} 张</h3>
    {data.references.length === 0 ? <p>没有传入图片参考。</p> : <ol className="preflight-references">
      {data.references.map((ref, index) => <li key={`${ref.sourceId}-${index}`}>
        <strong>{ref.label} · {ref.name || views[ref.view ?? ''] || '图片'}</strong>
        <span>{roles[ref.role] ?? ref.role}{ref.view ? ` / ${views[ref.view] ?? ref.view}` : ''}</span>
        {ref.fileState !== 'exists' && <small>{ref.fileState === 'unchecked' ? '文件尚未核验' : '文件不可用'}</small>}
      </li>)}
    </ol>}
    {data.speechReview && <p className="preflight-warning">
      对白 {data.speechReview.spokenCharacterCount} 字 · 旁白 {data.speechReview.narrationCharacterCount} 字 ·
      预计语音约 {data.speechReview.estimatedSpeechSec} 秒 / 镜头 {data.speechReview.durationSec} 秒
    </p>}
    <details><summary>动作与准确台词</summary>
      {data.camera && <>
        <p>机位与空间：{data.camera.visualDescription || '未单独填写'}</p>
        <p>运镜：{data.camera.cameraMovement || '未单独填写'}</p>
      </>}
      {(['actionBefore', 'actionMiddle', 'actionAfter'] as const).map((key, i) => <p key={key}>
        {['开始', '发展', '完成'][i]}：{data.actionStates?.[key] || '未单独填写'}
      </p>)}
      <p>对白：{data.speech?.dialogue || '无'}</p>
      <p>旁白：{data.speech?.narration || '无'}</p>
    </details>
    {data.prompt && <details><summary>{data.prompt.kind === 'expansion-input' ? '查看扩写输入' : '查看提交提示词'}</summary>
      <pre>{data.prompt.text}</pre>
    </details>}
    {data.warnings.map(warning => <p className="preflight-warning" key={warning}>{warning}</p>)}
    <p className="preflight-calls">预计调用：{data.calls ? `文本 ${data.calls.text} 次 · 视频 ${data.calls.video} 次` : '未知'}</p>
    <TechDetails>
      <dl>
        <dt>配置版本</dt><dd>{data.modelConfigRevision ?? '—'}</dd>
        {params.width && params.height ? <><dt>输出像素</dt><dd>{String(params.width)} × {String(params.height)}</dd></> : null}
        <dt>生成模式</dt><dd>{data.mode ?? '未提供'}</dd>
        {data.style && <><dt>风格版本</dt><dd>v{data.style.revision}</dd></>}
      </dl>
      {data.references.length > 0 && <p>参考素材编号：{data.references.map(ref => ref.sourceId).join('、')}</p>}
      {data.prompt && <p>提示词处理：{data.prompt.kind === 'expansion-input' ? `H3 Skill 规则 → 文本扩写（${data.textModel ?? '未知模型'}）→ 校验 → 视频模型。以下是扩写输入，尚未调用文本模型。` : data.prompt.platformOptimization ? '本地中文编译 → 优云 Context-IR 优化 → 视频模型。平台优化后的内部提示词不可见。' : '本地提示词 → 视频模型。'}链接和图片数据会隐藏。</p>}
      {data.prompt?.system && <details><summary>查看实际 Skill 与系统规则</summary><pre>{data.prompt.system}</pre></details>}
      {data.speechReview && <p>语音时长按每秒 5 字粗估，未计停顿，不代表实际音轨时长。</p>}
      <p>供应商费用以实际计费为准，查询和下载不计入调用次数。准备检查不调用生成模型，也不能证明实际画质或供应商额度充足。</p>
    </TechDetails>
  </div>
}
