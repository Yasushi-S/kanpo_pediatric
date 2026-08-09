# 実行記録（kanpo_pediatric）

Cursor での実施内容をこのファイルの末尾に追記する。

---
## [2026-08-09] 実行 #1 ── creation_order.md に基づく小児科漢方薬推奨システムの初回実装

### 対応した指示
- creation_order.md 全体（機能・データ構造・ファイル構成・セットアップ・セキュリティ要件）

### 実施内容詳細
- `app.py` を新規作成（Flask・port 50005）
  - `SYMPTOM_CATEGORIES`（4カテゴリ・26症状）、`LIFE_STAGES`、`SYMPTOM_LIFE_STAGES`、`AGE_DOSE_FACTORS`（LIFE_STAGESから導出）
  - `KAMPO_DATABASE` 19処方（小児向け notes・`life_stage_eligible` 付き）。乳児期対象は発注書どおり8処方
  - `SYMPTOM_KAMPO_WEIGHTS`（新形式）、`HERB_COMPONENTS`、`COMBINATION_PATTERNS`、`KAMPO_READING_KANA`
  - スコアリング・証推定・推奨・併用提案は既存 kanpo ロジックを踏襲し、ライフステージフィルタを前段に追加
  - `check_combination_safety()` に年齢換算係数適用（小児科固有）と1歳未満の必須警告を実装
  - 麻黄の危険閾値を小児向けに厳格化（warning 2.0 / danger 3.0、根拠コメント付き）
  - 操作ログ（SQLite・パラメータバインド）、`SECRET_KEY` は環境変数から取得
- `templates/index.html` を既存デザイン流用で小児科向けに改修
  - タイトル・免責（0〜6歳）、favicon（👶）、ライフステージ必須UI、年齢細分、乳児期赤警告
  - 症状チップのライフステージフィルタ・切替時の選択解除トースト
  - 推奨カードに年齢換算用量目安・小児 notes、併用の年齢換算生薬合計表示
- `templates/errors/404.html`・`500.html` を移植
- `setup_firewall.ps1`（port 50005）、`setup_task_scheduler.ps1`（タスク名 `kanpo-pediatric-app`）を調整
- 既存の `requirements.txt` / `start_app.bat` / `.env.example` / `.gitignore` / `.cursor/rules` は発注書どおりのため維持
- `static/`・`docs/` ディレクトリを用意

### 確認事項・備考
- **医療内容は未検証（レビュー待ち）**。ツムラ番号・生薬含有量・エビデンス・乳児期対象処方・年齢換算係数・麻黄閾値は暫定値。実運用前に薬剤師・医師による添付文書等での確認が必須。
- Claude Code レビュー完了・ユーザー承認まで git commit しない（.cursor/rules 準拠）。
- スモークテスト（`GET /`、幼児期・乳児期の `/recommend`、`/estimate-sho`、併用安全性チェック）は成功。
---

## [2026-08-09] 実行 #2 ── modification_instructions.md 追加指示 #1（未完了部分の実装・補完）

### 対応した指示
- modification_instructions.md「[2026-08-09] 追加指示 #1 ── 初回実装の未完了部分の実装」

### 実施内容詳細
- `templates/index.html` / `templates/errors/404.html` / `500.html` / `setup_firewall.ps1` / `setup_task_scheduler.ps1` は実行 #1 時点で作成済みであることを確認（起動時のテンプレート欠落は解消済み）
- CSS/JS は既存 kanpo と同様に `index.html` 内インラインで完結するため、`static/` への分離は不要と判断。ディレクトリ保持用に `static/.gitkeep` を追加
- `requirements.txt` に `python-dotenv==1.2.2` をバージョン固定で追加（`.env` からの `SECRET_KEY` 読み込みを保証）
- UI に医療レビュー待ちの明示を追加
  - 入力パネルに `.notice-review`（暫定データ・実運用前検証必須）
  - 推奨結果の参考文献欄にも同様の注意文を表示
- 本指示への対応内容を `modification_log.md` に追記（本エントリ）

### 確認事項・備考
- 医療内容（生薬量・年齢換算係数・危険閾値・ツムラ番号・エビデンス等）は引き続き暫定値。実運用前の医療レビューが必須。
- Claude Code レビュー完了・ユーザー承認まで git commit しない。
---

