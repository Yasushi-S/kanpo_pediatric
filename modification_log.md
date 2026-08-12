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

## [2026-08-09] 実行 #4 ── modification_instructions.md 追加指示 #3（レビュー指摘の軽微な修正2点）

### 対応した指示
- modification_instructions.md「[2026-08-09] 追加指示 #3 ── レビュー指摘の軽微な修正2点」

### 実施内容詳細
- `combinations.avoid` の非対称性を解消
  - 麻黄含有処方6種（五虎湯・小青竜湯・葛根湯・越婢加朮湯・麻黄湯・五積散）の `avoid` を相互に完全対称化（各処方が他5処方をすべて列挙）
  - 甘草高含有処方5種（芍薬甘草湯・甘麦大棗湯・桔梗湯・小建中湯・桂枝加芍薬湯）についても、芍薬甘草湯を起点とした `avoid` を相互に完全対称化
  - `KAMPO_DATABASE` 定義直前に、`combinations.avoid` は表示・注意喚起のための参考情報であり、実際の併用安全性判定は `COMBINATION_PATTERNS` + `check_combination_safety()` の生薬量計算で行われる旨のコメントを追加（誤解防止）
- 古いコメントの数値を更新
  - 症状データベースのコメントを「4カテゴリ・26症状」→「4カテゴリ・28症状（初期案26症状 + 追加指示#2で2症状追加）」に更新
  - 併用推奨パターンのコメントを「19処方から選定・暫定」→「27処方から選定・暫定」に更新
  - `app.py` 全体を検索し、他に処方数・症状数を誤って記載した古いコメントが残っていないことを確認（`tsumura_no` の値としての「19」等、無関係な数値は変更なし）
- スコアリング・安全性チェックのロジック自体は変更していないことを確認（コンパイルチェックのみ、`python -m py_compile app.py` は成功）

### 確認事項・備考
- 本実行は表示・ドキュメント上の整合性修正のみであり、医療内容の値そのものは変更していない
- Claude Code レビュー完了・ユーザー承認まで git commit しない
---

## [2026-08-09] 実行 #5 ── modification_instructions.md 追加指示 #4（複数メーカー対応・ツムラ／クラシエ／コタロー）

### 対応した指示
- modification_instructions.md「[2026-08-09] 追加指示 #4 ── 複数メーカー対応（ツムラ／クラシエ／コタロー）」

### 実施内容詳細
- `MANUFACTURERS` 定数（ツムラ／クラシエ／コタロー、`order` 付き）と `DEFAULT_MANUFACTURER`（ツムラ）、`VALID_MANUFACTURERS` を新設。`LIFE_STAGES` と同様、既存ロジックへの侵襲を最小化する追加軸として実装
- `KAMPO_DATABASE` の `tsumura_no`（単一フィールド）を `products`（メーカー別ネスト構造）に置き換え。27処方 × 3メーカー = 81通り全件を作成
  - ツムラの `product_no` は既存の `tsumura_no` 値をそのまま移設（値は変更なし）
  - クラシエ・コタローは製品番号（メーカー独自の番号体系）の実データを持たないため、捏造を避け `product_no: None` とし、コメントで「製品番号未確認・取扱有無要確認（要IF検証）」を明記。`available` はいずれも `True`（取扱有無不明のためデフォルト）
- `HERB_COMPONENTS` をメーカー別ネスト構造（`{処方名: {ツムラ: {...}, クラシエ: {...}, コタロー: {...}}}`）に変更
  - ツムラの値は既存の暫定値をそのまま移設
  - クラシエ・コタローはメーカー差の実データを持たないため、「同一の伝統的処方構成であり、ツムラと同値と仮定」とし、各項目に「ツムラと同値と仮定・要IF検証」のコメントを付与（実態を知らない値の捏造は行っていない）
