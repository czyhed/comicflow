"""Versioned project style snapshots and deterministic instructions for each stage."""
from copy import deepcopy
from typing import Literal

from comicflow.domain.errors import DomainError
from comicflow.domain.models import JsonObject

StyleStage = Literal['script', 'character-prompt', 'character-reference',
                     'character-reference-view', 'character-reference-board',
                     'character-reference-text-board',
                     'scene-background', 'video']

# Content provenance: docs/research/h3-prompt-source-register-2026-09-22.md.
# Live-action additions: docs/research/youmind-style-reference-2026-09-23.md.
# Wuxia film study: docs/implementation/wuxia-film-style-2026-09-24.md.
# New projects capture v2; saved profiles continue supplying their own rules.
_PRESET_REVISION = 2

_PRESETS: tuple[JsonObject, ...] = (
    {'presetId': 'cinematic-realism', 'name': '真人电影写实', 'medium': 'live-action',
     'thumbnail': '/style-previews/cinematic-realism.jpg',
     'description': '自然肤质、真实材质与克制的摄影光影。',
     'rendering': '真人电影摄影，自然人体比例、细腻肤质与发丝，布料和金属反光符合材质。'
                  '按已有服饰区分织物纹理、皮革柔光与金属小面积高光，不用统一油亮反光覆盖皮肤和衣料。',
     'lighting': '保留明暗层次，光源方向和色温明确，高光不过曝，色彩克制。',
     'motion': '动作有自然重量和惯性，人物外貌与服装纹理随运动稳定。',
     'avoid': '避免塑料肤质、过度磨皮、过度锐化、卡通线稿和电子游戏渲染感。'},
    {'presetId': 'guofeng-3d', 'name': '国风三维动画', 'medium': 'animation-3d',
     'description': '三维角色体积、精细服饰与统一动画材质。',
     'rendering': '国风三维动画，角色轮廓和体积清楚，发束层次、布料褶皱和装饰建模细致。'
                  '面部转折柔和，皮肤、发束、织物和已有饰件的粗糙度有区别，不强加真人毛孔。',
     'lighting': '柔和体积光与受控高光，接触阴影稳定，各物件使用统一三维材质语言。',
     'motion': '三维动画表演连贯，关节转动自然，服装运动保留体积，避免纹理闪烁。',
     'avoid': '避免低多边形粗糙轮廓、蜡像质感、真人照片与二维平涂混搭。'},
    {'presetId': 'anime-2d', 'name': '日系二维动画', 'medium': 'animation-2d',
     'description': '稳定线稿、赛璐璐阴影与干净色块。',
     'rendering': '日系二维动画，线稿粗细稳定，赛璐璐分区阴影，发束和衣褶用清晰线面表达。'
                  '材质差异用线条疏密、色块与少量高光概括，五官和服装边界清楚，不堆叠摄影微纹理。',
     'lighting': '色块边缘干净、亮暗层次明确，背景透视与人物采用统一二维上色。',
     'motion': '二维角色轮廓和五官稳定，动作节奏自然，避免线条抖动和色块闪烁。',
     'avoid': '避免真人毛孔、照片纹理、三维塑料高光和突然切换画风。'},
    {'presetId': 'guofeng-painted', 'name': '国风厚涂', 'medium': 'painted',
     'description': '细腻笔触、层叠色彩与绘画式体积。',
     'rendering': '国风厚涂插画，以有控制的笔触和色面塑造体积，衣料与环境保留绘画层次。'
                  '五官和服装结构处收紧边缘，远景边缘适度概括，材质依靠笔触方向和色面变化区分。',
     'lighting': '冷暖色面组织光影，焦点处细腻、非焦点处适度概括，避免颜色混浊。',
     'motion': '笔触质感随物体稳定移动，人物脸型与服饰不漂移，动作连贯。',
     'avoid': '避免照片贴图、僵硬三维高光、脏色堆积、笔触闪烁和细节糊成一片。'},
    {'presetId': 'ink-animation', 'name': '水墨动画', 'medium': 'ink',
     'description': '墨色浓淡、留白和可辨识的笔触。',
     'rendering': '水墨动画，以墨色浓淡、干湿笔触和留白塑造形体，关键五官与衣饰轮廓清楚。'
                  '面部辨识点与动作接触处保留清晰墨线，晕染用于次要区域，不用浓墨抹去手脚和道具关系。',
     'lighting': '用墨阶和少量设色表现层次，空间可读，人物轮廓与背景适度分离。',
     'motion': '墨迹随形体运动，保留身份与动作轮廓，墨色变化不能吞没五官。',
     'avoid': '避免摄影反光、荧光饱和色、塑料材质和整屏墨团遮挡动作。'},
    {'presetId': 'graphic-comic', 'name': '美式漫画', 'medium': 'graphic',
     'description': '明确轮廓、图形化阴影与鲜明对比。',
     'rendering': '美式漫画，轮廓线有力度，结构明确，图形化阴影和有节制的网点表现。'
                  '人物剪影与背景分离，线重服务形体转折，网点密度稳定，不遮住五官和手部动作。',
     'lighting': '主色分区清晰，黑白明暗构成有层次，保持跨镜头线条与色彩一致。',
     'motion': '人物体积与轮廓稳定，动作有明确起止，不插入漫画分格或气泡。',
     'avoid': '避免照片质感、随机网点闪烁、文字气泡、分格边框和人物比例漂移。'},
    {'presetId': 'documentary-dv', 'name': '真人纪实 DV', 'medium': 'live-action',
     'description': '自然生活感、轻微数码颗粒与克制的手持记录。',
     'rendering': '真人纪实影像，自然人体比例、真实肤质和日常衣料，细节略柔和，'
                  '少量数码颗粒不过度覆盖面部和服装辨识点，不做商业美颜或三维渲染。',
     'lighting': '保留原场景光源与色温，曝光自然，暗部仍可辨识，角色参考图采用均匀清晰布光。',
     'motion': '生活化表演与轻微手持呼吸感；仅在原稿允许时自然跟随人物，'
               '不强加抖动、失焦、突然变焦或蒙太奇。遵守本镜头时长、动作、对白和声音安排。',
     'avoid': '避免过度磨皮、塑料肤质、夸张景深、严重失焦、时间戳和摄影机界面叠字。'},
    {'presetId': 'suspense-realism', 'name': '克制悬疑摄影', 'medium': 'live-action',
     'description': '真实空间、明暗分区与有留白的紧张感。',
     'rendering': '真人电影摄影，用前中后景、遮挡关系和可读的空间纵深组织紧张感，'
                  '人物皮肤、衣料和已有道具材质真实，关键五官与动作接触点清楚。',
     'lighting': '以原有光源组织受控的明暗分区，暗部保留层次；不把白天强改成夜景，'
                 '不凭空添加闪灯、烟雾或天气。角色设定图仍用中性均匀光。',
     'motion': '沿原稿安排视线、停顿、反应和空间揭示，保持动作方向与机位关系可读，'
               '不自动添加惊吓、追逐、攻击、怪物或血腥情节。',
     'avoid': '避免整片死黑、无动机闪烁、任意镜头抖动和遮挡关键动作。'},
    {'presetId': 'cinematic-color-contrast', 'name': '电影色彩对比', 'medium': 'live-action',
     'description': '克制背景与主体色彩层次，突出人物和空间关系。',
     'rendering': '真人电影摄影，以已有服装与环境的色相、饱和度和明度关系突出叙事主体，'
                  '背景色彩克制，保留真实皮肤、布料纹理和空间层次，不强制红衣或改换服装配色。',
     'lighting': '光源方向和色温遵循原场景，肤色自然，高光受控，'
                 '用主体与背景的明暗分离建立视觉焦点，不整屏套同色滤镜。',
     'motion': '运动中保持人物轮廓、服装颜色与视觉焦点稳定；运镜服从原镜头，'
               '只在已有动作与时间允许时逐步揭示环境，不强加人群或拉远镜头。',
     'avoid': '避免色彩溢出、皮肤偏色、自动黑白化、过曝光晕和随帧变色。'},
    {'presetId': 'hong-kong-wuxia-film', 'name': '港风武侠胶片', 'medium': 'live-action',
     'description': '九十年代香港武侠银幕感，青灰低饱和、柔和逆光与35mm颗粒。',
     'rendering': '九十年代香港奇幻武侠电影胶片感，35mm适量颗粒、轻微光学柔化，'
                  '保留真实皮肤、天然发丝及原有布料、皮革、铁银器的材质差异。'
                  '低饱和青灰、冷黑与灰褐为环境底色，保留角色既定发色与服装配色；'
                  '仅以原稿已有暖色作小面积点色，不凭空加红灯或金发。'
                  '全身构图时双手、鞋履与已有兵器完整入画，握持、接触和重量关系清楚。',
     'lighting': '场景遵循原有时间、天气和光源，条件允许时用漫射光与柔和逆光，'
                 '黑位略抬、反差克制，少量高光溢出不遮五官；角色设定图优先中性均匀光。',
     'motion': '动作有重量、控制力与清楚的起止，兵器形制和双手握持关系随运动稳定；'
               '颗粒与轻微晕染不遮动作，不强加打斗、风雨或特效。',
     'avoid': '避免橙黄滤镜、蓝紫霓虹、HDR、过度锐化、塑料皮肤、现代偶像妆和游戏CG。'
              '人类角色不因绰号兽化或擅自老化，不添加兽头饰件、金色重甲或发光眼睛；'
              '角色身份、年龄及原稿明确的造型优先。'},
)


