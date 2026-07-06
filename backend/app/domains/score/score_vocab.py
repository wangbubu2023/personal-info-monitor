"""Vocabulary for pim-score-v2 rule-based dimensions.

Edit this file when tuning lanes, entity tiers, or event patterns.
Lists are merged at import time; substrings are matched case-insensitively.

See ``docs/SCORING_MODEL.md`` for operational guidance.
"""

from __future__ import annotations


def _merge(*groups: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for term in group:
            key = term.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(term.strip())
    return tuple(out)


# ---------------------------------------------------------------------------
# Lane keywords — classify article topic (title hit ×2 in score_rules)
# ---------------------------------------------------------------------------

_GEO_TERMS = (
    # 双边 / 多边
    "访华", "访美", "访日", "会晤", "峰会", "对话", "会谈", "外交", "大使", "领事",
    "制裁", "关税", "贸易战", "脱钩", "实体清单", "出口管制", "禁运", "封锁",
    "联合国", "安理会", "北约", "NATO", "G7", "G20", "APEC", "金砖", "上合",
    "一带一路", "印太", "台海", "两岸", "南海", "东海", "朝鲜", "半岛",
    "俄乌", "乌克兰", "俄罗斯", "中东", "以巴", "加沙", "伊朗", "叙利亚",
    "欧盟", "欧洲", "白宫", "国务院", "外交部", "国防部", "五角大楼", "克里姆林宫",
    "geopolit", "sanctions", "bilateral", "state visit", "summit", "diplomacy",
    "tariff", "trade war", "national security", "foreign policy",
    # 灾害 / 公共安全
    "洪灾", "洪水", "山洪", "暴雨", "强降雨", "内涝", "地震", "台风", "山体滑坡",
    "遇难", "死亡", "失联", "伤亡", "evacuat", "flood", "landslide", "earthquake",
    "typhoon", "fatalities", "killed", "casualties",
)

_MACRO_FINANCE_TERMS = (
    "美联储", "欧央行", "日本央行", "英国央行", "人民银行", "央行", "货币政策",
    "降息", "加息", "基点", "利率", "国债", "美债", "收益率", "利差",
    "CPI", "PPI", "GDP", "非农", "失业率", "通胀", "通缩", "滞胀", "软着陆", "硬着陆",
    "量化宽松", "QE", "缩表", "QT", "逆回购", "MLF", "LPR", "准备金",
    "汇率", "人民币", "美元", "日元", "欧元", "离岸", "在岸", "中间价",
    "fed ", "federal reserve", "ecb", "boj", "boe", "interest rate", "inflation",
    "monetary policy", "treasury yield", "yield curve", "recession",
)

_REGULATION_TERMS = (
    "反垄断", "监管", "合规", "立法", "法案", "条例", "办法", "征求意见稿",
    "网信办", "工信部", "市监总局", "证监会", "银保监会", "外汇局",
    "FDA", "SEC ", "FTC", "DOJ", "CFIUS", "EU AI Act", "GDPR",
    "数据安全", "个人信息", "算法推荐", "深度合成", "生成式人工智能",
    "antitrust", "regulation", "compliance", "proposed rule", "final rule",
    "chip act", "芯片法案", "出口管制", "实体清单", "investigation",
)

_TECH_PRODUCT_TERMS = (
    # AI / 模型
    "人工智能", "大模型", "模型", "LLM", "GPT", "Claude", "Gemini", "Llama",
    "DeepSeek", "通义", "文心", "Kimi", "智谱", "月之暗面", "百川", "MiniMax",
    "OpenAI", "Anthropic", "Google DeepMind", "xAI", "Mistral", "Cohere",
    "推理", "训练", "微调", "RAG", "Agent", "多模态", "token", "context window",
    "model release", "new model", "frontier model", "AI chip", "inference",
    # 硬件 / 芯片
    "芯片", "半导体", "光刻", "EUV", "GPU", "NPU", "TPU", "CUDA", "HBM",
    "台积电", "TSMC", "ASML", "英伟达", "NVIDIA", "AMD", "Intel", "高通", "Qualcomm",
    "华为", "海思", "中芯", "SMIC", "三星", "SK海力士", "美光", "Micron",
    # 消费 / 平台
    "iPhone", "iPad", "Mac", "Android", "鸿蒙", "HarmonyOS", "Windows",
    "云服务", "云计算", "SaaS", "PaaS", "IaaS", "数据中心", "算力",
    "上线", "开源", "API", "SDK", "beta", "GA", "preview",
)

_MARKETS_TERMS = (
    "股价", "股票", "股市", "大盘", "指数", "纳指", "标普", "道指", "恒生", "上证", "深证",
    "创业板", "科创板", "北交所", "财报", "业绩", "营收", "净利润", "毛利", "指引",
    "并购", "收购", "IPO", "上市", "退市", "增发", "配股", "回购", "分红",
    "涨停", "跌停", "做多", "做空", "牛市", "熊市", "波动", "VIX", "期权", "期货",
    "ETF", "基金", "私募", "公募", "QFII", "北向", "南向", "融资融券",
    "earnings", "revenue", "guidance", "merger", "acquisition", "market cap",
    "stock", "shares", "dividend", "buyback", "IPO", "delisting",
)

_CORPORATE_TERMS = (
    "CEO", "CFO", "CTO", "董事长", "总裁", "总经理", "创始人", "辞任", "任命", "接任",
    "裁员", "layoff", "重组", "分拆", "剥离", "战略", "组织架构", "人事变动",
    "合作", "签约", "战略投资", "合资", "partnership", "restructuring",
)

_VC_TERMS = (
    "融资", "A轮", "B轮", "C轮", "Pre-A", "种子轮", "天使轮", "跟投", "领投",
    "估值", "独角兽", "独角兽企业", "战投", "并购基金", "LP", "GP",
    "Series A", "Series B", "Series C", "venture", "raised", "valuation", "funding round",
)

LANE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "geopolitics": _GEO_TERMS,
    "macro_finance": _MACRO_FINANCE_TERMS,
    "regulation": _REGULATION_TERMS,
    "tech_product": _TECH_PRODUCT_TERMS,
    "markets": _MARKETS_TERMS,
    "corporate": _CORPORATE_TERMS,
    "vc_deals": _VC_TERMS,
}