- `check_combination_safety()` に `manufacturer: str = DEFAULT_MANUFACTURER` 引数を追加し、`HERB_COMPONENTS[kampo][manufacturer]` を参照するよう変更。指定メーカーのデータが存在しない場合はエラーとせず、安全側でツムラ値を代用し `data_fallback: True` を結果に含める（フォールバック動作をテストで確認済み）
- `calculate_kampo_scores()` / `get_top_recommendations()` / `find_combination_recommendations()` に `manufacturer` 引数を追加し、`_is_manufacturer_available()`（`_is_life_stage_eligible()` と同様の絞り込みロジック）で `products[manufacturer]["available"]` が `False` の処方を候補から除外できるように実装
- `/recommend` エンドポイントに `manufacturer`（未指定時は `DEFAULT_MANUFACTURER`）を追加し、未知のメーカー値はバリデーションエラー（400）とした。レスポンスの各処方情報を `tsumura_no` 直接参照から `manufacturer` / `product_no` / `product_available` に置き換え
- `/`（index）ルートで `manufacturers` / `default_manufacturer` をテンプレートに渡すよう変更
- `templates/index.html`
  - 入力パネル上部（レビュー待ち通知の直後、症状選択セクションの直前）にメーカー選択セクション（セグメントコントロール、デフォルト=ツムラ、必須）を追加
  - 選択セクション内に強い注意書き（赤枠・太字）「メーカー別データは未検証です。生薬量・製品番号は…差し替え前に必ず各メーカーの添付文書・インタビューフォームで確認してください。」を常時表示（ライフステージの1歳未満警告より強く、常時表示とした）
  - 推奨カード・併用提案カードの「ツムラXX番」表示を、選択中メーカーの `product_no` 表示（`formatProductBadge()`。`product_no` が無い場合は「製品番号未確認・要IF検証」と表示）に置き換え
  - メーカー変更時にトースト通知「メーカーを変更しました。処方候補・製品番号・安全性チェック結果が変わる場合があります。」を表示
  - `/recommend` 送信時に `manufacturer` を送信、未選択時はエラー表示
  - 参考文献欄の注意文に、選択中メーカーの生薬量・製品番号が未検証である旨を明記
- 検証
  - データ整合性: 27処方全件に `products`（3メーカー分）、`HERB_COMPONENTS` 全件に3メーカー分のキーが存在することをスクリプトで確認（欠落なし）
  - `check_combination_safety()`: ツムラ／コタロー間で結果が一致すること（現状クラシエ・コタローはツムラと同値の仮定のため）、および意図的にメーカー別データを欠落させた場合に `data_fallback: True` かつツムラ値で正しくフォールバックされることを確認
  - `/recommend` をローカルサーバー（`python app.py`）で起動し、メーカー未指定（デフォルト=ツムラ、`product_no` あり）、`manufacturer="クラシエ"`（`product_no: None`）、無効なメーカー値（400エラー）の3パターンを実機で確認
  - `calculate_kampo_scores()` / `get_top_recommendations()` / `find_combination_recommendations()` をメーカー引数付きで呼び出し、乳児期対象処方数（8処方）が変化しないこと、併用推奨（`かんしゃく・疳の虫`）の `product_no` が選択メーカーに応じて正しく反映されることを確認
  - `index.html` を実機取得し、メーカー選択UI（3ボタン）・デフォルト選択（ツムラ）・強い注意書きが正しくレンダリングされていることを確認
  - `python -m py_compile app.py` によるコンパイルチェック成功

### 確認事項・備考
- **本追加は特に医療安全性に直結する。** メーカー別の生薬量データ（クラシエ・コタロー）はツムラと同値との仮定に基づく未検証の暫定値であり、製品番号（クラシエ・コタロー）は不明のため `None` としている。実運用開始前に薬剤師が各メーカー公式の添付文書・インタビューフォームで全件照合するまでは、複数メーカー選択機能自体を実務では使用しないこと（UI上に強い注意書きとして明示済み）
- 既存のツムラ単体データ（19→27処方拡充分含む）の値そのものは変更していない（`products.ツムラ.product_no` に既存の `tsumura_no` 値をそのまま移設）
- Claude Code レビュー完了・ユーザー承認まで git commit しない
---

## [2026-08-09] 実行 #6 ── modification_instructions.md 追加指示 #5（combinations.avoid 対称化の残り1件）── Claude Code が直接実施