def style_catalog() -> JsonObject:
    return {'items': [{**deepcopy(item), 'revision': _PRESET_REVISION} for item in _PRESETS]}


def resolve_style(preset_id: str | None) -> JsonObject | None:
    if preset_id is None:
        return None
    style = next((s for s in _PRESETS if s['presetId'] == preset_id), None)
    if style is None:
        raise DomainError('STYLE_PRESET_UNKNOWN')
    return {**deepcopy(style), 'revision': _PRESET_REVISION}


def style_instructions(profile: object, stage: StyleStage) -> str:
    if profile is None:
        return ''
    if not isinstance(profile, dict) or any(
        not isinstance(profile.get(key), str) or not profile[key].strip()
        for key in ('presetId', 'name', 'medium', 'rendering', 'lighting', 'motion', 'avoid')
    ) or not isinstance(profile.get('revision'), int):
        raise DomainError('STYLE_PROFILE_INVALID')
    base = (f"【项目视觉风格：{profile['name']}】{profile['rendering']}"
            f"{profile['lighting']}{profile['avoid']}"
            '画风与材质以此项目风格为准；保持原文的身份、服装、剧情与准确台词，不增删人物。')
    if stage in {'character-prompt', 'character-reference', 'character-reference-view'}:
        base += ('角色身份锁：明确脸型骨相、眉眼鼻唇、发型发色、年龄感、肤色、'
                 '体型比例和标志性特征；保留服装层级、剪裁、配色与已有配饰，不擅自增加装备。'
                 '角色设定图：单一人物、全身清晰、中性纯色背景、自然站姿；'
                 '光线均匀便于辨认五官和服装，不照搬剧情的昏暗或遮挡。无文字、标签和水印。')
        if stage == 'character-reference-view':
            base += '只改变观察角度，保持已确认主图的脸型、发型、年龄、服装和配色。'
    elif stage == 'character-reference-board':
        base += '同一角色的正面、严格侧面、背面排列在一张图中，保持主图身份、服装和配色。'
    elif stage == 'character-reference-text-board':
        base += '同一角色的脸部特写、正面、严格侧面、背面排列在一张横向图中，统一身份、服装和配色。'
    elif stage == 'scene-background':
        base += ('场景参考图：无人广角全景，保留指定时间、地点、天气和光源，'
                 '明确前中后景、门窗位置与人物可行走路径。无人物、动物、文字和水印。')
    elif stage == 'video':
        base += profile['motion'] + '遵循镜头动作顺序、运镜与对白，不新增字幕或水印。'
    else:
        base += '将该画风用于场景和镜头视觉描述，不把画风规则写进人物台词或改变故事事件。'
    return base


def styled_script_input(project: JsonObject, story: str) -> str:
    instructions = style_instructions(project.get('visualStyleProfile'), 'script')
    return story + '\n\n' + instructions if instructions else story


def apply_video_style(shot: JsonObject, project: JsonObject) -> JsonObject:
    result = deepcopy(shot)
    profile = project.get('visualStyleProfile')
    instructions = style_instructions(profile, 'video')
    if instructions:
        assert isinstance(profile, dict)
        result['visualStyle'] = instructions
        # Style fields supplied separately by text models must not override the project.
        result.pop('style', None)
        if isinstance(result.get('scene'), dict):
            result['scene']['style'] = profile['rendering']
            result['scene'].pop('visualStyle', None)
        result['styleSnapshot'] = deepcopy(profile)
    return result