# ---------------------------------------------------------------------------
# Entity tiers — salience within lane (first match wins: S → A → B → C)
# Use distinctive spellings; English terms are lowercased at match time.
# ---------------------------------------------------------------------------

# --- 时政：主要国家元首 / 核心决策人物 ---
_GEO_LEADERS_S = (
    "习近平", "拜登", "biden", "特朗普", "trump", "普京", "putin",
    "马克龙", "macron", "朔尔茨", "scholz", "岸田文雄", "石破茂",
    "莫迪", "modi", "尹锡悦", "yoon", "特鲁多", "trudeau",
    "泽连斯基", "zelensky", "内塔尼亚胡", "netanyahu", "金正恩", "kim jong",
    "欧尔班", "orban", "米莱", "milei",
)

_GEO_INSTITUTIONS_S = (
    "白宫", "white house", "国务院", "state department", "外交部",
    "联合国", "united nations", "北约", "nato", "欧盟", "european union",
    "克里姆林宫", "kremlin", "国防部", "pentagon", "五角大楼",
)

# --- 财经：央行 / 监管 / 顶级机构 ---
_FIN_INSTITUTIONS_S = (
    "美联储", "federal reserve", "fed chair", "鲍威尔", "powell",
    "欧央行", "ecb", "拉加德", "lagarde",
    "中国人民银行", "人民银行", "潘功胜", "易纲",
    "日本央行", "boj", "植田和男", "英国央行", "boe",
    "财政部", "treasury department", "耶伦", "yellen",
    "imf", "international monetary fund", "世界银行", "world bank",
)

_FIN_INSTITUTIONS_A = (
    "高盛", "goldman sachs", "摩根大通", "jpmorgan", "jp morgan",
    "摩根士丹利", "morgan stanley", "花旗", "citigroup", "citi ",
    "瑞银", "ubs", "瑞信", "credit suisse", "汇丰", "hsbc",
    "伯克希尔", "berkshire", "巴菲特", "buffett", "桥水", "bridgewater",
    "黑石", "blackstone", "贝莱德", "blackrock", "先锋", "vanguard",
    "证监会", "csrc", "sec ", "cftc", "finra",
)

