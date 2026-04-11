from __future__ import annotations

from dataclasses import dataclass

STYLE_PRESET_AUTO = "auto"


@dataclass(frozen=True)
class StylePreset:
    id: str
    name: str
    prompt: str
    template_style_hint: str
    style_recipe_hint: str


STYLE_PRESETS: tuple[StylePreset, ...] = (
    StylePreset("minimal-teaching", "简约教学", "传统教学课件风格，结构清晰、层级明确、稳定统一、便于讲授。", "preset:minimal-teaching education training soft", "soft"),
    StylePreset("academic", "学术", "学术风格，理性、规范、清晰，强调研究表达、逻辑结构与图表可读性。", "preset:academic report data authority sharp", "sharp"),
    StylePreset("minimal", "极简", "极简风格，干净克制，突出留白、层级和信息节奏，减少装饰。", "preset:minimal balanced soft", "soft"),
    StylePreset("professional", "专业", "专业商务科技风格，沉稳正式，模块化表达，强调可信度。", "preset:professional finance report authority sharp", "sharp"),
    StylePreset("botanical", "植境", "自然生态风格，清新安静，轻纹理与植物意象，重视舒适阅读。", "preset:botanical creative rounded", "rounded"),
    StylePreset("wabi-sabi", "侘寂", "侘寂风格，低饱和质朴、留白克制，强调材质感与东方审美。", "preset:wabi-sabi soft balanced", "soft"),
    StylePreset("memphis", "孟菲斯", "孟菲斯风格，活泼几何、强节奏、图形化，突出创意与年轻感。", "preset:memphis creative marketing rounded", "rounded"),
    StylePreset("constructivism", "构成主义", "构成主义风格，高对比、斜切与非对称构图，强调力量感。", "preset:constructivism brutal sharp data", "sharp"),
    StylePreset("neo-brutalism", "新粗野主义", "新粗野主义风格，直接硬朗、实验感强，粗体与块面优先。", "preset:neo-brutalism brutal sharp", "sharp"),
    StylePreset("8bit", "8-bit", "像素复古风格，电子游戏界面语言，方块图形与像素边框。", "preset:8bit sharp creative", "sharp"),
    StylePreset("electro-pop", "流行电子", "电子潮流风格，霓虹发光、未来感和高冲击构图。", "preset:electro-pop premium brand luxury pill", "pill"),
    StylePreset("geo-bold", "几何粗体", "几何粗体风格，块面结构与大字号标题，强调识别度。", "preset:geo-bold sharp data", "sharp"),
    StylePreset("morandi", "莫兰迪", "莫兰迪风格，低饱和柔和配色，克制优雅，文艺舒缓。", "preset:morandi soft balanced", "soft"),
    StylePreset("nordic-research", "北欧研究", "北欧研究风格，理性自然，清爽网格与低干扰背景。", "preset:nordic-research education soft", "soft"),
    StylePreset("emotional-flow", "感性流动", "感性流动风格，柔雾氛围、曲线与半透明层次，强调情绪表达。", "preset:emotional-flow creative rounded", "rounded"),
    StylePreset("cinema-minimal", "影院极简", "影院极简风格，低照度电影感、光影聚焦、深邃克制。", "preset:cinema-minimal soft balanced", "soft"),
    StylePreset("rational-blue", "理性蓝调", "理性蓝调风格，冷静专业，强调分析结构与科技可信感。", "preset:rational-blue finance data sharp", "sharp"),
    StylePreset("warm-vc", "暖调创投", "暖调创投风格，商业质感与亲和力并存，适合路演提案。", "preset:warm-vc marketing rounded", "rounded"),
    StylePreset("contemporary-academic", "当代学术", "当代学术风格，现代简洁，研究展板式信息组织。", "preset:contemporary-academic report authority sharp", "sharp"),
    StylePreset("academic-curation", "学术策展", "学术策展风格，轻盈克制、展签式排版，强调图文并置。", "preset:academic-curation education soft", "soft"),
)


_PRESET_BY_ID = {item.id.lower(): item for item in STYLE_PRESETS}
_PRESET_BY_NAME = {item.name.lower(): item for item in STYLE_PRESETS}


def normalize_style_choice(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return STYLE_PRESET_AUTO
    lowered = raw.lower()
    if lowered == STYLE_PRESET_AUTO:
        return STYLE_PRESET_AUTO
    if lowered in _PRESET_BY_ID:
        return _PRESET_BY_ID[lowered].id
    if lowered in _PRESET_BY_NAME:
        return _PRESET_BY_NAME[lowered].id
    return raw


def is_valid_style_choice(value: str | None) -> bool:
    normalized = normalize_style_choice(value)
    return normalized == STYLE_PRESET_AUTO or normalized.lower() in _PRESET_BY_ID


def resolve_style_choice(value: str | None) -> StylePreset | None:
    normalized = normalize_style_choice(value)
    if normalized == STYLE_PRESET_AUTO:
        return None
    return _PRESET_BY_ID.get(normalized.lower())


def list_style_presets() -> list[StylePreset]:
    return list(STYLE_PRESETS)

