"""
小児科漢方薬推奨システム (Kanpo Recommender for Pediatrics)
Flask Web Application

信頼できるデータソース（小児科領域）:
- ツムラ医療用漢方製剤 添付文書・インタビューフォーム
- 日本東洋医学会 EBM漢方（小児科領域）
- 日本小児心身医学会 関連ガイドライン
- 厚生労働省 保険適用医薬品リスト

注意: このシステムは医療従事者の参考用です。
最終的な処方判断は医師が行ってください。
対象年齢: 乳幼児（0〜6歳）。7歳以上には使用しないでください。
特に1歳未満は医師の個別判断が必須です。

注意: 本ファイル内のツムラ番号・生薬含有量・エビデンス・年齢換算係数等は
creation_order.md に基づく暫定値を含む。実運用前に医療従事者による検証必須。
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

LOG_DB_PATH = Path(__file__).resolve().parent / "instance" / "operation_log.db"


def init_log_db():
    LOG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(LOG_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS operation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operated_at TEXT NOT NULL,
            ip_address TEXT NOT NULL DEFAULT '-',
            operation TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


def log_operation(operation: str, detail: str = ""):
    try:
        conn = sqlite3.connect(LOG_DB_PATH)
        conn.execute(
            "INSERT INTO operation_log (operated_at, ip_address, operation, detail) VALUES (?, ?, ?, ?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                request.remote_addr or "-",
                operation,
                detail,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # ログ失敗でアプリを止めない


# =============================================================================
# ライフステージ・年齢区分（小児科版固有）
# =============================================================================

LIFE_STAGES = {
    "乳児期": {
        "label": "乳児期（0歳〜1歳未満）",
        "age_options": [
            {"key": "under_1", "label": "1歳未満", "dose_factor": 0.25},
        ],
        "warning": "乳児期は漢方薬の使用実績・エビデンスが特に限定的です。医師の個別判断を必須としてください。",
    },
    "幼児期": {
        "label": "幼児期（1歳〜6歳）",
        "age_options": [
            {"key": "1-2", "label": "1〜2歳", "dose_factor": 0.333},
            {"key": "3-5", "label": "3〜5歳", "dose_factor": 0.5},
            {"key": "6", "label": "6歳", "dose_factor": 0.5},
        ],
        "warning": None,
    },
}

# LIFE_STAGES から導出（二重管理回避）
AGE_DOSE_FACTORS = {
    opt["key"]: opt["dose_factor"]
    for stage in LIFE_STAGES.values()
    for opt in stage["age_options"]
}

AGE_NOTE_KEY_MAP = {
    "under_1": "age_under_1",
    "1-2": "age_1_2",
    "3-5": "age_3_5",
    "6": "age_6",
}

VALID_LIFE_STAGES = set(LIFE_STAGES.keys())
VALID_AGE_KEYS = set(AGE_DOSE_FACTORS.keys())


# =============================================================================
# メーカー（追加指示#4・2026-08-09で新設）
#
# 【重要・医療安全性に関する警告】
# メーカー別の製品番号・生薬量データはすべて一般的な漢方知識に基づく未検証の暫定値である。
# 実運用開始前に薬剤師が各メーカー公式の添付文書・インタビューフォームで全件照合するまでは、
# 複数メーカー選択機能自体を実務では使用しないこと。
# =============================================================================

MANUFACTURERS = {
    "ツムラ": {"label": "ツムラ", "order": 1},
    "クラシエ": {"label": "クラシエ", "order": 2},
    "コタロー": {"label": "コタロー（小太郎漢方製薬）", "order": 3},
}
DEFAULT_MANUFACTURER = "ツムラ"
VALID_MANUFACTURERS = set(MANUFACTURERS.keys())


# =============================================================================
# 症状データベース（4カテゴリ・28症状。初期案26症状 + 追加指示#2で2症状追加）
# =============================================================================

SYMPTOM_CATEGORIES = {
    "消化器症状": [
        "腹痛", "便秘", "下痢", "嘔吐", "食欲不振", "乳児疝痛（コリック）", "便秘・下痢を繰り返す",
        "口内炎",
    ],
    "呼吸器症状": [
        "咳（乾性）", "咳（湿性・痰がらみ）", "喘息傾向", "鼻水・鼻づまり",
        "感冒（かぜ）初期", "感冒の遷延・長引く微熱", "中耳炎を繰り返す", "咽頭痛・扁桃炎",
    ],
    "夜泣き・かんしゃく・神経症状": [
        "夜泣き", "かんしゃく・疳の虫", "不眠", "情緒不安定", "熱性けいれん後の体調不良",
    ],
    "虚弱体質・皮膚・その他": [
        "虚弱体質・疲れやすい", "食が細い", "体重増加不良", "寝汗（盗汗）",
        "アトピー性皮膚炎", "湿疹・おむつかぶれ", "病後の体力低下",
    ],
}

# 各症状が該当するライフステージ（暫定・要医学レビュー）
SYMPTOM_LIFE_STAGES = {
    "腹痛": ["幼児期"],
    "便秘": ["乳児期", "幼児期"],
    "下痢": ["乳児期", "幼児期"],
    "嘔吐": ["乳児期", "幼児期"],
    "食欲不振": ["幼児期"],
    "乳児疝痛（コリック）": ["乳児期"],
    "便秘・下痢を繰り返す": ["乳児期", "幼児期"],
    "咳（乾性）": ["乳児期", "幼児期"],
    "咳（湿性・痰がらみ）": ["乳児期", "幼児期"],
    "喘息傾向": ["幼児期"],
    "鼻水・鼻づまり": ["乳児期", "幼児期"],
    "感冒（かぜ）初期": ["乳児期", "幼児期"],
    "感冒の遷延・長引く微熱": ["乳児期", "幼児期"],
    "中耳炎を繰り返す": ["乳児期", "幼児期"],
    # 追加指示#2で新規追加（暫定・要医学レビュー）
    "咽頭痛・扁桃炎": ["幼児期"],
    "口内炎": ["乳児期", "幼児期"],
    "夜泣き": ["乳児期", "幼児期"],
    "かんしゃく・疳の虫": ["幼児期"],
    "不眠": ["乳児期", "幼児期"],
    "情緒不安定": ["幼児期"],
    "熱性けいれん後の体調不良": ["幼児期"],
    "虚弱体質・疲れやすい": ["幼児期"],
    "食が細い": ["幼児期"],
    "体重増加不良": ["乳児期", "幼児期"],
    "寝汗（盗汗）": ["幼児期"],
    "アトピー性皮膚炎": ["乳児期", "幼児期"],
    "湿疹・おむつかぶれ": ["乳児期", "幼児期"],
    "病後の体力低下": ["幼児期"],
}


# =============================================================================
# 漢方薬データベース（保険適用漢方 - ツムラ番号は暫定値・要添付文書検証）
# 小児科向け27処方（初期案19処方 + 追加指示#2で8処方追加）
#
# 【combinations.avoid の位置づけ】
# 各処方の combinations.avoid は表示・注意喚起のための参考情報である。
# 実際の併用安全性判定は COMBINATION_PATTERNS と check_combination_safety() による
# 生薬量（甘草・麻黄・大黄・附子）の計算・閾値比較で行われ、avoid はどのロジックからも
# 参照されない（誤解を避けるため、追加指示#3にて明記）。
# =============================================================================

KAMPO_DATABASE = {
    "小建中湯": {
        "products": {
            "ツムラ": {"product_no": 99, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証",
        "description": "虚弱体質・腹痛・易疲労に。小児の虚弱体質改善の代表方",
        "indications": {
            "primary": ["腹痛", "虚弱体質・疲れやすい", "食が細い"],
            "secondary": ["便秘・下痢を繰り返す", "夜泣き", "体重増加不良"],
            "off_label": ["乳児疝痛（コリック）"],
        },
        "evidence": {
            "level": "B",  # 暫定: 小児虚弱への使用報告多数、大規模RCTは限定的
            "guideline_grade": "1B",
            "references": [
                "日東医誌 2012;63(4):334-341: 虚弱児への効果",
                "日本東洋医学会 EBM漢方（小児科領域）",
                "ツムラ小建中湯エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.62,  # 暫定値
            "clinical_usage_rank": 1,
        },
        "onset": {
            "initial": "1-2週間",
            "optimal": "4-8週間",
            "type": "chronic",
        },
        "contraindications": ["著明な実証", "嘔吐を繰り返す急性期"],
        "precautions": ["甘草含有製剤併用時", "膠飴含有（甘味）による服薬アドヒアランスへの影響"],
        "combinations": {
            "recommended": ["抑肝散", "六君子湯"],
            "possible": ["黄耆建中湯", "甘麦大棗湯"],
            "avoid": ["芍薬甘草湯"],  # 甘草重複・高含有同士の併用回避
        },
        "side_effects": {
            "common": ["軟便", "胃部不快感"],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": ["偽アルドステロン症（稀）"],
            "note": "甘草2.0g含有。膠飴（水飴）含有で甘く、乳幼児でも服用しやすいことが多い",
        },
        "notes": {
            "age_under_1": "医師相談必須。1歳未満での使用経験はあるが体格差が大きく用量は個別判断。参考情報としてのみ使用可。",
            "age_1_2": "成人1日量の約1/3を目安。腹痛・虚弱の体質改善に用いることが多い。医師判断で調整。",
            "age_3_5": "成人1日量の約1/2を目安。虚弱体質・反復腹痛に比較的よく用いられる。",
            "age_6": "成人1日量の約1/2を目安。学童期移行前の体質改善に。",
            "caution": "膠飴含有で甘く比較的服用しやすい。嫌がる場合は服薬ゼリーやお湯で溶いて冷まして与える。",
        },
        "life_stage_eligible": ["乳児期", "幼児期"],
    },
    "黄耆建中湯": {
        "products": {
            "ツムラ": {"product_no": 98, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証",
        "description": "小建中湯に黄耆を加えた方。盗汗・虚弱が強い児に",
        "indications": {
            "primary": ["虚弱体質・疲れやすい", "寝汗（盗汗）", "病後の体力低下"],
            "secondary": ["食が細い", "体重増加不良"],
            "off_label": [],
        },
        "evidence": {
            "level": "C",  # 暫定
            "guideline_grade": "2B",
            "references": [
                "ツムラ黄耆建中湯エキス顆粒 添付文書",
                "日東医誌: 虚弱児・盗汗への使用報告",
            ],
            "efficacy_rate": 0.55,  # 暫定値
            "clinical_usage_rank": 10,
        },
        "onset": {
            "initial": "2-4週間",
            "optimal": "8-12週間",
            "type": "chronic",
        },
        "contraindications": ["実証", "急性感染症の極期"],
        "precautions": ["甘草含有製剤併用時", "のぼせやすい児"],
        "combinations": {
            "recommended": ["補中益気湯"],
            "possible": ["六君子湯"],
            "avoid": [],
        },
        "side_effects": {
            "common": ["胃部不快感"],
            "rare": ["偽アルドステロン症", "発疹"],
            "serious": ["偽アルドステロン症（稀）"],
            "note": "甘草含有。黄耆による表虚・盗汗への補気固表作用",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則候補外。使用する場合は個別判断のみ。",
            "age_1_2": "成人1日量の約1/3を目安。盗汗・虚弱が強い場合に検討。医師判断必須。",
            "age_3_5": "成人1日量の約1/2を目安。病後の体力低下や盗汗に用いることがある。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "苦味は強くないが、服薬を嫌がる場合は服薬ゼリー等を検討。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "六君子湯": {
        "products": {
            "ツムラ": {"product_no": 43, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証",
        "description": "胃腸虚弱・食欲不振の基本方。食が細い児に",
        "indications": {
            "primary": ["食欲不振", "食が細い", "嘔吐"],
            "secondary": ["下痢", "体重増加不良", "虚弱体質・疲れやすい"],
            "off_label": [],
        },
        "evidence": {
            "level": "A",
            "guideline_grade": "1A",
            "references": [
                "日本消化器病学会 機能性ディスペプシア診療ガイドライン（成人領域・参考）",
                "日東医誌: 小児胃腸虚弱への使用報告",
                "ツムラ六君子湯エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.66,  # 暫定値（小児での厳密な有効率は要検証）
            "clinical_usage_rank": 2,
        },
        "onset": {
            "initial": "1-2週間",
            "optimal": "4-8週間",
            "type": "subacute",
        },
        "contraindications": [],
        "precautions": ["甘草含有製剤併用時"],
        "combinations": {
            "recommended": ["柴胡桂枝湯", "抑肝散加陳皮半夏"],
            "possible": ["補中益気湯", "小建中湯"],
            "avoid": [],
        },
        "side_effects": {
            "common": [],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": ["偽アルドステロン症（稀）"],
            "note": "甘草1.5g含有。四君子湯に陳皮・半夏を加えた処方で胃腸に使いやすい",
        },
        "notes": {
            "age_under_1": "医師相談必須。哺乳不良・嘔吐傾向への使用報告はあるが用量は個別判断。",
            "age_1_2": "成人1日量の約1/3を目安。食が細い・胃腸虚弱の第一選択候補になりやすい。",
            "age_3_5": "成人1日量の約1/2を目安。食欲不振・食が細い児に広く用いられる。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "味は比較的受け入れられやすい。嫌がる場合はお湯で溶いて冷まして与える。",
        },
        "life_stage_eligible": ["乳児期", "幼児期"],
    },
    "人参湯": {
        "products": {
            "ツムラ": {"product_no": 32, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証",
        "description": "胃腸虚弱で冷え・下痢傾向の強い児に。温裏補気の方",
        "indications": {
            "primary": ["下痢", "食欲不振", "便秘・下痢を繰り返す"],
            "secondary": ["虚弱体質・疲れやすい", "嘔吐"],
            "off_label": [],
        },
        "evidence": {
            "level": "C",  # 暫定
            "guideline_grade": "2B",
            "references": [
                "ツムラ人参湯エキス顆粒 添付文書",
                "日東医誌: 虚寒性下痢への使用報告",
            ],
            "efficacy_rate": 0.56,  # 暫定値
            "clinical_usage_rank": 14,
        },
        "onset": {
            "initial": "数日〜1週間",
            "optimal": "2-4週間",
            "type": "subacute",
        },
        "contraindications": ["実証", "熱感が強い児", "急性感染性腸炎の極期"],
        "precautions": ["甘草含有製剤併用時", "のぼせやすい児"],
        "combinations": {
            "recommended": ["五苓散"],
            "possible": ["六君子湯"],
            "avoid": [],
        },
        "side_effects": {
            "common": ["胃部不快感", "のぼせ感"],
            "rare": ["偽アルドステロン症"],
            "serious": ["偽アルドステロン症（稀）"],
            "note": "乾姜・人参による温補作用。熱証には不向き",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則候補外。",
            "age_1_2": "成人1日量の約1/3を目安。冷え・下痢傾向が強い虚証児に検討。",
            "age_3_5": "成人1日量の約1/2を目安。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "生姜系の味で嫌がることがある。服薬ゼリー等を検討。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "桂枝加芍薬湯": {
        "products": {
            "ツムラ": {"product_no": 60, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証",
        "description": "腹痛・腹部膨満・便通異常に。過敏性腸症状様の児に",
        "indications": {
            "primary": ["腹痛", "便秘・下痢を繰り返す", "便秘"],
            "secondary": ["下痢", "食欲不振"],
            "off_label": [],
        },
        "evidence": {
            "level": "B",
            "guideline_grade": "2A",
            "references": [
                "日東医誌: IBS様症状・腹痛への効果（成人領域・参考）",
                "ツムラ桂枝加芍薬湯エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.60,  # 暫定値
            "clinical_usage_rank": 11,
        },
        "onset": {
            "initial": "数日〜1週間",
            "optimal": "2-4週間",
            "type": "subacute",
        },
        "contraindications": [],
        "precautions": ["甘草含有製剤併用時"],
        "combinations": {
            "recommended": ["小建中湯"],
            "possible": ["六君子湯"],
            "avoid": ["芍薬甘草湯"],  # 甘草重複・高含有同士の併用回避
        },
        "side_effects": {
            "common": ["軟便"],
            "rare": ["偽アルドステロン症"],
            "serious": ["偽アルドステロン症（稀）"],
            "note": "甘草2.0g含有。芍薬による鎮痙・鎮痛作用",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則候補外。",
            "age_1_2": "成人1日量の約1/3を目安。反復腹痛・便通異常に検討。",
            "age_3_5": "成人1日量の約1/2を目安。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "比較的服用しやすい。嫌がる場合はお湯で溶いて冷ます。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "五苓散": {
        "products": {
            "ツムラ": {"product_no": 17, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "証を問わない",
        "description": "水滞に。嘔吐・下痢・むくみ・口渇を伴う胃腸炎様症状に",
        "indications": {
            "primary": ["嘔吐", "下痢", "便秘・下痢を繰り返す"],
            "secondary": ["中耳炎を繰り返す", "感冒の遷延・長引く微熱"],
            "off_label": [],
        },
        "evidence": {
            "level": "B",
            "guideline_grade": "1B",
            "references": [
                "日東医誌: 急性胃腸炎・水滞への効果",
                "ツムラ五苓散エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.64,  # 暫定値
            "clinical_usage_rank": 3,
        },
        "onset": {
            "initial": "数時間〜1日",
            "optimal": "数日〜1週間",
            "type": "acute",
        },
        "contraindications": ["脱水が高度な状態（水分補給を優先）"],
        "precautions": ["脱水状態の患者ではまず補液・水分補給を優先"],
        "combinations": {
            "recommended": ["人参湯", "柴胡桂枝湯"],
            "possible": ["小建中湯"],
            "avoid": [],
        },
        "side_effects": {
            "common": [],
            "rare": ["肝機能障害", "発疹"],
            "serious": ["肝機能障害（稀）"],
            "note": "甘草・麻黄・大黄・附子を含まず、副作用は比較的少ない",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児の嘔吐・下痢への使用経験はあるが、脱水評価を最優先。",
            "age_1_2": "成人1日量の約1/3を目安。胃腸炎様の嘔吐・下痢に用いられる。",
            "age_3_5": "成人1日量の約1/2を目安。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "粉っぽい味で嫌がることがある。服薬ゼリーや少量の湯冷ましで溶かす。",
        },
        "life_stage_eligible": ["乳児期", "幼児期"],
    },
    "柴胡桂枝湯": {
        "products": {
            "ツムラ": {"product_no": 10, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "中間証",
        "description": "感冒の遷延・腹痛を伴う体調不良・反復性の発熱傾向に",
        "indications": {
            "primary": ["感冒の遷延・長引く微熱", "腹痛", "中耳炎を繰り返す"],
            "secondary": ["感冒（かぜ）初期", "食欲不振", "熱性けいれん後の体調不良"],
            "off_label": [],
        },
        "evidence": {
            "level": "B",  # 暫定: 小児腹痛・感冒遷延で使用報告あり
            "guideline_grade": "2A",
            "references": [
                "日東医誌: 小児反復性腹痛・感冒遷延への使用報告",
                "ツムラ柴胡桂枝湯エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.61,  # 暫定値
            "clinical_usage_rank": 4,
        },
        "onset": {
            "initial": "数日〜1週間",
            "optimal": "1-3週間",
            "type": "subacute",
        },
        "contraindications": ["著明な虚証で極度に体力低下している児"],
        "precautions": ["甘草含有製剤併用時", "間質性肺炎の既往"],
        "combinations": {
            "recommended": ["六君子湯", "五苓散"],
            "possible": ["小柴胡湯"],
            "avoid": [],
        },
        "side_effects": {
            "common": ["胃部不快感", "軟便"],
            "rare": ["偽アルドステロン症", "間質性肺炎", "肝機能障害"],
            "serious": ["間質性肺炎（稀）", "偽アルドステロン症"],
            "note": "柴胡含有。長期投与時は肝機能・呼吸器症状に注意",
        },
        "notes": {
            "age_under_1": "医師相談必須。使用経験は限定的。発熱・感染の除外診断を優先。",
            "age_1_2": "成人1日量の約1/3を目安。遷延感冒・反復腹痛に検討。",
            "age_3_5": "成人1日量の約1/2を目安。小児科で比較的よく用いられる方剤の一つ。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "苦味があり嫌がることがある。服薬ゼリー推奨。",
        },
        "life_stage_eligible": ["乳児期", "幼児期"],
    },
    "麦門冬湯": {
        "products": {
            "ツムラ": {"product_no": 29, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証〜中間証",
        "description": "乾性咳嗽・痰の少ない咳・咽の乾燥感に",
        "indications": {
            "primary": ["咳（乾性）"],
            "secondary": ["感冒の遷延・長引く微熱", "喘息傾向"],
            "off_label": [],
        },
        "evidence": {
            "level": "B",
            "guideline_grade": "2A",
            "references": [
                "日本呼吸器学会 咳嗽ガイドライン（成人領域・参考）",
                "ツムラ麦門冬湯エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.63,  # 暫定値
            "clinical_usage_rank": 8,
        },
        "onset": {
            "initial": "数日〜1週間",
            "optimal": "1-3週間",
            "type": "subacute",
        },
        "contraindications": ["湿性咳嗽で痰が多い場合（方意に合わない）"],
        "precautions": ["甘草含有製剤併用時"],
        "combinations": {
            "recommended": [],
            "possible": ["小柴胡湯", "補中益気湯"],
            "avoid": ["五虎湯"],  # 方意が異なるため安易な併用は避ける
        },
        "side_effects": {
            "common": ["胃部不快感", "食欲不振"],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": ["偽アルドステロン症（稀）"],
            "note": "甘草1.0g含有。粳米含有で甘みがあり比較的服用しやすい",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則候補外。咳の鑑別（感染・異物等）を優先。",
            "age_1_2": "成人1日量の約1/3を目安。乾性咳嗽に検討。",
            "age_3_5": "成人1日量の約1/2を目安。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "比較的甘みがあり服用しやすい。嫌がる場合はお湯で溶いて冷ます。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "五虎湯": {
        "products": {
            "ツムラ": {"product_no": 95, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "中間証〜実証",
        "description": "喘鳴を伴う咳嗽・呼吸困難感に。麻黄含有のため乳幼児では慎重投与",
        "indications": {
            "primary": ["喘息傾向", "咳（湿性・痰がらみ）"],
            "secondary": ["咳（乾性）"],
            "off_label": [],
        },
        "evidence": {
            "level": "C",  # 暫定
            "guideline_grade": "2C",
            "references": [
                "ツムラ五虎湯エキス顆粒 添付文書",
                "日東医誌: 小児喘息様症状への使用報告（限定的）",
            ],
            "efficacy_rate": 0.52,  # 暫定値
            "clinical_usage_rank": 16,
        },
        "onset": {
            "initial": "数時間〜数日",
            "optimal": "数日〜1週間",
            "type": "acute",
        },
        "contraindications": ["虚証", "著しい体力低下", "心疾患", "甲状腺機能亢進"],
        "precautions": [
            "乳幼児での慎重投与",  # 麻黄含有・必須記載
            "麻黄含有製剤併用時",
            "動悸・不眠・発汗の出現に注意",
            "他の麻黄含有方剤との併用は原則避ける",
        ],
        "combinations": {
            "recommended": [],
            "possible": ["小柴胡湯"],
            "avoid": ["小青竜湯", "葛根湯", "越婢加朮湯", "麻黄湯", "五積散", "麦門冬湯"],  # 麻黄重複
        },
        "side_effects": {
            "common": ["動悸", "不眠", "発汗", "興奮"],
            "rare": ["偽アルドステロン症", "排尿障害"],
            "serious": ["交感神経刺激症状の増強", "偽アルドステロン症"],
            "note": "麻黄・甘草含有。乳幼児は麻黄感受性が高く特に注意",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則候補外。麻黄含有のため原則使用しない。",
            "age_1_2": "成人1日量の約1/3を目安。麻黄含有のため慎重投与。動悸・不眠に注意。",
            "age_3_5": "成人1日量の約1/2を目安。喘鳴・湿性咳嗽で実証寄りに限る。",
            "age_6": "成人1日量の約1/2を目安。慎重投与。",
            "caution": "苦味・麻黄の刺激で嫌がることが多い。服薬ゼリー推奨。興奮・不眠時は中止検討。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "小青竜湯": {
        "products": {
            "ツムラ": {"product_no": 19, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証〜中間証",
        "description": "水様鼻汁・くしゃみ・喘鳴を伴う咳嗽に。麻黄含有のため乳幼児では慎重投与",
        "indications": {
            "primary": ["鼻水・鼻づまり", "咳（湿性・痰がらみ）", "喘息傾向"],
            "secondary": ["感冒（かぜ）初期"],
            "off_label": [],
        },
        "evidence": {
            "level": "B",
            "guideline_grade": "2A",
            "references": [
                "アレルギー性鼻炎・感冒への使用報告",
                "ツムラ小青竜湯エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.60,  # 暫定値
            "clinical_usage_rank": 9,
        },
        "onset": {
            "initial": "数時間〜数日",
            "optimal": "数日〜2週間",
            "type": "acute",
        },
        "contraindications": ["胃腸虚弱が著明", "口渇が強い燥証"],
        "precautions": [
            "乳幼児での慎重投与",  # 麻黄含有・必須記載
            "麻黄含有製剤併用時",
            "甘草含有量が比較的多い",
            "動悸・不眠・発汗に注意",
        ],
        "combinations": {
            "recommended": [],
            "possible": ["五苓散"],
            "avoid": ["五虎湯", "葛根湯", "越婢加朮湯", "麻黄湯", "五積散"],  # 麻黄重複
        },
        "side_effects": {
            "common": ["動悸", "胃部不快感", "発汗", "不眠"],
            "rare": ["偽アルドステロン症", "排尿障害"],
            "serious": ["偽アルドステロン症", "交感神経刺激症状の増強"],
            "note": "麻黄・甘草含有（甘草量が多め）。乳幼児では慎重投与",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則候補外。麻黄含有のため原則使用しない。",
            "age_1_2": "成人1日量の約1/3を目安。水様鼻汁・湿性咳嗽に限って慎重検討。",
            "age_3_5": "成人1日量の約1/2を目安。慎重投与。",
            "age_6": "成人1日量の約1/2を目安。慎重投与。",
            "caution": "味が強く嫌がることが多い。服薬ゼリー推奨。興奮時は中止検討。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "葛根湯": {
        "products": {
            "ツムラ": {"product_no": 1, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "実証",
        "description": "感冒初期の悪寒・項背部のこわばりに。麻黄含有のため乳幼児では慎重投与",
        "indications": {
            "primary": ["感冒（かぜ）初期"],
            "secondary": ["鼻水・鼻づまり", "中耳炎を繰り返す"],
            "off_label": [],
        },
        "evidence": {
            "level": "B",
            "guideline_grade": "2A",
            "references": [
                "感冒初期への古典的使用・臨床報告",
                "ツムラ葛根湯エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.58,  # 暫定値
            "clinical_usage_rank": 12,
        },
        "onset": {
            "initial": "数時間〜1日",
            "optimal": "1-3日",
            "type": "acute",
        },
        "contraindications": ["虚証", "著しい体力低下", "発汗過多の状態"],
        "precautions": [
            "乳幼児での慎重投与",  # 麻黄含有・必須記載
            "麻黄含有製剤併用時",
            "発汗後の脱水に注意",
            "実証寄りの感冒初期に限る",
        ],
        "combinations": {
            "recommended": [],
            "possible": [],
            "avoid": ["五虎湯", "小青竜湯", "越婢加朮湯", "麻黄湯", "五積散"],  # 麻黄重複
        },
        "side_effects": {
            "common": ["発汗", "動悸", "胃部不快感"],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": ["偽アルドステロン症", "交感神経刺激症状の増強"],
            "note": "麻黄・甘草含有。発汗を促すため虚証児には不向き",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則候補外。麻黄含有のため原則使用しない。",
            "age_1_2": "成人1日量の約1/3を目安。体力があり実証寄りの感冒初期に限って慎重検討。",
            "age_3_5": "成人1日量の約1/2を目安。慎重投与。",
            "age_6": "成人1日量の約1/2を目安。慎重投与。",
            "caution": "苦味が強く嫌がることが多い。服薬ゼリー推奨。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "小柴胡湯": {
        "products": {
            "ツムラ": {"product_no": 9, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "中間証",
        "description": "感冒の遷延・微熱・胸脇苦満様の不調・中耳炎反復に",
        "indications": {
            "primary": ["感冒の遷延・長引く微熱", "中耳炎を繰り返す"],
            "secondary": ["食欲不振", "熱性けいれん後の体調不良"],
            "off_label": [],
        },
        "evidence": {
            "level": "B",
            "guideline_grade": "2A",
            "references": [
                "日東医誌: 小児遷延感冒・中耳炎への使用報告",
                "ツムラ小柴胡湯エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.59,  # 暫定値
            "clinical_usage_rank": 5,
        },
        "onset": {
            "initial": "数日〜1週間",
            "optimal": "1-3週間",
            "type": "subacute",
        },
        "contraindications": ["インターフェロン製剤併用", "肝硬変・肝腫瘍等（成人領域の注意を準用）"],
        "precautions": ["間質性肺炎の既往", "甘草含有製剤併用時", "長期投与時の肝機能モニタリング"],
        "combinations": {
            "recommended": ["五苓散"],  # 柴苓湯的な発想（参考）
            "possible": ["柴胡桂枝湯", "六君子湯"],
            "avoid": [],
        },
        "side_effects": {
            "common": ["胃部不快感", "軟便"],
            "rare": ["間質性肺炎", "肝機能障害", "偽アルドステロン症"],
            "serious": ["間質性肺炎", "肝機能障害"],
            "note": "柴胡含有。間質性肺炎は稀だが咳嗽・呼吸困難出現時は中止し精査",
        },
        "notes": {
            "age_under_1": "医師相談必須。使用経験は限定的。感染の除外診断を優先。",
            "age_1_2": "成人1日量の約1/3を目安。遷延感冒・反復中耳炎に検討。",
            "age_3_5": "成人1日量の約1/2を目安。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "苦味があり嫌がることが多い。服薬ゼリー推奨。",
        },
        "life_stage_eligible": ["乳児期", "幼児期"],
    },
    "抑肝散": {
        "products": {
            "ツムラ": {"product_no": 54, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証〜中間証",
        "description": "夜泣き・かんしゃく・神経の高ぶりに。小児科で頻用される方剤",
        "indications": {
            "primary": ["夜泣き", "かんしゃく・疳の虫", "情緒不安定"],
            "secondary": ["不眠", "熱性けいれん後の体調不良"],
            "off_label": [],
        },
        "evidence": {
            "level": "B",  # 小児夜泣き・疳の虫での使用実績は豊富、RCTは限定的
            "guideline_grade": "1B",
            "references": [
                "日本小児心身医学会 関連報告",
                "日東医誌: 小児夜泣き・疳の虫への効果",
                "ツムラ抑肝散エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.65,  # 暫定値
            "clinical_usage_rank": 1,
        },
        "onset": {
            "initial": "数日〜2週間",
            "optimal": "2-6週間",
            "type": "subacute",
        },
        "contraindications": [],
        "precautions": ["甘草含有製剤併用時", "低カリウム血症"],
        "combinations": {
            "recommended": ["小建中湯", "甘麦大棗湯"],
            "possible": ["六君子湯"],
            "avoid": [],
        },
        "side_effects": {
            "common": ["食欲不振", "胃部不快感", "傾眠"],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": ["偽アルドステロン症"],
            "note": "甘草1.5g含有。胃腸虚弱児には抑肝散加陳皮半夏を検討",
        },
        "notes": {
            "age_under_1": "医師相談必須。夜泣きへの使用経験はあるが、器質的疾患・養育環境の評価を優先。",
            "age_1_2": "成人1日量の約1/3を目安。夜泣き・かんしゃくに頻用。",
            "age_3_5": "成人1日量の約1/2を目安。かんしゃく・情緒不安定に用いられる。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "味は強くないが嫌がる場合は服薬ゼリー。就寝前投与が選択されることもある。",
        },
        "life_stage_eligible": ["乳児期", "幼児期"],
    },
    "抑肝散加陳皮半夏": {
        "products": {
            "ツムラ": {"product_no": 83, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証",
        "description": "抑肝散に胃腸保護を加えた方。胃腸虚弱で神経症状のある児に",
        "indications": {
            "primary": ["夜泣き", "かんしゃく・疳の虫", "情緒不安定"],
            "secondary": ["不眠", "食欲不振", "食が細い"],
            "off_label": [],
        },
        "evidence": {
            "level": "B",
            "guideline_grade": "2A",
            "references": [
                "日東医誌: 胃腸虚弱例の神経症状への効果",
                "ツムラ抑肝散加陳皮半夏エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.60,  # 暫定値
            "clinical_usage_rank": 6,
        },
        "onset": {
            "initial": "数日〜2週間",
            "optimal": "2-6週間",
            "type": "subacute",
        },
        "contraindications": [],
        "precautions": ["甘草含有製剤併用時"],
        "combinations": {
            "recommended": ["六君子湯", "小建中湯"],
            "possible": ["甘麦大棗湯"],
            "avoid": [],
        },
        "side_effects": {
            "common": ["傾眠"],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": ["偽アルドステロン症"],
            "note": "抑肝散より胃腸への負担は軽減。甘草1.5g含有",
        },
        "notes": {
            "age_under_1": "医師相談必須。胃腸虚弱を伴う夜泣きで検討されることがある。",
            "age_1_2": "成人1日量の約1/3を目安。胃腸虚弱＋神経症状に適する。",
            "age_3_5": "成人1日量の約1/2を目安。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "抑肝散より飲みやすいことが多い。嫌がる場合は服薬ゼリー。",
        },
        "life_stage_eligible": ["乳児期", "幼児期"],
    },
    "甘麦大棗湯": {
        "products": {
            "ツムラ": {"product_no": 72, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証",
        "description": "夜泣き・ひきつけ様の興奮・情緒不安定に。甘く服用しやすいが甘草量に注意",
        "indications": {
            "primary": ["夜泣き", "情緒不安定", "かんしゃく・疳の虫"],
            "secondary": ["不眠", "熱性けいれん後の体調不良"],
            "off_label": [],
        },
        "evidence": {
            "level": "C",  # 暫定: 古典的使用・症例報告中心
            "guideline_grade": "2B",
            "references": [
                "日東医誌: 小児夜泣き・臟躁様症状への使用報告",
                "ツムラ甘麦大棗湯エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.57,  # 暫定値
            "clinical_usage_rank": 7,
        },
        "onset": {
            "initial": "数日〜2週間",
            "optimal": "2-4週間",
            "type": "subacute",
        },
        "contraindications": [],
        "precautions": [
            "甘草含有量が多く（5.0g）、単剤でも偽アルドステロン症に注意",
            "他の甘草含有方剤との併用は特に慎重に",
        ],
        "combinations": {
            "recommended": ["抑肝散", "小建中湯"],
            "possible": [],
            "avoid": ["芍薬甘草湯"],  # 甘草重複・高含有同士の併用回避
        },
        "side_effects": {
            "common": ["浮腫", "軟便"],
            "rare": ["偽アルドステロン症", "低カリウム血症"],
            "serious": ["偽アルドステロン症（甘草高含有のため注意）"],
            "note": "甘草5.0gと高含有。単剤でも閾値超過しやすい。併用時は特に注意",
        },
        "notes": {
            "age_under_1": "医師相談必須。甘いが甘草量が多く、電解質・浮腫に注意。",
            "age_1_2": "成人1日量の約1/3を目安。甘草高含有のため短期・慎重投与。",
            "age_3_5": "成人1日量の約1/2を目安。甘草量に留意。",
            "age_6": "成人1日量の約1/2を目安。甘草量に留意。",
            "caution": "小麦・大棗・甘草で甘く服用しやすい。むしろ過量服用に注意。",
        },
        "life_stage_eligible": ["乳児期", "幼児期"],
    },
    "補中益気湯": {
        "products": {
            "ツムラ": {"product_no": 41, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証",
        "description": "気虚の基本方。疲れやすい・食が細い・病後の回復に",
        "indications": {
            "primary": ["虚弱体質・疲れやすい", "病後の体力低下", "食が細い"],
            "secondary": ["食欲不振", "中耳炎を繰り返す", "寝汗（盗汗）"],
            "off_label": [],
        },
        "evidence": {
            "level": "B",
            "guideline_grade": "1B",
            "references": [
                "日東医誌: 小児虚弱・病後回復への使用報告",
                "ツムラ補中益気湯エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.63,  # 暫定値
            "clinical_usage_rank": 5,
        },
        "onset": {
            "initial": "2-4週間",
            "optimal": "6-12週間",
            "type": "chronic",
        },
        "contraindications": ["実証", "急性熱性疾患の極期"],
        "precautions": ["甘草含有製剤併用時", "のぼせやすい児"],
        "combinations": {
            "recommended": ["六君子湯", "十全大補湯"],
            "possible": ["黄耆建中湯"],
            "avoid": [],
        },
        "side_effects": {
            "common": ["胃部不快感", "のぼせ感"],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": ["偽アルドステロン症"],
            "note": "甘草1.5g含有。升提作用があるためのぼせやすい児には注意",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則候補外。",
            "age_1_2": "成人1日量の約1/3を目安。虚弱・病後回復に検討。",
            "age_3_5": "成人1日量の約1/2を目安。反復感染傾向の虚弱児に用いられることがある。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "苦味があり嫌がることがある。服薬ゼリーやお湯で溶いて冷ます。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "十全大補湯": {
        "products": {
            "ツムラ": {"product_no": 48, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証",
        "description": "気血両虚に。病後・手術後・強度の虚弱に",
        "indications": {
            "primary": ["病後の体力低下", "虚弱体質・疲れやすい", "体重増加不良"],
            "secondary": ["食が細い", "寝汗（盗汗）"],
            "off_label": [],
        },
        "evidence": {
            "level": "B",
            "guideline_grade": "2A",
            "references": [
                "日東医誌: 病後回復・虚弱への効果",
                "ツムラ十全大補湯エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.58,  # 暫定値
            "clinical_usage_rank": 13,
        },
        "onset": {
            "initial": "2-4週間",
            "optimal": "8-12週間",
            "type": "chronic",
        },
        "contraindications": ["実証", "のぼせが強い児", "急性炎症の極期"],
        "precautions": ["甘草含有製剤併用時", "のぼせ・高血圧傾向"],
        "combinations": {
            "recommended": ["補中益気湯"],
            "possible": ["六君子湯"],
            "avoid": [],
        },
        "side_effects": {
            "common": ["胃部不快感", "食欲不振", "のぼせ感"],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": ["偽アルドステロン症"],
            "note": "甘草1.5g含有。温補作用が強いためのぼせやすい児には不向き",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則候補外。",
            "age_1_2": "成人1日量の約1/3を目安。強度の虚弱・病後に限って検討。",
            "age_3_5": "成人1日量の約1/2を目安。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "地黄等で胃もたれしやすい。服薬ゼリー・食後投与を検討。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "消風散": {
        "products": {
            "ツムラ": {"product_no": 22, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "中間証〜実証",
        "description": "かゆみの強い湿疹・皮膚炎に。湿熱・風湿の皮膚症状向け",
        "indications": {
            "primary": ["アトピー性皮膚炎", "湿疹・おむつかぶれ"],
            "secondary": [],
            "off_label": [],
        },
        "evidence": {
            "level": "C",  # 暫定
            "guideline_grade": "2B",
            "references": [
                "日東医誌: 湿疹・皮膚炎への使用報告",
                "ツムラ消風散エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.54,  # 暫定値
            "clinical_usage_rank": 15,
        },
        "onset": {
            "initial": "1-2週間",
            "optimal": "4-8週間",
            "type": "subacute",
        },
        "contraindications": ["虚証", "胃腸虚弱が著明"],
        "precautions": ["甘草含有製剤併用時", "長期連用時の肝機能"],
        "combinations": {
            "recommended": [],
            "possible": ["越婢加朮湯"],
            "avoid": [],
        },
        "side_effects": {
            "common": ["胃部不快感", "軟便", "下痢"],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": ["肝機能障害"],
            "note": "苦味が強く、胃腸への負担あり。虚証児には不向きなことあり",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則候補外。皮膚症状の鑑別・外用治療を優先。",
            "age_1_2": "成人1日量の約1/3を目安。かゆみの強い湿疹で中間証〜実証に検討。",
            "age_3_5": "成人1日量の約1/2を目安。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "苦味が非常に強く嫌がることが多い。服薬ゼリー必須級。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "越婢加朮湯": {
        "products": {
            "ツムラ": {"product_no": 28, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "実証",
        "description": "熱感・腫脹を伴う湿疹・浮腫傾向に。麻黄含有のため乳幼児では慎重投与",
        "indications": {
            "primary": ["アトピー性皮膚炎", "湿疹・おむつかぶれ"],
            "secondary": ["喘息傾向"],
            "off_label": [],
        },
        "evidence": {
            "level": "C",
            "guideline_grade": "2C",
            "references": [
                "日東医誌: 湿疹・浮腫への効果",
                "ツムラ越婢加朮湯エキス顆粒 添付文書",
            ],
            "efficacy_rate": 0.53,  # 暫定値
            "clinical_usage_rank": 17,
        },
        "onset": {
            "initial": "数日〜2週間",
            "optimal": "2-6週間",
            "type": "subacute",
        },
        "contraindications": ["虚証", "体力低下", "心疾患"],
        "precautions": [
            "乳幼児での慎重投与",  # 麻黄含有・必須記載
            "麻黄含有製剤併用時",
            "高血圧・心疾患",
            "動悸・不眠・発汗に注意",
        ],
        "combinations": {
            "recommended": [],
            "possible": ["消風散"],
            "avoid": ["五虎湯", "小青竜湯", "葛根湯", "麻黄湯", "五積散"],  # 麻黄重複
        },
        "side_effects": {
            "common": ["動悸", "不眠", "発汗"],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": ["偽アルドステロン症", "交感神経刺激症状の増強"],
            "note": "麻黄6.0g・甘草2.0gと麻黄量が特に多い。乳幼児では最慎重",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則候補外。麻黄量が多く原則使用しない。",
            "age_1_2": "成人1日量の約1/3を目安。麻黄量が多く原則慎重・短期間。",
            "age_3_5": "成人1日量の約1/2を目安。実証で熱感・腫脹が明らかな場合に限る。",
            "age_6": "成人1日量の約1/2を目安。慎重投与。",
            "caution": "苦味・麻黄刺激で嫌がることが多い。興奮・不眠時は直ちに中止検討。",
        },
        "life_stage_eligible": ["幼児期"],
    },

    # =========================================================================
    # 追加指示#2（2026-08-09）で追加された8処方
    # ツムラ番号・生薬量・エビデンス・life_stage_eligible は既存19処方と同様に暫定値。
    # 実運用前に添付文書・インタビューフォームでの検証が必須。
    # =========================================================================
    "麻黄湯": {
        "products": {
            "ツムラ": {"product_no": 27, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "実証",
        "description": "感冒・インフルエンザ様の初期、悪寒・発熱・関節痛が強い実証の児に。麻黄含有のため乳幼児では慎重投与",
        "indications": {
            "primary": ["感冒（かぜ）初期"],
            "secondary": ["咳（乾性）"],
            "off_label": [],
        },
        "evidence": {
            "level": "B",
            "guideline_grade": "2B",
            "references": [
                "ツムラ麻黄湯エキス顆粒 添付文書・インタビューフォーム",
                "日東医誌: インフルエンザ様症状への効果",
            ],
            "efficacy_rate": 0.60,  # 暫定値
            "clinical_usage_rank": 25,
        },
        "onset": {
            "initial": "数時間〜1日",
            "optimal": "1-3日",
            "type": "acute",
        },
        "contraindications": ["虚証", "著明な体力低下", "心疾患"],
        "precautions": [
            "乳幼児での慎重投与",  # 麻黄含有・必須記載
            "麻黄含有製剤併用時",
            "高血圧・心疾患",
            "発汗過多・食欲不振時は中止検討",
        ],
        "combinations": {
            "recommended": [],
            "possible": [],
            "avoid": ["五虎湯", "小青竜湯", "葛根湯", "越婢加朮湯", "五積散"],  # 麻黄重複
        },
        "side_effects": {
            "common": ["胃部不快感", "発汗"],
            "rare": ["動悸", "不眠", "偽アルドステロン症"],
            "serious": ["交感神経刺激症状の増強"],
            "note": "麻黄・甘草量は暫定値。乳幼児は成人より麻黄への感受性が高い可能性があり要注意",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則使用しない（エビデンス・使用実績が特に限定的）。",
            "age_1_2": "原則慎重。発熱・悪寒が強い実証相当の場合に医師判断のもと短期間のみ検討。",
            "age_3_5": "成人1日量の約1/2を目安。短期間の使用に限り、発汗・不眠に注意。",
            "age_6": "成人1日量の約1/2を目安。短期間の使用に限る。",
            "caution": "苦味があり乳幼児が嫌がる場合がある。服薬ゼリー等の活用を検討。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "桔梗湯": {
        "products": {
            "ツムラ": {"product_no": 138, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "実証〜中間証",
        "description": "咽頭痛・扁桃炎の急性期に。甘草含有量が多めのため長期連用は避ける",
        "indications": {
            "primary": ["咽頭痛・扁桃炎"],
            "secondary": [],
            "off_label": [],
        },
        "evidence": {
            "level": "C",
            "guideline_grade": "2B",
            "references": [
                "ツムラ桔梗湯エキス顆粒 添付文書・インタビューフォーム",
                "日東医誌: 咽頭痛・扁桃炎への効果",
            ],
            "efficacy_rate": 0.55,  # 暫定値
            "clinical_usage_rank": 33,
        },
        "onset": {
            "initial": "数時間〜1日",
            "optimal": "3-7日",
            "type": "acute",
        },
        "contraindications": [],
        "precautions": ["甘草含有製剤併用時", "長期連用を避ける"],
        "combinations": {
            "recommended": [],
            "possible": ["小柴胡湯"],
            "avoid": ["芍薬甘草湯"],  # 甘草重複・高含有同士の併用回避
        },
        "side_effects": {
            "common": ["胃部不快感"],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": ["偽アルドステロン症（甘草高含有のため長期連用時に注意）"],
            "note": "甘草含有量が多め（暫定3.0g・要IF検証）。頓用〜短期使用が中心",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則候補外（甘草量が多く使用実績が限定的）。",
            "age_1_2": "成人1日量の約1/3を目安。短期間の使用に限る。",
            "age_3_5": "成人1日量の約1/2を目安。含嗽代わりに少量ずつ服用させる工夫も検討。",
            "age_6": "成人1日量の約1/2を目安。短期間の使用に限る。",
            "caution": "苦味が強く、白湯に溶いて冷ましてから少量ずつ与えるなどの工夫が必要な場合がある。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "温清飲": {
        "products": {
            "ツムラ": {"product_no": 57, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "中間証〜虚証",
        "description": "血虚・血熱によるアトピー性皮膚炎・湿疹に。麻黄・大黄・附子は含まない想定",
        "indications": {
            "primary": ["アトピー性皮膚炎"],
            "secondary": ["湿疹・おむつかぶれ"],
            "off_label": [],
        },
        "evidence": {
            "level": "C",
            "guideline_grade": "2B",
            "references": [
                "ツムラ温清飲エキス顆粒 添付文書・インタビューフォーム",
                "日東医誌: 皮膚症状への効果",
            ],
            "efficacy_rate": 0.52,  # 暫定値
            "clinical_usage_rank": 34,
        },
        "onset": {
            "initial": "2-4週間",
            "optimal": "8-12週間",
            "type": "chronic",
        },
        "contraindications": [],
        "precautions": ["消化器症状のある患者", "長期連用時（5年以上）は経過観察が望ましい"],
        "combinations": {
            "recommended": [],
            "possible": ["消風散"],
            "avoid": [],
        },
        "side_effects": {
            "common": ["胃部不快感", "下痢"],
            "rare": ["肝機能障害"],
            "serious": ["腸間膜静脈硬化症（長期連用5年以上・山梔子含有製剤で報告例）"],
            "note": "麻黄・大黄・附子は含まない想定（要IF検証）。山梔子含有のため長期連用時は経過観察",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は使用実績が限定的。",
            "age_1_2": "成人1日量の約1/3を目安。",
            "age_3_5": "成人1日量の約1/2を目安。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "苦味があり継続服用を嫌がる場合は服薬ゼリー等を検討。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "柴朴湯": {
        "products": {
            "ツムラ": {"product_no": 96, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "中間証",
        "description": "小柴胡湯と半夏厚朴湯の合方。喘息傾向・咳嗽の遷延に不安・咽喉頭異物感を伴う場合に",
        "indications": {
            "primary": ["喘息傾向"],
            "secondary": ["咳（湿性・痰がらみ）", "感冒の遷延・長引く微熱"],
            "off_label": [],
        },
        "evidence": {
            "level": "B",
            "guideline_grade": "2A",
            "references": [
                "ツムラ柴朴湯エキス顆粒 添付文書・インタビューフォーム",
                "日東医誌: 小児気管支喘息への効果",
            ],
            "efficacy_rate": 0.58,  # 暫定値
            "clinical_usage_rank": 28,
        },
        "onset": {
            "initial": "1-2週間",
            "optimal": "4-8週間",
            "type": "subacute",
        },
        "contraindications": [],
        "precautions": ["甘草含有製剤併用時", "間質性肺炎の既往"],
        "combinations": {
            "recommended": [],
            "possible": ["五苓散"],
            "avoid": [],
        },
        "side_effects": {
            "common": ["胃部不快感"],
            "rare": ["間質性肺炎", "肝機能障害", "偽アルドステロン症"],
            "serious": ["間質性肺炎（稀）"],
            "note": "小柴胡湯由来の柴胡・黄芩と半夏厚朴湯由来の生薬を含む合方",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は使用実績が限定的なため原則候補外。",
            "age_1_2": "成人1日量の約1/3を目安。",
            "age_3_5": "成人1日量の約1/2を目安。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "咳・呼吸苦が持続する場合は基礎疾患の除外を優先し、漫然投与を避ける。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "半夏瀉心湯": {
        "products": {
            "ツムラ": {"product_no": 14, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "中間証",
        "description": "口内炎・下痢に。心下痞（胃部のつかえ）を伴う場合に用いる",
        "indications": {
            "primary": ["口内炎"],
            "secondary": ["下痢"],
            "off_label": [],
        },
        "evidence": {
            "level": "C",
            "guideline_grade": "2B",
            "references": [
                "ツムラ半夏瀉心湯エキス顆粒 添付文書・インタビューフォーム",
                "日東医誌: 口内炎・下痢への効果",
            ],
            "efficacy_rate": 0.54,  # 暫定値
            "clinical_usage_rank": 31,
        },
        "onset": {
            "initial": "数日〜1週間",
            "optimal": "2-4週間",
            "type": "subacute",
        },
        "contraindications": [],
        "precautions": ["甘草含有製剤併用時"],
        "combinations": {
            "recommended": [],
            "possible": ["六君子湯"],
            "avoid": [],
        },
        "side_effects": {
            "common": ["胃部不快感", "下痢の悪化（稀）"],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": ["偽アルドステロン症（稀）"],
            "note": "甘草含有（暫定2.5g・要IF検証）。口内炎への外用（塗布）用法もあるが本アプリは内服を前提とする",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は使用実績が限定的なため原則候補外。",
            "age_1_2": "成人1日量の約1/3を目安。",
            "age_3_5": "成人1日量の約1/2を目安。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "苦味が強く内服を嫌がりやすい。白湯に溶いて冷ます、服薬ゼリーの活用等を検討。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "芍薬甘草湯": {
        "products": {
            "ツムラ": {"product_no": 68, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "証を問わない",
        "description": "急な痙攣性の腹痛に頓用で用いる。甘草含有量が非常に多いため長期連用は避ける",
        "indications": {
            "primary": ["腹痛"],
            "secondary": [],
            "off_label": [],
        },
        "evidence": {
            "level": "B",
            "guideline_grade": "2A",
            "references": [
                "ツムラ芍薬甘草湯エキス顆粒 添付文書・インタビューフォーム",
                "日東医誌: 急性腹痛・こむら返りへの効果",
            ],
            "efficacy_rate": 0.63,  # 暫定値
            "clinical_usage_rank": 20,
        },
        "onset": {
            "initial": "数十分〜数時間（頓用）",
            "optimal": "頓用のため該当なし",
            "type": "acute",
        },
        "contraindications": [],
        "precautions": [
            "甘草含有量が非常に多く、他の甘草含有製剤との併用・連用に厳重注意",
            "長期連用を避け、頓用を基本とする",
        ],
        "combinations": {
            "recommended": [],
            "possible": [],
            "avoid": ["甘麦大棗湯", "桔梗湯", "小建中湯", "桂枝加芍薬湯"],  # 甘草重複・高含有同士の併用回避
        },
        "side_effects": {
            "common": ["胃部不快感"],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": ["偽アルドステロン症（低K血症、血圧上昇）"],
            "note": "甘草6.0g/日と単剤でも高含有。頓用的な使用が中心であり、連日長期の使用は避けること",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則使用しない（甘草量が多く使用実績が特に限定的）。",
            "age_1_2": "成人1日量の約1/3を目安に頓用。連用しない。",
            "age_3_5": "成人1日量の約1/2を目安に頓用。連用しない。",
            "age_6": "成人1日量の約1/2を目安に頓用。連用しない。",
            "caution": "頓用が基本。腹痛が頻回・持続する場合は他疾患の除外を優先し、漫然と連用しないこと。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "五積散": {
        "products": {
            "ツムラ": {"product_no": 63, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証〜中間証",
        "description": "冷えを伴う感冒・体の痛みに。麻黄含有のため乳幼児では慎重投与",
        "indications": {
            "primary": ["感冒（かぜ）初期"],
            "secondary": [],
            "off_label": [],
        },
        "evidence": {
            "level": "C",
            "guideline_grade": "2C",
            "references": [
                "ツムラ五積散エキス顆粒 添付文書・インタビューフォーム",
            ],
            "efficacy_rate": 0.50,  # 暫定値
            "clinical_usage_rank": 38,
        },
        "onset": {
            "initial": "数時間〜1日",
            "optimal": "3-7日",
            "type": "acute",
        },
        "contraindications": ["著明な実証", "高血圧・心疾患"],
        "precautions": [
            "乳幼児での慎重投与",  # 麻黄含有・必須記載
            "麻黄含有製剤併用時",
        ],
        "combinations": {
            "recommended": [],
            "possible": [],
            "avoid": ["五虎湯", "小青竜湯", "葛根湯", "越婢加朮湯", "麻黄湯"],  # 麻黄重複
        },
        "side_effects": {
            "common": ["胃部不快感"],
            "rare": ["動悸", "不眠", "発汗", "偽アルドステロン症"],
            "serious": ["交感神経刺激症状の増強"],
            "note": "麻黄2.0g・甘草1.0g含有（既存の麻黄含有処方と同様の慎重投与が必要）",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は原則使用しない。",
            "age_1_2": "原則慎重。医師判断のもと短期間のみ検討。",
            "age_3_5": "成人1日量の約1/2を目安。短期間の使用に限る。",
            "age_6": "成人1日量の約1/2を目安。短期間の使用に限る。",
            "caution": "他の麻黄含有処方との併用は避けること。",
        },
        "life_stage_eligible": ["幼児期"],
    },
    "参蘇飲": {
        "products": {
            "ツムラ": {"product_no": 66, "available": True},
            "クラシエ": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
            "コタロー": {"product_no": None, "available": True},  # 暫定: 製品番号未確認・取扱有無要確認（要IF検証）
        },
        "insurance": True,
        "sho": "虚証",
        "description": "胃腸虚弱を伴う感冒に。麻黄は含まない想定で虚証の児に用いやすい",
        "indications": {
            "primary": ["感冒（かぜ）初期", "感冒の遷延・長引く微熱"],
            "secondary": ["食欲不振"],
            "off_label": [],
        },
        "evidence": {
            "level": "C",
            "guideline_grade": "2B",
            "references": [
                "ツムラ参蘇飲エキス顆粒 添付文書・インタビューフォーム",
            ],
            "efficacy_rate": 0.53,  # 暫定値
            "clinical_usage_rank": 36,
        },
        "onset": {
            "initial": "数時間〜1日",
            "optimal": "3-7日",
            "type": "acute",
        },
        "contraindications": [],
        "precautions": ["甘草含有製剤併用時"],
        "combinations": {
            "recommended": [],
            "possible": ["六君子湯"],
            "avoid": [],
        },
        "side_effects": {
            "common": ["胃部不快感"],
            "rare": ["偽アルドステロン症", "肝機能障害"],
            "serious": [],
            "note": "麻黄は含まない想定（要IF検証）。胃腸虚弱な虚証の感冒に用いやすい",
        },
        "notes": {
            "age_under_1": "医師相談必須。乳児期は使用実績が限定的。",
            "age_1_2": "成人1日量の約1/3を目安。",
            "age_3_5": "成人1日量の約1/2を目安。",
            "age_6": "成人1日量の約1/2を目安。",
            "caution": "胃腸虚弱が強い場合は食後服用を検討。",
        },
        "life_stage_eligible": ["幼児期"],
    },
}


# =============================================================================
# 漢方薬名のカタカナ読み
# =============================================================================

KAMPO_READING_KANA = {
    "小建中湯": "ショウケンチュウトウ",
    "黄耆建中湯": "オウギケンチュウトウ",
    "六君子湯": "リックンシトウ",
    "人参湯": "ニンジントウ",
    "桂枝加芍薬湯": "ケイシカシャクヤクトウ",
    "五苓散": "ゴレイサン",
    "柴胡桂枝湯": "サイコケイシトウ",
    "麦門冬湯": "バクモンドウトウ",
    "五虎湯": "ゴコトウ",
    "小青竜湯": "ショウセイリュウトウ",
    "葛根湯": "カッコントウ",
    "小柴胡湯": "ショウサイコトウ",
    "抑肝散": "ヨクカンサン",
    "抑肝散加陳皮半夏": "ヨクカンサンカチンピハンゲ",
    "甘麦大棗湯": "カンバクタイソウトウ",
    "補中益気湯": "ホチュウエッキトウ",
    "十全大補湯": "ジュウゼンダイホトウ",
    "消風散": "ショウフウサン",
    "越婢加朮湯": "エッピカジュツトウ",
    "麻黄湯": "マオウトウ",
    "桔梗湯": "キキョウトウ",
    "温清飲": "ウンセイイン",
    "柴朴湯": "サイボクトウ",
    "半夏瀉心湯": "ハンゲシャシントウ",
    "芍薬甘草湯": "シャクヤクカンゾウトウ",
    "五積散": "ゴシャクサン",
    "参蘇飲": "ジンソイン",
}


# =============================================================================
# 症状→漢方 重み付け（新形式: weight / evidence_level / recommendation_grade）
# 値は暫定。医療従事者によるレビュー必須。
# =============================================================================

SYMPTOM_KAMPO_WEIGHTS = {
    "腹痛": {
        "小建中湯": {"weight": 5, "evidence_level": "B", "recommendation_grade": "1B"},
        "芍薬甘草湯": {"weight": 5, "evidence_level": "B", "recommendation_grade": "2A"},
        "桂枝加芍薬湯": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "柴胡桂枝湯": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "五苓散": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2B"},
    },
    "便秘": {
        "小建中湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "桂枝加芍薬湯": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "六君子湯": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "下痢": {
        "五苓散": {"weight": 5, "evidence_level": "B", "recommendation_grade": "1B"},
        "人参湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "六君子湯": {"weight": 3, "evidence_level": "B", "recommendation_grade": "2A"},
        "半夏瀉心湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "小建中湯": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "嘔吐": {
        "五苓散": {"weight": 5, "evidence_level": "B", "recommendation_grade": "1B"},
        "六君子湯": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "人参湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
    },
    "食欲不振": {
        "六君子湯": {"weight": 5, "evidence_level": "A", "recommendation_grade": "1A"},
        "補中益気湯": {"weight": 4, "evidence_level": "B", "recommendation_grade": "1B"},
        "小建中湯": {"weight": 3, "evidence_level": "B", "recommendation_grade": "2A"},
        "人参湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
    },
    "乳児疝痛（コリック）": {
        "小建中湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "五苓散": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2C"},
        "抑肝散": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
    },
    # 追加指示#2で新規追加（暫定・要医学レビュー）
    "口内炎": {
        "半夏瀉心湯": {"weight": 5, "evidence_level": "C", "recommendation_grade": "2B"},
        "六君子湯": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "便秘・下痢を繰り返す": {
        "桂枝加芍薬湯": {"weight": 5, "evidence_level": "B", "recommendation_grade": "2A"},
        "小建中湯": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "五苓散": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "人参湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
    },
    "咳（乾性）": {
        "麦門冬湯": {"weight": 5, "evidence_level": "B", "recommendation_grade": "2A"},
        "小柴胡湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "柴胡桂枝湯": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "咳（湿性・痰がらみ）": {
        "小青竜湯": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "五虎湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2C"},
        "小柴胡湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "柴朴湯": {"weight": 3, "evidence_level": "B", "recommendation_grade": "2A"},
        "柴胡桂枝湯": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "喘息傾向": {
        "五虎湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2C"},
        "小青竜湯": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "柴朴湯": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "麦門冬湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "越婢加朮湯": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "鼻水・鼻づまり": {
        "小青竜湯": {"weight": 5, "evidence_level": "B", "recommendation_grade": "2A"},
        "葛根湯": {"weight": 3, "evidence_level": "B", "recommendation_grade": "2B"},
        "柴胡桂枝湯": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "感冒（かぜ）初期": {
        "葛根湯": {"weight": 5, "evidence_level": "B", "recommendation_grade": "2A"},
        "麻黄湯": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2B"},
        "小青竜湯": {"weight": 3, "evidence_level": "B", "recommendation_grade": "2B"},
        "柴胡桂枝湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "参蘇飲": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "五苓散": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
        "五積散": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "感冒の遷延・長引く微熱": {
        "柴胡桂枝湯": {"weight": 5, "evidence_level": "B", "recommendation_grade": "2A"},
        "小柴胡湯": {"weight": 5, "evidence_level": "B", "recommendation_grade": "2A"},
        "柴朴湯": {"weight": 3, "evidence_level": "B", "recommendation_grade": "2A"},
        "参蘇飲": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "補中益気湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "六君子湯": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    # 追加指示#2で新規追加（暫定・要医学レビュー）
    "咽頭痛・扁桃炎": {
        "桔梗湯": {"weight": 5, "evidence_level": "C", "recommendation_grade": "2B"},
        "小柴胡湯": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "中耳炎を繰り返す": {
        "小柴胡湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "柴胡桂枝湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "補中益気湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "五苓散": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "夜泣き": {
        "抑肝散": {"weight": 5, "evidence_level": "B", "recommendation_grade": "1B"},
        "甘麦大棗湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "抑肝散加陳皮半夏": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "小建中湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
    },
    "かんしゃく・疳の虫": {
        "抑肝散": {"weight": 5, "evidence_level": "B", "recommendation_grade": "1B"},
        "抑肝散加陳皮半夏": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "甘麦大棗湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "小建中湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
    },
    "不眠": {
        "抑肝散": {"weight": 5, "evidence_level": "B", "recommendation_grade": "1B"},
        "抑肝散加陳皮半夏": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "甘麦大棗湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
    },
    "情緒不安定": {
        "抑肝散": {"weight": 5, "evidence_level": "B", "recommendation_grade": "1B"},
        "甘麦大棗湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "抑肝散加陳皮半夏": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "小建中湯": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "熱性けいれん後の体調不良": {
        "柴胡桂枝湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "抑肝散": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "甘麦大棗湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2C"},
        "小柴胡湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "補中益気湯": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "虚弱体質・疲れやすい": {
        "小建中湯": {"weight": 5, "evidence_level": "B", "recommendation_grade": "1B"},
        "補中益気湯": {"weight": 5, "evidence_level": "B", "recommendation_grade": "1B"},
        "黄耆建中湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "十全大補湯": {"weight": 3, "evidence_level": "B", "recommendation_grade": "2A"},
        "六君子湯": {"weight": 3, "evidence_level": "B", "recommendation_grade": "2A"},
    },
    "食が細い": {
        "六君子湯": {"weight": 5, "evidence_level": "A", "recommendation_grade": "1A"},
        "小建中湯": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "補中益気湯": {"weight": 4, "evidence_level": "B", "recommendation_grade": "1B"},
        "抑肝散加陳皮半夏": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "体重増加不良": {
        "小建中湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "六君子湯": {"weight": 4, "evidence_level": "B", "recommendation_grade": "2A"},
        "十全大補湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
        "黄耆建中湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "寝汗（盗汗）": {
        "黄耆建中湯": {"weight": 5, "evidence_level": "C", "recommendation_grade": "2B"},
        "補中益気湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "小建中湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2C"},
        "十全大補湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "アトピー性皮膚炎": {
        "温清飲": {"weight": 5, "evidence_level": "C", "recommendation_grade": "2B"},
        "消風散": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "越婢加朮湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2C"},
        "補中益気湯": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
        "十全大補湯": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "湿疹・おむつかぶれ": {
        "消風散": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "温清飲": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2C"},
        "越婢加朮湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2C"},
        "五苓散": {"weight": 2, "evidence_level": "C", "recommendation_grade": "2C"},
    },
    "病後の体力低下": {
        "補中益気湯": {"weight": 5, "evidence_level": "B", "recommendation_grade": "1B"},
        "十全大補湯": {"weight": 5, "evidence_level": "B", "recommendation_grade": "2A"},
        "黄耆建中湯": {"weight": 4, "evidence_level": "C", "recommendation_grade": "2B"},
        "六君子湯": {"weight": 3, "evidence_level": "B", "recommendation_grade": "2A"},
        "小建中湯": {"weight": 3, "evidence_level": "C", "recommendation_grade": "2B"},
    },
}


# =============================================================================
# 生薬成分データベース（併用チェック用・成人1日量 g）
# 参考: ツムラ医療用漢方製剤 添付文書・IF
# 注記のある値は暫定。実運用前にIFで必ず検証すること。
# =============================================================================

# 【追加指示#4・2026-08-09】メーカー別ネスト構造に変更。
# ツムラの値は既存（追加指示#2以前）の暫定値をそのまま移設。
# クラシエ・コタローは製剤ごとのメーカー差の実データを持たないため、
# 特記のない限り「同一の伝統的処方構成であり、ツムラと同値と仮定」とし、
# 実際の含有量はメーカー各社の添付文書・インタビューフォームで必ず個別に検証すること。
HERB_COMPONENTS = {
    "小建中湯": {
        "ツムラ": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},
        "クラシエ": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "黄耆建中湯": {
        "ツムラ": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: 小建中湯系に準拠・要IF検証
        "クラシエ": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "六君子湯": {
        "ツムラ": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},
        "クラシエ": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "人参湯": {
        "ツムラ": {"甘草": 3.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: IF準拠想定・要検証
        "クラシエ": {"甘草": 3.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 3.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "桂枝加芍薬湯": {
        "ツムラ": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},
        "クラシエ": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "五苓散": {
        "ツムラ": {"甘草": 0, "麻黄": 0, "大黄": 0, "附子": 0},
        "クラシエ": {"甘草": 0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "柴胡桂枝湯": {
        "ツムラ": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: 要IF検証
        "クラシエ": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "麦門冬湯": {
        "ツムラ": {"甘草": 1.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 既存kanpoと同一
        "クラシエ": {"甘草": 1.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 1.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "五虎湯": {
        "ツムラ": {"甘草": 1.5, "麻黄": 4.0, "大黄": 0, "附子": 0},  # 暫定: 要IF検証
        "クラシエ": {"甘草": 1.5, "麻黄": 4.0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 1.5, "麻黄": 4.0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "小青竜湯": {
        "ツムラ": {"甘草": 3.0, "麻黄": 3.0, "大黄": 0, "附子": 0},  # 暫定: 要IF検証
        "クラシエ": {"甘草": 3.0, "麻黄": 3.0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 3.0, "麻黄": 3.0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "葛根湯": {
        "ツムラ": {"甘草": 2.0, "麻黄": 4.0, "大黄": 0, "附子": 0},  # 暫定: 要IF検証
        "クラシエ": {"甘草": 2.0, "麻黄": 4.0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 2.0, "麻黄": 4.0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "小柴胡湯": {
        "ツムラ": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: 要IF検証
        "クラシエ": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "抑肝散": {
        "ツムラ": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},
        "クラシエ": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "抑肝散加陳皮半夏": {
        "ツムラ": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},
        "クラシエ": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "甘麦大棗湯": {
        "ツムラ": {"甘草": 5.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 単剤でも高含有
        "クラシエ": {"甘草": 5.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 5.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "補中益気湯": {
        "ツムラ": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},
        "クラシエ": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "十全大補湯": {
        "ツムラ": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},
        "クラシエ": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 1.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "消風散": {
        "ツムラ": {"甘草": 1.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: 要IF検証（大黄非含有想定）
        "クラシエ": {"甘草": 1.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 1.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "越婢加朮湯": {
        "ツムラ": {"甘草": 2.0, "麻黄": 6.0, "大黄": 0, "附子": 0},
        "クラシエ": {"甘草": 2.0, "麻黄": 6.0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 2.0, "麻黄": 6.0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    # 追加指示#2で追加された8処方（暫定値・要IF検証）
    "麻黄湯": {
        "ツムラ": {"甘草": 1.5, "麻黄": 5.0, "大黄": 0, "附子": 0},  # 暫定: 麻黄含有量が多い代表処方・要IF検証
        "クラシエ": {"甘草": 1.5, "麻黄": 5.0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 1.5, "麻黄": 5.0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "桔梗湯": {
        "ツムラ": {"甘草": 3.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: 甘草高含有・要IF検証
        "クラシエ": {"甘草": 3.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 3.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "温清飲": {
        "ツムラ": {"甘草": 0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: 麻黄・大黄・附子非含有想定・要IF検証
        "クラシエ": {"甘草": 0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "柴朴湯": {
        "ツムラ": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: 小柴胡湯+半夏厚朴湯の合方・要IF検証
        "クラシエ": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 2.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "半夏瀉心湯": {
        "ツムラ": {"甘草": 2.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: 甘草含有量が多め・要IF検証
        "クラシエ": {"甘草": 2.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 2.5, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "芍薬甘草湯": {
        "ツムラ": {"甘草": 6.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 甘草含有量が非常に多い（既存kanpoと同一値）
        "クラシエ": {"甘草": 6.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 6.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "五積散": {
        "ツムラ": {"甘草": 1.0, "麻黄": 2.0, "大黄": 0, "附子": 0},  # 麻黄含有（既存kanpoと同一値）
        "クラシエ": {"甘草": 1.0, "麻黄": 2.0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 1.0, "麻黄": 2.0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
    "参蘇飲": {
        "ツムラ": {"甘草": 1.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: 麻黄非含有想定・要IF検証
        "クラシエ": {"甘草": 1.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
        "コタロー": {"甘草": 1.0, "麻黄": 0, "大黄": 0, "附子": 0},  # 暫定: ツムラと同値と仮定・要IF検証
    },
}

# 併用リスク閾値（1日量 g）
# 甘草・大黄・附子は婦人科版と同一。
# 麻黄のみ小児向けにより保守的な閾値とする。
HERB_RISK_THRESHOLDS = {
    "甘草": {
        "warning": 2.5,
        "danger": 5.0,
        "risk_name": "偽アルドステロン症",
        "symptoms": "低カリウム血症、血圧上昇、浮腫、筋力低下",
    },
    # 小児科版: 乳幼児は麻黄の交感神経刺激作用（動悸・不眠・発汗）に敏感なため、
    # 成人閾値（warning 4.0 / danger 6.0）より低い warning 2.0 / danger 3.0 を採用。
    # 年齢換算後の量と比較する前提。要医療レビュー。
    "麻黄": {
        "warning": 2.0,
        "danger": 3.0,
        "risk_name": "交感神経刺激作用増強",
        "symptoms": "動悸、血圧上昇、不眠、発汗、興奮",
    },
    "大黄": {
        "warning": 2.0,
        "danger": 4.0,
        "risk_name": "瀉下作用増強",
        "symptoms": "激しい下痢、腹痛、脱水",
    },
    "附子": {
        "warning": 0.5,
        "danger": 1.0,
        "risk_name": "アコニチン中毒",
        "symptoms": "しびれ、動悸、不整脈、血圧低下",
    },
}


def check_combination_safety(
    kampo_list: List[str],
    age_key: Optional[str] = None,
    manufacturer: str = DEFAULT_MANUFACTURER,
) -> dict:
    """
    2剤併用時の安全性チェック（小児科版）

    【小児科固有】年齢用量換算係数の適用:
    HERB_COMPONENTS は成人1日量（g）で保持する。閾値比較の前に
    AGE_DOSE_FACTORS[age_key] を乗じて年齢換算後の推定1日量とする。
    この係数適用は小児科版固有の処理であり、婦人科版には存在しない。

    【追加指示#4・メーカー対応】
    HERB_COMPONENTS[kampo] はメーカー別（ツムラ/クラシエ/コタロー）にネストされている。
    指定メーカーにその処方のデータが存在しない場合は、エラーとせず安全側として
    ツムラの値を代用し、結果に "data_fallback": True を含める。

    Args:
        kampo_list: 併用する漢方薬名のリスト
        age_key: 年齢区分キー（under_1 / 1-2 / 3-5 / 6）。未指定時は係数1.0（成人量）
        manufacturer: メーカー名（ツムラ/クラシエ/コタロー）。未指定時は DEFAULT_MANUFACTURER

    Returns:
        dict: {
            "safe": bool,
            "warnings": List[dict],
            "dangers": List[dict],
            "herb_totals": dict,           # 年齢換算後の合計
            "herb_totals_adult": dict,     # 成人量ベースの合計（参考）
            "dose_factor": float,
            "age_key": str | None,
            "age_mandatory_warning": str | None,  # 1歳未満時の必須警告
            "manufacturer": str,
            "data_fallback": bool,         # 指定メーカーのデータが無くツムラ値で代用した場合 True
        }
    """
    if manufacturer not in VALID_MANUFACTURERS:
        manufacturer = DEFAULT_MANUFACTURER

    # 小児科固有: 年齢用量換算係数を適用
    dose_factor = 1.0
    if age_key and age_key in AGE_DOSE_FACTORS:
        dose_factor = AGE_DOSE_FACTORS[age_key]

    herb_totals_adult = {"甘草": 0.0, "麻黄": 0.0, "大黄": 0.0, "附子": 0.0}
    data_fallback = False

    for kampo in kampo_list:
        if kampo not in HERB_COMPONENTS:
            continue
        by_manufacturer = HERB_COMPONENTS[kampo]
        herb_amounts = by_manufacturer.get(manufacturer)
        if herb_amounts is None:
            # 指定メーカーのデータが無い場合は安全側でツムラ値を代用
            herb_amounts = by_manufacturer.get(DEFAULT_MANUFACTURER, {})
            data_fallback = True
        for herb, amount in herb_amounts.items():
            herb_totals_adult[herb] += amount

    # 年齢換算後の量で閾値判定（小児科固有）
    herb_totals = {h: round(v * dose_factor, 3) for h, v in herb_totals_adult.items()}

    warnings = []
    dangers = []

    for herb, total in herb_totals.items():
        if total > 0:
            threshold = HERB_RISK_THRESHOLDS[herb]
            entry = {
                "herb": herb,
                "total_amount": total,
                "adult_amount": herb_totals_adult[herb],
                "dose_factor": dose_factor,
                "risk_name": threshold["risk_name"],
                "symptoms": threshold["symptoms"],
            }
            if total >= threshold["danger"]:
                dangers.append({**entry, "level": "danger"})
            elif total >= threshold["warning"]:
                warnings.append({**entry, "level": "warning"})

    # 1歳未満は判定結果によらず医師の個別判断必須警告を付加
    age_mandatory_warning = None
    if age_key == "under_1":
        age_mandatory_warning = (
            "1歳未満は医師の個別判断が必須です。"
            "本チェック結果は参考情報であり、安全性を保証するものではありません。"
        )
        warnings.append({
            "herb": "（年齢）",
            "total_amount": 0,
            "risk_name": "1歳未満・医師判断必須",
            "symptoms": age_mandatory_warning,
            "level": "warning",
            "mandatory": True,
        })

    return {
        "safe": len(dangers) == 0,
        "warnings": warnings,
        "dangers": dangers,
        "herb_totals": {k: v for k, v in herb_totals.items() if v > 0},
        "herb_totals_adult": {k: v for k, v in herb_totals_adult.items() if v > 0},
        "dose_factor": dose_factor,
        "age_key": age_key,
        "age_mandatory_warning": age_mandatory_warning,
        "manufacturer": manufacturer,
        "data_fallback": data_fallback,
    }


# =============================================================================
# 2剤併用の推奨パターン（27処方から選定・暫定）
# =============================================================================

COMBINATION_PATTERNS = [
    {
        "combination": ["小建中湯", "抑肝散"],
        "indication": "虚弱体質でかんしゃく・夜泣きを伴う",
        "note": "体質改善の小建中湯に、神経症状への抑肝散を併用",
    },
    {
        "combination": ["柴胡桂枝湯", "六君子湯"],
        "indication": "反復性の体調不良と食欲不振の併存",
        "note": "遷延感冒・反復腹痛に胃腸機能改善を併用",
    },
    {
        "combination": ["抑肝散", "甘麦大棗湯"],
        "indication": "夜泣き・情緒不安定が強い虚証の児",
        "note": "甘草量が多くなるため安全性チェックを必ず確認",
    },
    {
        "combination": ["小建中湯", "六君子湯"],
        "indication": "虚弱で食が細く、腹痛を伴う児",
        "note": "脾胃虚弱の体質改善",
    },
    {
        "combination": ["抑肝散加陳皮半夏", "六君子湯"],
        "indication": "胃腸虚弱を伴うかんしゃく・夜泣き",
        "note": "神経症状と脾胃虚弱の両方に対応",
    },
    {
        "combination": ["補中益気湯", "六君子湯"],
        "indication": "病後の体力低下と食欲不振",
        "note": "気虚補益と胃腸機能改善の相乗効果",
    },
    {
        "combination": ["小柴胡湯", "五苓散"],
        "indication": "感冒の遷延で水滞（むくみ・尿不利傾向）を伴う",
        "note": "柴苓湯的な発想での併用（参考）",
    },
    {
        "combination": ["小建中湯", "甘麦大棗湯"],
        "indication": "虚弱体質で夜泣き・ひきつけ様興奮がある",
        "note": "甘麦大棗湯の甘草量に注意して短期併用を検討",
    },
    {
        "combination": ["黄耆建中湯", "補中益気湯"],
        "indication": "盗汗を伴う強度の虚弱・病後回復",
        "note": "気虚・表虚への補気固表",
    },
    # 追加指示#2で追加された併用パターン（甘草・麻黄の合計量を check_combination_safety() で確認済み）
    {
        "combination": ["柴朴湯", "五苓散"],
        "indication": "喘息傾向で咳嗽が続き、むくみ・水滞傾向を伴う",
        "note": "柴朴湯（咳嗽・不安）に五苓散（水滞）を併用",
    },
    {
        "combination": ["参蘇飲", "六君子湯"],
        "indication": "感冒に伴う胃腸虚弱・食欲不振の回復期",
        "note": "参蘇飲（胃腸虚弱を伴う感冒）に六君子湯で消化機能をサポート",
    },
    {
        "combination": ["半夏瀉心湯", "六君子湯"],
        "indication": "口内炎・下痢に胃腸虚弱を伴う場合",
        "note": "半夏瀉心湯（心下痞・口内炎）に六君子湯（脾胃虚弱）を併用",
    },
]


# =============================================================================
# 推奨エンジン - エビデンスベース（婦人科版と同一係数）
# =============================================================================

EVIDENCE_LEVEL_MULTIPLIERS = {
    "A": 1.3,  # 高品質エビデンス（メタアナリシス、複数のRCT）
    "B": 1.15,  # 中品質エビデンス（単独RCT、コホート研究）
    "C": 1.0,  # 低品質エビデンス（症例集積、ケースシリーズ）
    "D": 0.9,  # 専門家意見のみ
}

GUIDELINE_GRADE_MULTIPLIERS = {
    "1A": 1.25,  # 強く推奨
    "1B": 1.15,  # 推奨
    "2A": 1.05,  # 提案
    "2B": 1.0,  # 弱い提案
    "2C": 0.95,  # 弱い提案（エビデンス不十分）
}

SHO_MATCH_MULTIPLIERS = {
    "perfect": 1.3,  # 完全一致（虚証の患者に虚証の漢方）
    "good": 1.15,    # 良好（虚証の患者に虚証〜中間証の漢方）
    "acceptable": 1.0,  # 許容範囲（中間証、証を問わない）
    "caution": 0.8,  # 注意（虚証の患者に実証〜中間証の漢方）
    "poor": 0.5,     # 不適合（虚証の患者に実証の漢方）
}


def calculate_sho_match(patient_sho: str, kampo_sho: str) -> float:
    """証の適合度を計算"""
    if not patient_sho or patient_sho == "指定なし":
        return SHO_MATCH_MULTIPLIERS["acceptable"]

    if "証を問わない" in kampo_sho:
        return SHO_MATCH_MULTIPLIERS["acceptable"]

    if patient_sho in kampo_sho:
        return SHO_MATCH_MULTIPLIERS["perfect"]

    if patient_sho == "虚証":
        if "中間証" in kampo_sho:
            return SHO_MATCH_MULTIPLIERS["good"]
        elif "実証" in kampo_sho:
            return SHO_MATCH_MULTIPLIERS["poor"]

    elif patient_sho == "実証":
        if "中間証" in kampo_sho:
            return SHO_MATCH_MULTIPLIERS["good"]
        elif "虚証" in kampo_sho:
            return SHO_MATCH_MULTIPLIERS["poor"]

    elif patient_sho == "中間証":
        return SHO_MATCH_MULTIPLIERS["good"]

    return SHO_MATCH_MULTIPLIERS["acceptable"]


def _is_life_stage_eligible(kampo_name: str, life_stage: Optional[str]) -> bool:
    """処方の life_stage_eligible に選択中ライフステージが含まれるか"""
    if not life_stage:
        return True
    info = KAMPO_DATABASE.get(kampo_name)
    if not info:
        return False
    eligible = info.get("life_stage_eligible") or []
    return life_stage in eligible


def _is_manufacturer_available(kampo_name: str, manufacturer: Optional[str]) -> bool:
    """
    【追加指示#4】処方の products[manufacturer]["available"] が True かどうか。
    manufacturer 未指定時、または該当メーカーのデータが無い場合は絞り込みを行わない（True）。
    """
    if not manufacturer:
        return True
    info = KAMPO_DATABASE.get(kampo_name)
    if not info:
        return False
    product = (info.get("products") or {}).get(manufacturer)
    if product is None:
        return True
    return bool(product.get("available", True))


def calculate_kampo_scores(
    selected_symptoms: List[str],
    patient_sho: str = None,
    life_stage: str = None,
    manufacturer: str = None,
) -> Dict[str, float]:
    """
    選択された症状から各漢方薬のスコアを計算（エビデンスベース強化版）

    小児科固有: life_stage が指定された場合、life_stage_eligible に
    含まれない処方はスコア集計対象外とする。
    追加指示#4: manufacturer が指定された場合、products[manufacturer]["available"]
    が False の処方もスコア集計対象外とする。
    """
    scores = {}

    for symptom in selected_symptoms:
        if symptom in SYMPTOM_KAMPO_WEIGHTS:
            for kampo, weight_data in SYMPTOM_KAMPO_WEIGHTS[symptom].items():
                if kampo not in KAMPO_DATABASE:
                    continue
                if not _is_life_stage_eligible(kampo, life_stage):
                    continue
                if not _is_manufacturer_available(kampo, manufacturer):
                    continue

                if isinstance(weight_data, int):
                    base_weight = weight_data
                    evidence_multiplier = 1.0
                    guideline_multiplier = 1.0
                else:
                    base_weight = weight_data.get("weight", 3)
                    evidence_level = weight_data.get("evidence_level", "C")
                    guideline_grade = weight_data.get("recommendation_grade", "2B")
                    evidence_multiplier = EVIDENCE_LEVEL_MULTIPLIERS.get(evidence_level, 1.0)
                    guideline_multiplier = GUIDELINE_GRADE_MULTIPLIERS.get(guideline_grade, 1.0)

                kampo_info = KAMPO_DATABASE[kampo]
                sho_multiplier = calculate_sho_match(patient_sho, kampo_info["sho"])
                symptom_score = base_weight * evidence_multiplier * guideline_multiplier * sho_multiplier
                scores[kampo] = scores.get(kampo, 0) + symptom_score

    return scores


def estimate_sho(selected_symptoms: List[str]) -> dict:
    """
    選択症状から証（体質）の傾向を推定する（参考情報。医師の最終判断を代替しない）
    """
    sho_scores = {"虚証": 0.0, "中間証": 0.0, "実証": 0.0}

    for symptom in selected_symptoms:
        if symptom not in SYMPTOM_KAMPO_WEIGHTS:
            continue
        for kampo, weight_data in SYMPTOM_KAMPO_WEIGHTS[symptom].items():
            if kampo not in KAMPO_DATABASE:
                continue
            weight = weight_data if isinstance(weight_data, int) else weight_data.get("weight", 3)
            kampo_sho = KAMPO_DATABASE[kampo]["sho"]

            if "証を問わない" in kampo_sho:
                continue

            matched = [s for s, has in [
                ("虚証", "虚証" in kampo_sho),
                ("中間証", "中間証" in kampo_sho),
                ("実証", "実証" in kampo_sho),
            ] if has]
            if not matched:
                continue
            share = weight / len(matched)
            for s in matched:
                sho_scores[s] += share

    total = sum(sho_scores.values())
    if total == 0:
        return {"suggested_sho": None, "scores": sho_scores, "message": "推定に十分な症状データがありません"}

    ranked = sorted(sho_scores.items(), key=lambda x: x[1], reverse=True)
    top_sho, top_score = ranked[0]
    second_score = ranked[1][1]

    if second_score > 0 and top_score / second_score < 1.2:
        return {"suggested_sho": None, "scores": sho_scores, "message": "明確な傾向は見られません（複数の証が拮抗しています）"}

    return {
        "suggested_sho": top_sho,
        "scores": {k: round(v, 2) for k, v in sho_scores.items()},
        "message": f"選択された症状から、{top_sho}の傾向がやや優勢です（参考情報）",
    }


def get_top_recommendations(
    scores: Dict[str, float],
    sho: str = None,
    max_results: int = 3,
    life_stage: str = None,
    age_key: str = None,
    dose_factor: float = None,
    manufacturer: str = None,
) -> List[dict]:
    """
    上位の推奨漢方を取得（エビデンス情報付き）

    小児科固有: life_stage で候補をフィルタし、年齢換算用量メモを付与する。
    追加指示#4: manufacturer で候補をフィルタし、選択メーカーの product_no を付与する。
    """
    sorted_kampo = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    effective_manufacturer = manufacturer if manufacturer in VALID_MANUFACTURERS else DEFAULT_MANUFACTURER

    if dose_factor is None:
        if age_key and age_key in AGE_DOSE_FACTORS:
            dose_factor = AGE_DOSE_FACTORS[age_key]
        else:
            dose_factor = 1.0

    note_key = AGE_NOTE_KEY_MAP.get(age_key) if age_key else None

    results = []
    for kampo_name, score in sorted_kampo:
        if len(results) >= max_results:
            break

        if not _is_life_stage_eligible(kampo_name, life_stage):
            continue
        if not _is_manufacturer_available(kampo_name, effective_manufacturer):
            continue

        kampo_info = KAMPO_DATABASE[kampo_name]

        if sho and sho != "指定なし":
            kampo_sho = kampo_info["sho"]
            if sho == "虚証" and "実証" in kampo_sho and "虚証" not in kampo_sho and "中間証" not in kampo_sho and "証を問わない" not in kampo_sho:
                continue
            elif sho == "実証" and "虚証" in kampo_sho and "実証" not in kampo_sho and "中間証" not in kampo_sho and "証を問わない" not in kampo_sho:
                continue

        ev = kampo_info.get("evidence", {}) or {}
        on = kampo_info.get("onset", {}) or {}
        nt = kampo_info.get("notes", {}) or {}

        age_note_excerpt = nt.get(note_key, "") if note_key else ""
        product = (kampo_info.get("products") or {}).get(effective_manufacturer, {})

        results.append({
            "name": kampo_name,
            "score": round(score, 2),
            "manufacturer": effective_manufacturer,
            "product_no": product.get("product_no"),
            "product_available": product.get("available", True),
            "sho": kampo_info["sho"],
            "description": kampo_info["description"],
            "indications": kampo_info["indications"],
            "contraindications": kampo_info["contraindications"],
            "precautions": kampo_info.get("precautions", []),
            "side_effects": kampo_info.get("side_effects", {}),
            "evidence": ev,
            "onset": on,
            "notes": nt,
            "evidence_level": ev.get("level", ""),
            "guideline_grade": ev.get("guideline_grade", ""),
            "efficacy_rate": ev.get("efficacy_rate"),
            "onset_initial": on.get("initial", ""),
            "onset_optimal": on.get("optimal", ""),
            "reading_kana": KAMPO_READING_KANA.get(kampo_name, ""),
            "life_stage_eligible": kampo_info.get("life_stage_eligible", []),
            "age_adjusted_dose_note": f"成人1日量の約{int(dose_factor * 100)}%を目安（要医師判断）",
            "age_specific_note": age_note_excerpt,
        })

    return results


def find_combination_recommendations(
    top_kampo: List[dict],
    selected_symptoms: List[str],
    age_key: str = None,
    life_stage: str = None,
    manufacturer: str = None,
) -> List[dict]:
    """2剤併用の推奨を検索（安全性チェック付き・小児科版）"""
    recommendations = []
    top_names = [k["name"] for k in top_kampo]
    effective_manufacturer = manufacturer if manufacturer in VALID_MANUFACTURERS else DEFAULT_MANUFACTURER

    for pattern in COMBINATION_PATTERNS:
        combo = pattern["combination"]

        # 小児科固有: ライフステージ非該当処方を含むパターンは除外
        if life_stage and not all(_is_life_stage_eligible(name, life_stage) for name in combo):
            continue

        # 追加指示#4: 選択メーカーで取扱不可（available: False）の処方を含むパターンは除外
        if not all(_is_manufacturer_available(name, effective_manufacturer) for name in combo):
            continue

        match_count = sum(1 for k in combo if k in top_names)
        if match_count >= 1:
            combo_info = []
            for name in combo:
                if name in KAMPO_DATABASE:
                    product = (KAMPO_DATABASE[name].get("products") or {}).get(effective_manufacturer, {})
                    combo_info.append({
                        "name": name,
                        "manufacturer": effective_manufacturer,
                        "product_no": product.get("product_no"),
                        "reading_kana": KAMPO_READING_KANA.get(name, ""),
                    })

            # 小児科固有: age_key を渡して年齢換算後に安全性チェック
            # 追加指示#4: manufacturer を渡してメーカー別の生薬量で判定
            safety_check = check_combination_safety(combo, age_key=age_key, manufacturer=effective_manufacturer)

            recommendations.append({
                "combination": combo_info,
                "indication": pattern["indication"],
                "note": pattern["note"],
                "match_score": match_count,
                "safety": safety_check,
            })

    recommendations.sort(key=lambda x: (-int(x["safety"]["safe"]), -x["match_score"]))
    return recommendations[:3]


def filter_symptoms_by_life_stage(symptoms: List[str], life_stage: str) -> List[str]:
    """選択症状をライフステージでフィルタ"""
    filtered = []
    for s in symptoms:
        stages = SYMPTOM_LIFE_STAGES.get(s)
        if stages is None or life_stage in stages:
            filtered.append(s)
    return filtered


# =============================================================================
# Flask Routes
# =============================================================================

@app.route("/")
def index():
    log_operation("page_view", "index")
    return render_template(
        "index.html",
        symptom_categories=SYMPTOM_CATEGORIES,
        life_stages=LIFE_STAGES,
        symptom_life_stages=SYMPTOM_LIFE_STAGES,
        manufacturers=MANUFACTURERS,
        default_manufacturer=DEFAULT_MANUFACTURER,
    )


@app.route("/recommend", methods=["POST"])
def recommend():
    data = request.get_json(silent=True) or {}
    selected_symptoms = data.get("symptoms", [])
    sho = data.get("sho", "指定なし")
    life_stage = data.get("life_stage")
    age_key = data.get("age_key")
    manufacturer = data.get("manufacturer", DEFAULT_MANUFACTURER)

    log_operation(
        "recommend",
        f"症状={str(selected_symptoms)[:80]}, life_stage={life_stage}, age_key={age_key}, manufacturer={manufacturer}",
    )

    if not selected_symptoms:
        return jsonify({"error": "症状を1つ以上選択してください。"}), 400

    if not life_stage or life_stage not in VALID_LIFE_STAGES:
        return jsonify({"error": "ライフステージ（乳児期／幼児期）を選択してください。"}), 400

    if not age_key or age_key not in VALID_AGE_KEYS:
        return jsonify({"error": "年齢区分を選択してください。"}), 400

    if not manufacturer or manufacturer not in VALID_MANUFACTURERS:
        return jsonify({"error": "メーカー（ツムラ／クラシエ／コタロー）を選択してください。"}), 400

    # ライフステージと年齢区分の整合性チェック
    valid_keys_for_stage = {opt["key"] for opt in LIFE_STAGES[life_stage]["age_options"]}
    if age_key not in valid_keys_for_stage:
        return jsonify({"error": f"選択されたライフステージ（{life_stage}）に対して無効な年齢区分です。"}), 400

    # 症状をライフステージでフィルタ
    filtered_symptoms = filter_symptoms_by_life_stage(selected_symptoms, life_stage)
    if not filtered_symptoms:
        return jsonify({
            "error": "選択された症状は、現在のライフステージでは対象外です。症状またはライフステージを見直してください。"
        }), 400

    dose_factor = AGE_DOSE_FACTORS[age_key]

    scores = calculate_kampo_scores(
        filtered_symptoms,
        patient_sho=sho,
        life_stage=life_stage,
        manufacturer=manufacturer,
    )

    if not scores:
        return jsonify({"error": "選択された症状に対応する漢方薬が見つかりませんでした。"}), 404

    top_recommendations = get_top_recommendations(
        scores,
        sho,
        max_results=3,
        life_stage=life_stage,
        age_key=age_key,
        dose_factor=dose_factor,
        manufacturer=manufacturer,
    )

    combinations = find_combination_recommendations(
        top_recommendations,
        filtered_symptoms,
        age_key=age_key,
        life_stage=life_stage,
        manufacturer=manufacturer,
    )

    response_data = {
        "recommendations": top_recommendations,
        "combinations": combinations,
        "selected_symptoms": filtered_symptoms,
        "life_stage": life_stage,
        "age_key": age_key,
        "manufacturer": manufacturer,
        "dose_factor": dose_factor,
        "scoring_info": {
            "evidence_based": True,
            "sho_matched": sho != "指定なし",
            "life_stage_filtered": True,
            "manufacturer_filtered": True,
            "version": "pediatric-1.0",
        },
    }

    if life_stage == "乳児期" or age_key == "under_1":
        response_data["age_warning"] = (
            "1歳未満は医師の個別判断が必須です。参考情報としてのみご使用ください。"
        )

    if not top_recommendations:
        if sho and sho != "指定なし":
            response_data["message"] = (
                f"選択された症状に対して、指定された証（{sho}）およびライフステージ（{life_stage}）に"
                "適合する漢方薬が見つかりませんでした。"
                "証の選択を「指定なし」に変更するか、症状・ライフステージの組み合わせをご確認ください。"
            )
        else:
            response_data["message"] = (
                "選択された症状・ライフステージに対応する漢方薬が見つかりませんでした。"
                "症状の組み合わせをご確認ください。"
            )

    return jsonify(response_data)


@app.route("/estimate-sho", methods=["POST"])
def estimate_sho_route():
    """選択症状から証（体質）の傾向を推定する（参考情報）"""
    data = request.get_json(silent=True) or {}
    symptoms = data.get("symptoms", [])
    if not isinstance(symptoms, list) or not symptoms:
        return jsonify({"error": "症状を1つ以上選択してください。"}), 400
    result = estimate_sho(symptoms)
    log_operation("estimate_sho", f"症状={str(symptoms)[:100]}")
    return jsonify(result)


@app.route("/kampo/<name>")
def kampo_detail(name):
    """漢方薬の詳細情報を取得"""
    log_operation("herb_detail", f"herb={name}")
    if name in KAMPO_DATABASE:
        info = KAMPO_DATABASE[name].copy()
        info["name"] = name
        info["reading_kana"] = KAMPO_READING_KANA.get(name, "")
        return jsonify(info)
    return jsonify({"error": "漢方薬が見つかりません"}), 404


@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("errors/500.html"), 500


init_log_db()

if __name__ == "__main__":
    init_log_db()
    app.run(host='0.0.0.0', port=50005, debug=False)