# --- 科技：巨头 / AI 实验室 / 关键 CEO ---
_TECH_COMPANIES_S = (
    "openai", "anthropic", "google", "alphabet", "apple", "microsoft", "meta ",
    "amazon", "nvidia", "tesla", "台积电", "tsmc", "asml",
    "华为", "huawei", "腾讯", "tencent", "阿里巴巴", "alibaba", "字节跳动", "bytedance",
)

_TECH_AI_LEADERS_S = (
    "sam altman", "奥特曼", "dario amodei", "demis hassabis", "黄仁勋", "jensen huang",
    "马斯克", "elon musk", "musk", "库克", "tim cook", "纳德拉", "satya nadella",
    "扎克伯格", "zuckerberg", "苏姿丰", "lisa su", "魏哲家", "cc wei",
)

_TECH_COMPANIES_A = (
    "deepseek", "深度求索", "月之暗面", "moonshot", "kimi", "智谱", "zhipu",
    "百川", "baichuan", "minimax", "零一万物", "01.ai", "阶跃星辰",
    "mistral", "cohere", "xai", "groq", "cerebras", "sambanova",
    "amd", "intel", "qualcomm", "高通", "博通", "broadcom", "arm ",
    "三星", "samsung", "sk hynix", "海力士", "美光", "micron", "中芯国际", "smic",
    "小米", "xiaomi", "oppo", "vivo", "比亚迪", "byd", "蔚来", "nio",
    "理想", "li auto", "小鹏", "xpeng", "网易", "netease", "京东", "jd.com", "jd ",
    "拼多多", "pinduoduo", "pdd", "美团", "meituan", "百度", "baidu",
    "snowflake", "databricks", "palantir", "oracle", "sap ", "salesforce",
    "adobe", "netflix", "spotify", "uber", "airbnb",
)

_TECH_FIGURES_A = (
    "雷军", "leijun", "张一鸣", "zhang yiming", "马化腾", "pony ma",
    "李彦宏", "robin li", "丁磊", "william ding", "周鸿祎",
    "andrej karpathy", "ilya sutskever", "yann lecun", "hinton", "吴恩达", "andrew ng",
)

_GEO_FIGURES_A = (
    "布林肯", "blinken", "沙利文", "sullivan", "拉夫罗夫", "lavrov",
    "冯德莱恩", "von der leyen", "斯托尔滕贝格", "stoltenberg",
    "王毅", "秦刚", "谢锋", "驻美大使", "外长", "国务卿", "secretary of state",
    "国防部长", "defense secretary", "national security adviser",
)

_MARKET_FIGURES_A = (
    "jamie dimon", "戴蒙", "david solomon", "ray dalio", "达利欧",
    "carl icahn", "bill ackman", "cathie wood", "木头姐",
)

ENTITY_TIER_S: tuple[str, ...] = _merge(
    _GEO_LEADERS_S,
    _GEO_INSTITUTIONS_S,
    _FIN_INSTITUTIONS_S,
    _TECH_COMPANIES_S,
    _TECH_AI_LEADERS_S,
)

ENTITY_TIER_A: tuple[str, ...] = _merge(
    _GEO_FIGURES_A,
    _FIN_INSTITUTIONS_A,
    _TECH_COMPANIES_A,
    _TECH_FIGURES_A,
    _MARKET_FIGURES_A,
)

ENTITY_TIER_B: tuple[str, ...] = _merge(
    (
        "startup", "初创", "独角兽", "隐形冠军", "专精特新",
        "a16z", "sequoia", "红杉", "高瓴", "hillhouse", "idg", "经纬", "真格",
        "benchmark", "accel", "lightspeed", "softbank", "软银", "vision fund",
        "y combinator", "yc ", "founders fund",
    ),
)

ENTITY_TIER_SCORES = {"S": 9.0, "A": 7.5, "B": 6.0, "C": 4.0}


# ---------------------------------------------------------------------------
# Event patterns — salience bonus when headline matches event type
# ---------------------------------------------------------------------------