## [2026-08-09] 実行 #3 ── modification_instructions.md 追加指示 #2（候補処方の拡充・19→27処方）

### 対応した指示
- modification_instructions.md「[2026-08-09] 追加指示 #2 ── 候補処方の拡充（8処方追加・19→27処方）」

### 実施内容詳細
- `KAMPO_DATABASE` に8処方を追加（27処方）: 麻黄湯・桔梗湯・温清飲・柴朴湯・半夏瀉心湯・芍薬甘草湯・五積散・参蘇飲
  - 既存19処方と同一のフィールド構成（indications/evidence/onset/contraindications/precautions/combinations/side_effects/notes/life_stage_eligible）で作成
  - 麻黄湯・五積散は麻黄含有のため `precautions` に「乳幼児での慎重投与」を明記し、`combinations.avoid` に他の麻黄含有処方（五虎湯・小青竜湯・葛根湯・越婢加朮湯・相互）を設定
  - 芍薬甘草湯は甘草6.0g/日と高含有のため、`precautions`・`notes.caution` に頓用中心・連用回避を明記し、`combinations.avoid` に甘草高含有処方を設定
  - 桔梗湯・半夏瀉心湯も甘草含有量が多めである旨を `side_effects.note` に明記
  - 8処方すべて `life_stage_eligible: ["幼児期"]` のみとした（指示のとおり麻黄湯・芍薬甘草湯は乳児期対象外を強く推奨、他6処方も使用実績が既存8処方ほど明確でないためデフォルト＝幼児期のみを採用）
- `SYMPTOM_CATEGORIES` に新規症状2件を追加（計28症状）: 呼吸器症状に「咽頭痛・扁桃炎」、消化器症状に「口内炎」
- `SYMPTOM_LIFE_STAGES` に両症状のライフステージ該当区分を追加（咽頭痛・扁桃炎: 幼児期のみ／口内炎: 乳児期・幼児期）
- `HERB_COMPONENTS` に8処方の甘草・麻黄・大黄・附子含有量（暫定値）を追加。麻黄湯・五積散・芍薬甘草湯・桔梗湯は値の根拠をコメントで明記
- `SYMPTOM_KAMPO_WEIGHTS` に新規症状2件の重み付けを追加するとともに、新規処方を関連する既存症状（腹痛・下痢・感冒（かぜ）初期・感冒の遷延・喘息傾向・咳（湿性・痰がらみ）・アトピー性皮膚炎・湿疹・おむつかぶれ）に組み込み
- `KAMPO_READING_KANA` に8処方のカタカナ読みを追加
- `COMBINATION_PATTERNS` に新規処方を用いた併用パターンを3件追加（柴朴湯+五苓散、参蘇飲+六君子湯、半夏瀉心湯+六君子湯）。追加前に `check_combination_safety()` で全年齢区分の安全性を確認し、危険域に達しないことを検証済み
- データ整合性テスト（処方27件・症状28件、`HERB_COMPONENTS`/`KAMPO_READING_KANA`のキー一致、症状重み参照先の存在確認）とAPIスモークテスト（新規症状での推奨、乳児期での新規処方除外、麻黄含有処方同士の危険併用検知）を実施し、いずれも想定どおりの結果を確認

### 確認事項・備考
- 処方数増加（19→27）に伴い、`creation_order.md` 4.2節・modification_instructions.md 記載の暫定データはすべて実運用前に医療従事者による検証が必須。UIの「レビュー待ち」表示は既存のまま変更なし。
- 甘草高含有の芍薬甘草湯・桔梗湯・半夏瀉心湯を追加したことで、他処方との2剤併用時に `HERB_RISK_THRESHOLDS`（甘草 warning 2.5g / danger 5.0g）に抵触しやすくなる点を踏まえ、新規追加した `COMBINATION_PATTERNS` は6歳（dose_factor 0.5、幼児期で最も換算量が大きい区分）でも安全性チェックが danger/warning にならないことを個別に確認済み
- Claude Code レビュー完了・ユーザー承認まで git commit しない。
---
