"""Controlled vocabularies for the news atom library (Schema v1.0)."""

from __future__ import annotations

from enum import StrEnum


class AtomType(StrEnum):
    INFO = "信息"
    OPINION = "观点"
    DATA = "数据"


class AtomStatus(StrEnum):
    ACTIVE = "active"
    SHADOW = "shadow"
    SUPERSEDED = "superseded"
    CONFLICTED = "conflicted"
    ARCHIVED = "archived"
    REJECTED = "rejected"


class AtomOperationType(StrEnum):
    EXTRACT = "extract"
    FILTER = "filter"
    RECONCILE = "reconcile"
    MANUAL = "manual"


class Domain(StrEnum):
    MACRO = "宏观经济"
    FINANCE = "金融市场"
    TECH = "科技"
    AUTO = "汽车"
    REAL_ESTATE = "房地产"
    ENERGY = "能源"
    CONSUMER = "消费"
    HEALTH = "医疗健康"
    POLICY = "政策监管"
    INTL = "国际关系"
    OTHER = "其他"


class SubjectType(StrEnum):
    COMPANY = "企业"
    GOVERNMENT = "政府机构"
    PERSON = "人物"
    ORGANIZATION = "机构"
    REGION = "国家/地区"
    PRODUCT = "产品/品牌"


class WhatType(StrEnum):
    HR = "人事"
    FINANCIAL = "财务"
    PRODUCT = "产品"
    POLICY = "政策"
    MARKET = "市场"
    LEGAL = "法律"
    COOPERATION = "合作"
    ACCIDENT = "事故"
    DIPLOMACY = "外交"
    OTHER = "其他"


class Validity(StrEnum):
    IMMEDIATE = "即时"
    SHORT = "短期"
    MEDIUM = "中期"
    LONG = "长期"
    PERMANENT = "永久"


class Role(StrEnum):
    OFFICIAL = "政府官员"
    EXEC = "企业CEO/高管"
    ANALYST = "分析师"
    SCHOLAR = "学者/研究员"
    LAWYER = "律师"
    ASSOCIATION = "行业协会代表"
    INVESTOR = "投资人"
    JOURNALIST = "记者/媒体"
    POLITICIAN = "政治人物"
    OTHER = "其他"


class Sentiment(StrEnum):
    POSITIVE = "正面"
    NEUTRAL = "中性"
    NEGATIVE = "负面"


class Intensity(StrEnum):
    MILD = "温和"
    CLEAR = "明确"
    STRONG = "强烈"


class PoliticalSpectrum(StrEnum):
    LEFT = "左"
    CENTER = "中"
    RIGHT = "右"
    NA = "不适用"


class ChinaStance(StrEnum):
    POSITIVE = "正面"
    NEUTRAL = "中立"
    CRITICAL = "批评"
    NA = "不适用"


class DataSourceType(StrEnum):
    COMPANY_REPORT = "一手/公司财报"
    GOVERNMENT_STATS = "一手/政府统计"
    INDUSTRY_ASSOC = "一手/行业协会"
    RESEARCH = "二手/研究机构"
    MEDIA_COMPILED = "二手/媒体整理"
    ESTIMATE = "估算/模型预测"
    SURVEY = "调研/问卷"


class Unit(StrEnum):
    CNY_100M = "亿元人民币"
    CNY_1M = "百万元人民币"
    USD_100M = "亿美元"
    USD_1M = "百万美元"
    EUR_100M = "亿欧元"
    HKD_100M = "亿港元"
    PCT = "%（百分比）"
    PP = "pp（百分点）"
    MULTIPLE = "倍"
    INDEX = "指数点"
    VEHICLE_10K = "万辆"
    UNIT_10K = "万台"
    PERSON_10K = "万人"
    PIECE_100M = "亿件"
    TON_10K = "万吨"
    GW = "GW（吉瓦）"
    CNY_PER_SHARE = "元/股"
    USD_PER_BARREL = "美元/桶"
    CNY_PER_SQM = "元/平方米"
    CUSTOM = "自定义"


class PeriodType(StrEnum):
    DAY = "日"
    WEEK = "周"
    MONTH = "月"
    QUARTER = "季度"
    HALF_YEAR = "半年"
    FULL_YEAR = "全年"
    CUMULATIVE = "累计"
    AS_OF = "截至某日"


class RelationType(StrEnum):
    CAUSE = "因果"
    PROGRESSION = "递进"
    REVERSAL = "转折"
    CONTRADICTION = "矛盾"
    CORROBORATION = "印证"
    BACKGROUND = "背景"
    PARALLEL = "并列"


class RelationDirection(StrEnum):
    A_TO_B = "A→B"
    B_TO_A = "B→A"
    BIDIRECTIONAL = "双向"


__all__ = [
    "AtomOperationType",
    "AtomStatus",
    "AtomType",
    "ChinaStance",
    "DataSourceType",
    "Domain",
    "Intensity",
    "PeriodType",
    "PoliticalSpectrum",
    "RelationDirection",
    "RelationType",
    "Role",
    "Sentiment",
    "SubjectType",
    "Unit",
    "Validity",
    "WhatType",
]