### 対応した指示
- modification_instructions.md「[2026-08-09] 追加指示 #5 ── combinations.avoid 対称化の残り1件」
- ユーザーの依頼により、本件は Cursor を介さず Claude Code が直接 `app.py` を編集して対応

### 実施内容詳細
- `五虎湯` の `combinations.avoid` に `麦門冬湯` を追加し、`麦門冬湯`→`五虎湯` の非対称を解消
- `KAMPO_DATABASE` 全27処方の `combinations.avoid` を機械的に突き合わせるスクリプトを実行し、他に非対称なペアが残っていないことを確認（0件）
- `python -m py_compile app.py` によるコンパイルチェック成功

### 確認事項・備考
- `combinations.avoid` は表示専用データであり、安全性判定ロジック（`check_combination_safety()`）に変更はない
- Claude Code レビュー完了・ユーザー承認まで git commit しない
---

## [2026-08-12] 実行 #7 ── modification_instructions.md 追加指示 #6（対象年齢0〜15歳拡張・新規症状3件・新規処方2件）

### 対応した指示
- modification_instructions.md「[2026-08-12] 追加指示 #6 ── 対象年齢の拡張（0〜6歳→0〜15歳）と新規症状3件（冷え・ニキビ・不安）の追加」

### 実施内容詳細
- `LIFE_STAGES` に `学童期`（7〜9歳 dose_factor 0.6、10〜12歳 0.7）・`思春期`（13〜15歳 0.85）を追加。既存の `乳児期`・`幼児期` は変更なし
- `AGE_NOTE_KEY_MAP` に `"7-9": "age_7_9"`, `"10-12": "age_10_12"`, `"13-15": "age_13_15"` を追加（`AGE_DOSE_FACTORS` / `VALID_AGE_KEYS` は `LIFE_STAGES` から自動導出）
- `KAMPO_DATABASE` 全29処方（既存27 + 新規2）の `notes` に `age_7_9` / `age_10_12` / `age_13_15` を追加。既存 `age_6` の記述・成人換算比率の流れを踏襲し、dose_factor（3/5・7/10・85%）と整合
- 既存27処方の `life_stage_eligible` を拡張：`"幼児期"` を含むものは原則 `"学童期"` `"思春期"` も追加
- `SYMPTOM_CATEGORIES` に新規症状3件を追加：`"冷え"`・`"ニキビ"`（虚弱体質・皮膚・その他）、`"不安"`（夜泣き・かんしゃく・神経症状）
- `SYMPTOM_LIFE_STAGES` を更新：新規3症状を追加、既存28症状のうち学童期・思春期にも起こりうる大半に `"学童期"` `"思春期"` を追加。乳幼児期特有（`乳児疝痛（コリック）`・`かんしゃく・疳の虫`・`夜泣き`・`湿疹・おむつかぶれ`）は現状維持（コメントで根拠明記）
- `KAMPO_DATABASE` に新規処方2件を追加：
  - `当帰四逆湯`（ツムラ38・冷え・虚証）。`life_stage_eligible` は `["学童期", "思春期"]` に限定（幼児期での実質使用は稀と判断しコメント明記）
  - `清上防風湯`（ツムラ58・ニキビ・実証〜中間証）。`life_stage_eligible` は `["幼児期", "学童期", "思春期"]`
- `HERB_COMPONENTS` に2処方分（メーカー別3社）を追加。麻黄・大黄・附子は0（非含有想定・要IF検証）
- `KAMPO_READING_KANA` に「当帰四逆湯」→「トウキシギャクトウ」、「清上防風湯」→「セイジョウボウフウトウ」を追加
- `SYMPTOM_KAMPO_WEIGHTS` に新規症状3件を追加：
  - `"冷え"`: 当帰四逆湯（主候補）、五積散・人参湯
  - `"ニキビ"`: 清上防風湯（主候補）、温清飲・消風散
  - `"不安"`: 抑肝散・甘麦大棗湯・柴胡桂枝湯（情緒不安定と整合）