EVENT_PATTERNS: dict[str, tuple[float, tuple[str, ...]]] = {
    "summit_visit": (
        1.0,
        (
            "访华", "访美", "峰会", "会晤", "国事访问", "summit", "state visit",
            "bilateral talks", "meet with", "会谈",
        ),
    ),
    "model_release": (
        1.0,
        (
            "发布模型", "新模型", "大模型", "model release", "new model", "gpt-",
            "claude ", "gemini ", "llama ", "frontier model", "重磅发布", "正式上线",
        ),
    ),
    "policy_shift": (
        1.0,
        (
            "法案", "全面", "禁令", "出口管制", "实体清单", "ban ", "policy shift",
            "regulation", "行政令", "executive order", "立法", "征求意见稿",
        ),
    ),
    "earnings": (
        0.5,
        (
            "财报", "业绩", "earnings", "revenue", "营收", "净利润", "guidance",
            "业绩会", "电话会", "earnings call",
        ),
    ),
    "funding": (
        0.5,
        (
            "融资", "亿美元", "亿元", "series a", "series b", "series c",
            "raised", "valuation", "估值", "领投", "跟投",
        ),
    ),
    "m_and_a": (
        0.5,
        (
            "并购", "收购", "merger", "acquisition", "takeover", "buyout",
            "战略投资", "全资收购",
        ),
    ),
    "rate_decision": (
        0.5,
        (
            "降息", "加息", "利率决定", "rate decision", "fomc", "维持利率",
            "基点", "basis point",
        ),
    ),
    "ipo_offering": (
        1.0,
        (
            "首次公开募股", "公开募股", " ipo", "ipo ", "public offering",
            "going public", "上市申请", "股票出售申请", "files for public",
            "filed for public", "largest ipo", "最大规模", "有史以来最大",
        ),
    ),
    "disaster_casualty": (
        1.5,
        (
            "死亡", "遇难", "失联", "伤亡", "fatalities", "killed", "casualties",
            "dead", "missing",
        ),
    ),
}


# ---------------------------------------------------------------------------
# Reach shape keywords
# ---------------------------------------------------------------------------

# Narrow-scope stories (deal, accessory, division hire) — cap impact dimensions.
# Matched against title first, then title+summary. See score_rules.apply_impact_caps.
# Commerce / promo / consumer-feature stories — aggressive score caps.
COMMERCE_SIGNALS: tuple[str, ...] = (
    # deals & sales
    "优惠", "折扣", "打折", "促销", "特价", "最低价", "最优惠", "清仓", "周年促销",
    "折扣优惠", "优惠活动", "我们最喜欢", "favorite deal", "anniversary sale",
    " gift guide", "gift guide",
    "memorial day", "black friday", "cyber monday", "阵亡将士",
    "discount", "% off", " off at", "best price", "lowest price", "on sale",
    # accessories & gadgets (commerce context)
    "magsafe", "power bank", "充电宝", "适配器", "电源适配器", "earbuds", "charger",
    # streaming / subscription product fluff
    "订阅用户", "观看记录", "推荐内容", "套餐的订阅", "bundle subscriber",
    "watch history", "subscribers can", "available now",
)

# Backward-compatible alias used by tests/docs
DEAL_SIGNALS: tuple[str, ...] = COMMERCE_SIGNALS

# IPO / secondary offering — must not trigger commerce deal caps ("stock sale", etc.)
MARKET_OFFERING_EXEMPT: tuple[str, ...] = (
    "ipo", "initial public offering", "public offering", "going public",
    "首次公开募股", "公开募股", "上市", "股票出售", "stock sale", "files for",
    "filed for", "sec filing", "s-1",
)

DISASTER_TERMS: tuple[str, ...] = (
    "洪灾", "洪水", "山洪", "暴雨", "强降雨", "内涝", "地震", "台风", "山体滑坡",
    "flood", "landslide", "earthquake", "typhoon", "evacuation",
)

CASUALTY_TERMS: tuple[str, ...] = (
    "死亡", "遇难", "失联", "伤亡", "fatalities", "killed", "casualties", "dead",
)

NARROW_SCOPE_SIGNALS: tuple[str, ...] = (
    "聘请", " hired", "hires", " hiring", " appoints", "任命", "首席战略",
    "修复", " fix ", "firmware", "patch notes",
    "review", "评测", " tested", "测试了", "hands-on", "上手",
    "power bank", "earbuds", "adapter", "charger", "controller", "headphones",
    "keyboard", "mouse", "smartwatch", "webcam",
    "充电宝", "适配器", "耳机", "控制器", "键盘", "鼠标", "手环",
)

