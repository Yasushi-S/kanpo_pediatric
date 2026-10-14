# CLAUDE.md（kanpo_pediatric）

---

## このプロジェクトのアプリ種別

VPSで一般公開（インターネット経由アクセス）
※ ConoHa VPS「ClinicPortal」上で運用。ドメイン: `https://kanpo-pediatric.shitano-clinic.jp`

### 例外: 認証なしの一般公開（意図的）
- 本アプリは誰でも利用できるよう、認証を設けずに公開する
- 理由: 患者データを保存せず、推奨データはアプリ内固定で外部から書き換えできないため
- そのため「VPS公開アプリ」要件のうち、認証・ログイン試行制限は推奨画面には適用しない
- HTTPS、操作ログ、SECRET_KEY の .env 管理は引き続き必須
- 操作ログに個人を特定しうる情報（IP と入力症状の組み合わせ等）を残さない
- **要望メモ機能のみ**パスワード保護（`MEMO_PASSWORD_HASH`）する

---

## 開発環境

- アプリ種別　: Flask（Python）製 Web アプリ（小児科漢方薬推奨・対象年齢 0〜15歳・複数メーカー）
- アクセス方法: `https://kanpo-pediatric.shitano-clinic.jp`
- 実行環境　　: ConoHa VPS（Ubuntu）、gunicorn + systemd、venv
- VPS パス　: アプリ `/apps/kanpo_pediatric`、venv `/apps/kanpo_pediatric/venv/bin/python`
- gunicorn バインド: `127.0.0.1:50010`（`app.py` 内の `port=50005` は院内PC時代の値で、VPS では使わない）
- 書き込み先: リポジトリ内 `instance/`（`operation_log.db`・`requests.db`）。`.gitignore` で除外済み

---

## ブラッシュアップ手順

ユーザーが「ブラッシュアップして」と言ったときに実施する。AI API は使わない。

1. 未対応メモの取得  
   `ssh -o BatchMode=yes deploy@160.251.200.215` で `/apps/kanpo_pediatric` に入り、venv の Python で  
   `/apps/kanpo_pediatric/venv/bin/python /apps/kanpo_pediatric/tools/requests_cli.py list --status open --json` を実行する。

2. 各メモの内容を確認し、修正指示書を作成する  
   - 症状追加: エビデンスの高い情報源（日本東洋医学会、PubMed、J-STAGE、PMDA添付文書、ツムラ／クラシエ／コタロー医療関係者向け、Cochrane 等）を調査し、重み（既存尺度 2〜5）・候補漢方（既存収録外も可）・併用候補・ライフステージ適否・根拠を `docs/修正指示書.md` にまとめる  
   - 併用追加: 既存 `COMBINATION_PATTERNS` / `check_combination_safety()` と年齢換算を踏まえて指示書を書く  
   - 改善要望・その他: 影響範囲をコード調査したうえで指示書を書く  
   - 要望が曖昧、または医学的判断が必要なものはユーザーに確認する

3. ユーザー承認 → Cursor 実装 → レビュー → ユーザー承認で commit/push → VPS で `git pull` と `sudo systemctl restart kanpo_pediatric`

4. 反映後、該当メモを対応済みにする  
   `/apps/kanpo_pediatric/venv/bin/python /apps/kanpo_pediatric/tools/requests_cli.py resolve <id> --status done --note "修正指示 #N で対応"`  
   （見送りの場合は `--status skipped`）

### 要望メモ用パスワードハッシュ（ユーザーが VPS で設定。Cursor は `.env` を触らない）

```bash
cd /apps/kanpo_pediatric && ./venv/bin/python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('ここにパスワード'))"
```

出力を `.env` に `MEMO_PASSWORD_HASH=...` として追加し、サービスを再起動する。

---

## 開発フロー（必ず守ること）

```
フェーズ1: 現状把握（コード調査）
フェーズ2: 指示書作成（docs/修正指示書.md 末尾追記）
フェーズ3: ユーザー承認（必須）
フェーズ4: Cursor コーディング → docs/修正実行書.md に記録
フェーズ5: Claude Code レビュー
フェーズ6: ユーザー動作確認 → git commit・push
```

- 既存の推奨ロジック・薬剤データ（医学的内容）を無断で変更しない
- 生薬量・年齢換算係数・危険閾値など臨床安全性に関わる数値を変更する場合は根拠をコメントしユーザー確認を取る
- Claude Code のレビューが完了するまで git commit しない