- `COMBINATION_PATTERNS` に2件追加：当帰四逆湯+人参湯（冷え+虚弱）、清上防風湯+温清飲（ニキビ+皮膚乾燥）。`check_combination_safety()` で確認（danger なし、当帰四逆湯+人参湯は甘草 warning のみ）
- UI・コメント文言更新：
  - `app.py` 冒頭ドキュメント・症状数（31症状）・処方数（29処方）・併用パターンコメントを更新
  - `templates/index.html` の対象年齢表示を「小児（0〜15歳）。16歳以上には使用しないでください。」に更新
  - 推奨カード `notesHtml` に `age_7_9`（7〜9歳）・`age_10_12`（10〜12歳）・`age_13_15`（13〜15歳）の表示分岐を追加
- 検証：
  - データ整合性：29処方全件に新規年齢キー3件、`HERB_COMPONENTS` 29件×3メーカー、症状31件を確認
  - 推奨エンジン：冷え→当帰四逆湯、ニキビ→清上防風湯、不安→抑肝散 が各トップ候補になることを確認
  - `python -m py_compile app.py` 成功
  - `app.py`・`templates/` を "0〜6歳" "7歳以上" "28症状" "27処方" で検索し、古い記述残存なしを確認

### 確認事項・備考
- 本指示で追加する2処方を含め、学童期・思春期向け用量目安・新規症状の重み付けはすべて一般的な漢方知識に基づく暫定値であり、実運用前に医療従事者による検証が必須（既存の「レビュー待ち」表示の対象範囲を拡大する形）
- `check_combination_safety()` のロジック自体は変更なし。年齢層拡大は安全性チェックの厳格さを緩めない設計を維持
- Claude Code レビュー完了・ユーザー承認まで git commit しない
---

## [2026-08-12] 実行 #8 ── 実行#7（追加指示#6）の Claude Code レビューで検出した不整合の直接修正

### 対応した指示
- 実行#7（追加指示#6）に対する Claude Code レビューでの指摘事項

### 実施内容詳細
- `清上防風湯` の `life_stage_eligible` が `["幼児期", "学童期", "思春期"]` となっていたが、同処方の `notes.age_1_2` / `notes.age_3_5` / `notes.age_6` はいずれも「原則候補外。ニキビは学童期以降の適応を想定。」と明記されており矛盾していた。`_is_life_stage_eligible()` はライフステージ単位（年齢キー単位ではない）でフィルタするため、実際には幼児期（1〜2歳・3〜5歳・6歳）の児にも `清上防風湯`（ニキビ治療薬）が推奨候補として提示されうる状態になっていた（例: 幼児期のアトピー性皮膚炎の推奨候補に混入することを実機確認で再現）。
- `life_stage_eligible` を `["学童期", "思春期"]` に修正し、notes の記述と整合させた（`当帰四逆湯` と同様の限定パターン）。コメントで理由を明記。
- 修正後、Flask test client で以下を実機確認:
  - `思春期(13-15)` × `ニキビ` → 推奨candidate先頭が 清上防風湯・温清飲・消風散
  - `幼児期(3-5)` × `アトピー性皮膚炎` → 清上防風湯は候補から除外されることを確認
  - `学童期(7-9)` × `冷え` → 当帰四逆湯・五積散・人参湯
  - `幼児期(3-5)` × `不安` → 抑肝散・甘麦大棗湯・柴胡桂枝湯
- あわせて `python -m py_compile app.py` 成功、および全29処方・31症状のデータ整合性（notesキー・life_stage_eligible の値・SYMPTOM_KAMPO_WEIGHTS/COMBINATION_PATTERNS の参照先処方名）をスクリプトで突合し問題なしを確認。
- なお `app.py` の保存時に全体がCRLF改行に変換されていたため（元はLF）、Claude Code側でLFに戻して差分ノイズを解消した（内容変更なし）。

### 確認事項・備考
- 上記1件を除き、実行#7の内容（年齢区分・新規処方・新規症状のデータ）は構造的な不整合なし。医療内容自体は引き続きすべて暫定値・レビュー待ち。
- ユーザー承認まで git commit しない。
---