IMPACT_CAPS: dict[str, dict[str, float]] = {
    "commerce": {"salience": 3.5, "reach": 3.5, "depth": 4.0},
    "narrow": {"salience": 6.5, "reach": 5.5, "depth": 7.5},
}

REACH_KEYWORDS: dict[str, tuple[str, ...]] = {
    "systemic": (
        "全面", "全球", "行业格局", "系统性", "重塑", "颠覆", "范式",
        "global", "systemic", "worldwide", "across the industry", "landscape",
        "游戏规则", "基础设施", "底层",
    ),
    "sector": (
        "行业", "赛道", "生态", "供应链", "产业链", "sector", "industry-wide",
        "ecosystem", "vertical", "whole market", "全行业",
        "多地", "多个省份", "数个省份", "跨省", "several provinces",
        "首次公开募股", "公开募股", " ipo", "public offering", "上市",
    ),
    "local": (
        "当地", "区域", "试点", "省级", "市级", "local", "regional", "pilot",
        "province", "county",
    ),
}

REACH_SCORES = {"systemic": 9.0, "sector": 7.0, "major_entity": 6.5, "entity": 5.5, "local": 3.5}

AUTHORITY_TYPE_BONUS: dict[str, float] = {
    "official": 1.0,
    "regulator": 1.0,
    "wire": 0.5,
    "primary": 0.5,
}

SOURCE_STARS_AUTHORITY = {1: 4.0, 2: 6.5, 3: 8.5}

LANE_LABELS = {
    "geopolitics": "地缘外交",
    "macro_finance": "宏观金融",
    "regulation": "监管政策",
    "tech_product": "科技产品",
    "markets": "市场交易",
    "corporate": "公司动态",
    "vc_deals": "创投融资",
    "other": "综合",
}

DIMENSION_LABELS = {
    "salience": "显著性",
    "reach": "影响面",
    "authority": "信源权威",
    "depth": "信息深度",
    "subjective": "主观判断",
}


