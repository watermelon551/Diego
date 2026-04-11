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

STYLE_THEME_HINTS: dict[str, dict[str, str]] = {
    "minimal-teaching": {"primary": "1F3A5F", "secondary": "4E6A8E", "accent": "2E86DE", "light": "E9EEF5", "bg": "F7FAFC"},
    "academic": {"primary": "1F2937", "secondary": "4B5563", "accent": "2563EB", "light": "E5E7EB", "bg": "F9FAFB"},
    "minimal": {"primary": "1A1A1A", "secondary": "666666", "accent": "3B82F6", "light": "EDEDED", "bg": "FFFFFF"},
    "professional": {"primary": "0B1F3A", "secondary": "1E3A5F", "accent": "00A3FF", "light": "E8EEF5", "bg": "F4F7FB"},
    "botanical": {"primary": "2F5D50", "secondary": "5E8B7E", "accent": "8CBF5A", "light": "E9F2EB", "bg": "F7FBF7"},
    "wabi-sabi": {"primary": "4A3F35", "secondary": "7B6D5D", "accent": "B08B67", "light": "EDE6DE", "bg": "F7F3ED"},
    "memphis": {"primary": "111111", "secondary": "2A2A2A", "accent": "FF3D81", "light": "FFE66D", "bg": "FFF6EC"},
    "constructivism": {"primary": "111111", "secondary": "2E2E2E", "accent": "E10600", "light": "F5F5F5", "bg": "FFF8E1"},
    "neo-brutalism": {"primary": "0A0A0A", "secondary": "1D1D1D", "accent": "00D1FF", "light": "F4F4F4", "bg": "FFFFFF"},
    "8bit": {"primary": "1A1A1A", "secondary": "3A3A3A", "accent": "00E676", "light": "F9D65C", "bg": "F5F7FF"},
    "electro-pop": {"primary": "120024", "secondary": "3A0B63", "accent": "FF00C8", "light": "00E5FF", "bg": "0E0A1F"},
    "geo-bold": {"primary": "111111", "secondary": "2B2B2B", "accent": "FF6B00", "light": "E8F0FF", "bg": "FFFFFF"},
    "morandi": {"primary": "6E6A67", "secondary": "8F8A86", "accent": "BCA89F", "light": "E8E2DC", "bg": "F7F4F1"},
    "nordic-research": {"primary": "223344", "secondary": "4A5F70", "accent": "5FA8D3", "light": "E8EEF2", "bg": "F7FAFC"},
    "emotional-flow": {"primary": "5A4E7C", "secondary": "7E6FAE", "accent": "F08AA6", "light": "F5EAF3", "bg": "FFF7FB"},
    "cinema-minimal": {"primary": "F2F2F2", "secondary": "BFBFBF", "accent": "F5C16C", "light": "2A2A2A", "bg": "111111"},
    "rational-blue": {"primary": "1B2A4A", "secondary": "345A8A", "accent": "4DA3FF", "light": "E7EEF8", "bg": "F5F8FD"},
    "warm-vc": {"primary": "4A2E22", "secondary": "7A4F3A", "accent": "F28C52", "light": "F9E7DA", "bg": "FFF9F4"},
    "contemporary-academic": {"primary": "1E2430", "secondary": "4A5568", "accent": "6B8AF5", "light": "E8EBF2", "bg": "FAFBFD"},
    "academic-curation": {"primary": "2F3542", "secondary": "57606F", "accent": "70A1FF", "light": "EAF0F6", "bg": "FCFDFF"},
}


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


def get_style_theme_hint(style_choice: str | None) -> dict[str, str] | None:
    normalized = normalize_style_choice(style_choice)
    if normalized == STYLE_PRESET_AUTO:
        return None
    theme = STYLE_THEME_HINTS.get(normalized.lower())
    return dict(theme) if isinstance(theme, dict) else None