def _tuple_from_yaml(value, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return fallback
    return _merge(tuple(str(item) for item in value))


def _dict_tuple_from_yaml(value, fallback: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        return fallback
    merged: dict[str, tuple[str, ...]] = {}
    for key, default_terms in fallback.items():
        merged[key] = _tuple_from_yaml(value.get(key), default_terms)
    for key, terms in value.items():
        if key not in merged:
            merged[str(key)] = _tuple_from_yaml(terms, ())
    return merged


def _float_dict_from_yaml(value, fallback: dict) -> dict:
    if not isinstance(value, dict):
        return fallback
    out = dict(fallback)
    for key, raw in value.items():
        try:
            out[key] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


def _event_patterns_from_yaml(value, fallback: dict[str, tuple[float, tuple[str, ...]]]) -> dict[str, tuple[float, tuple[str, ...]]]:
    if not isinstance(value, dict):
        return fallback
    out = dict(fallback)
    for key, raw in value.items():
        if not isinstance(raw, dict):
            continue
        try:
            bonus = float(raw.get("bonus", 0.0))
        except (TypeError, ValueError):
            continue
        keywords = _tuple_from_yaml(raw.get("keywords"), ())
        if keywords:
            out[str(key)] = (bonus, keywords)
    return out


def _nested_float_dict_from_yaml(value, fallback: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    if not isinstance(value, dict):
        return fallback
    out = {key: dict(val) for key, val in fallback.items()}
    for key, raw in value.items():
        if not isinstance(raw, dict):
            continue
        bucket = out.setdefault(str(key), {})
        for dim, limit in raw.items():
            try:
                bucket[str(dim)] = float(limit)
            except (TypeError, ValueError):
                continue
    return out


def _labels_from_yaml(value, fallback: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict):
        return fallback
    out = dict(fallback)
    for key, raw in value.items():
        label = str(raw or "").strip()
        if label:
            out[str(key)] = label
    return out


def _source_stars_from_yaml(value, fallback: dict[int, float]) -> dict[int, float]:
    if not isinstance(value, dict):
        return fallback
    out = dict(fallback)
    for key, raw in value.items():
        try:
            out[int(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


def _apply_score_vocab_data(data: dict) -> None:
    global LANE_KEYWORDS, ENTITY_TIER_S, ENTITY_TIER_A, ENTITY_TIER_B
    global ENTITY_TIER_SCORES, EVENT_PATTERNS, COMMERCE_SIGNALS, DEAL_SIGNALS
    global MARKET_OFFERING_EXEMPT, DISASTER_TERMS, CASUALTY_TERMS, NARROW_SCOPE_SIGNALS
    global IMPACT_CAPS, REACH_KEYWORDS, REACH_SCORES, AUTHORITY_TYPE_BONUS
    global SOURCE_STARS_AUTHORITY, LANE_LABELS, DIMENSION_LABELS

    if not data:
        return

    LANE_KEYWORDS = _dict_tuple_from_yaml(data.get("lane_keywords"), LANE_KEYWORDS)
    tiers = data.get("entity_tiers") if isinstance(data.get("entity_tiers"), dict) else {}
    ENTITY_TIER_S = _tuple_from_yaml(tiers.get("S"), ENTITY_TIER_S)
    ENTITY_TIER_A = _tuple_from_yaml(tiers.get("A"), ENTITY_TIER_A)
    ENTITY_TIER_B = _tuple_from_yaml(tiers.get("B"), ENTITY_TIER_B)
    ENTITY_TIER_SCORES = _float_dict_from_yaml(data.get("entity_tier_scores"), ENTITY_TIER_SCORES)
    EVENT_PATTERNS = _event_patterns_from_yaml(data.get("event_patterns"), EVENT_PATTERNS)

    signals = data.get("signals") if isinstance(data.get("signals"), dict) else {}
    COMMERCE_SIGNALS = _tuple_from_yaml(signals.get("commerce"), COMMERCE_SIGNALS)
    DEAL_SIGNALS = COMMERCE_SIGNALS
    MARKET_OFFERING_EXEMPT = _tuple_from_yaml(signals.get("market_offering_exempt"), MARKET_OFFERING_EXEMPT)
    DISASTER_TERMS = _tuple_from_yaml(signals.get("disaster"), DISASTER_TERMS)
    CASUALTY_TERMS = _tuple_from_yaml(signals.get("casualty"), CASUALTY_TERMS)
    NARROW_SCOPE_SIGNALS = _tuple_from_yaml(signals.get("narrow_scope"), NARROW_SCOPE_SIGNALS)

    IMPACT_CAPS = _nested_float_dict_from_yaml(data.get("impact_caps"), IMPACT_CAPS)
    REACH_KEYWORDS = _dict_tuple_from_yaml(data.get("reach_keywords"), REACH_KEYWORDS)
    REACH_SCORES = _float_dict_from_yaml(data.get("reach_scores"), REACH_SCORES)
    AUTHORITY_TYPE_BONUS = _float_dict_from_yaml(data.get("authority_type_bonus"), AUTHORITY_TYPE_BONUS)
    SOURCE_STARS_AUTHORITY = _source_stars_from_yaml(data.get("source_stars_authority"), SOURCE_STARS_AUTHORITY)
    LANE_LABELS = _labels_from_yaml(data.get("lane_labels"), LANE_LABELS)
    DIMENSION_LABELS = _labels_from_yaml(data.get("dimension_labels"), DIMENSION_LABELS)


def score_vocab_snapshot() -> dict:
    """Return lightweight metadata about the active scoring vocabulary."""
    return {
        "lane_count": len(LANE_KEYWORDS),
        "entity_tier_counts": {
            "S": len(ENTITY_TIER_S),
            "A": len(ENTITY_TIER_A),
            "B": len(ENTITY_TIER_B),
        },
        "event_pattern_count": len(EVENT_PATTERNS),
        "reach_level_count": len(REACH_KEYWORDS),
    }


def reload_score_vocab_from_disk(path=None) -> dict:
    """Reload YAML-backed score vocab and update exported constants."""
    from app.domains.score.score_vocab_loader import reload_score_vocab

    data = reload_score_vocab(path)
    _apply_score_vocab_data(data)
    return score_vocab_snapshot()


try:
    from app.domains.score.score_vocab_loader import load_score_vocab

    _apply_score_vocab_data(load_score_vocab())
except (OSError, TypeError, ValueError):
    # Keep import-time scoring available even when a local YAML edit is invalid.
    pass
