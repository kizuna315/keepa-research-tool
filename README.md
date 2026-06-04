# Keepa Research Tool

## 概要
Keepa Research Tool は、Keepa API を使って Amazon.co.jp の商品候補を取得し、スコアリング、判定、一覧化、CSV出力まで行うローカルWebアプリです。

MVPでは、ASIN指定リサーチとキーワード検索リサーチを中心に、商品確認、ステータス管理、メモ保存、CSV出力、安全なエラーハンドリングを提供します。

## MVP完成状態
- Phase 1〜Phase 12 完了
- MVP完成
- 最新の主要導線E2E、MVP smoke、エラーハンドリング横断テスト、全体テストが通過済み
- 追加Phase: UI/UXデザイン改善 完了

## UI/UXデザイン改善
MVP完成後の追加Phaseで、主要画面の見た目と操作性を改善しました。

- 共通レイアウト、ナビゲーション、カード、テーブル、フォーム、ボタン、バッジのデザインを統一
- ダッシュボード、商品一覧、商品詳細、新規リサーチ、設定画面の視認性を改善
- PC、タブレット、スマホ幅で崩れにくいレスポンシブ表示へ調整
- バックエンドロジック、URL、フォーム名、既存機能は変更していません

## 今回できること
- Keepa API Keyを設定画面から保存する
- Keepa APIトークン状態をダッシュボードで確認する
- ASINリストから商品情報を取得する
- キーワードと条件を指定して商品候補を検索する
- 取得した商品データをDBへ保存する
- 同一ASINの商品を重複登録せず更新する
- Keepaスコアを計算する
- `good / watch / bad / unknown` の判定を付ける
- `candidate / unreviewed / hold / excluded / supplier_search_pending` のステータスを管理する
- 商品一覧と商品詳細を表示する
- 商品一覧をフィルター・並び替えする
- 商品ごとにステータス変更とメモ保存を行う
- 全商品CSVを出力する
- 候補商品のみCSVを出力する
- Keepa APIエラー、DBエラー、CSVエラー時に安全なメッセージを表示する
- API Key、token、Authorizationなどの機密値を画面・ログ・DBエラーメッセージ・CSVへ出さない

## 今回できないこと
以下はMVP範囲外です。

- 仕入れ先検索
- 卸サイトの価格取得
- 楽天、Yahoo、Qoo10などとの価格比較
- FBA利益計算
- Amazon Seller Centralへの自動登録
- プライスター連携
- 自動発注
- 知財・真贋リスクの完全自動判定
- 利益確定判定
- 価格監視と通知
- ユーザーログイン機能

特に、仕入れ先検索機能は実装していません。`supplier_search_pending` はステータス値として保存するだけです。

## 技術構成
- Python
- Flask
- Flask-SQLAlchemy
- Flask-Migrate / Alembic
- SQLite
- requests
- pytest
- Bootstrap 5

主な構成:

```text
app/
  routes/       画面ルート
  services/     Keepa API、リサーチ、スコアリング、CSV、設定、エラー安全化
  templates/    HTMLテンプレート
  models.py     DBモデル
config.py        環境変数とパス設定
run.py           アプリ起動
migrations/      DBマイグレーション
data/            SQLite DB
exports/         CSV出力先
logs/            アプリログ
```

## セットアップ手順
Windows / PowerShell 前提の手順です。

```powershell
cd C:\Users\saita\OneDrive\デスクトップ\AI\keepa_resarch\keepa_resarch_system\keepa_research_tool
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

`.env` はGit管理しないでください。API Keyなどの秘密情報をREADMEやコミットに書かないでください。

## .env設定
`.env.example` には以下を用意しています。

```text
FLASK_APP=run.py
FLASK_ENV=development
FLASK_DEBUG=1
SECRET_KEY=change-me
DATABASE_URL=sqlite:///data/app.db
```

項目の意味:

- `FLASK_APP`: Flask CLIで使うアプリ指定
- `FLASK_ENV`: ローカル開発用の環境名
- `FLASK_DEBUG`: `1` の場合、`python run.py` 起動時にdebugを有効化
- `SECRET_KEY`: Flaskのセッション等に使うキー。ローカルMVPでは任意の値に変更可
- `DATABASE_URL`: SQLite DBの場所。標準では `data/app.db`

Keepa API Keyは `.env` ではなく、アプリ起動後に `/settings/` から保存します。

## DB初期化
依存関係をインストールし、`.env` を作成したあとにDBを初期化します。

```powershell
flask --app run.py db upgrade
```

補足:

- `data/`, `exports/`, `logs/` はアプリ起動時に自動作成されます
- `data/app.db` はSQLite DBです
- `migrations/` は既に用意されているため、通常は `db upgrade` だけで開始できます
- モデルを変更した場合のみ、新しいマイグレーションを作成します

モデル変更時の例:

```powershell
flask --app run.py db migrate -m "変更内容"
flask --app run.py db upgrade
```

## 起動方法
```powershell
python run.py
```

ブラウザで以下へアクセスします。

```text
http://127.0.0.1:5000
```

停止する場合は、ターミナルで `Ctrl + C` を押します。

## 画面URL
- `/` ダッシュボード
- `/settings/` 設定画面
- `/research/new` 新規リサーチ
- `/products/` 商品一覧
- `/products/<id>` 商品詳細
- `/products/export?target=all` 全商品CSV出力
- `/products/export?target=candidates` 候補商品のみCSV出力

## 使い方

### 1. 設定画面でKeepa API Keyを保存する
1. `/settings/` を開く
2. Keepa API Keyを入力する
3. 必要に応じて価格、出品者数、ランキング変動回数などのデフォルト条件を設定する
4. 保存する

保存済みAPI Keyの実値は画面に表示されません。API Key入力欄を空欄で保存した場合、既存API Keyは維持されます。

### 2. ASIN指定リサーチを実行する
1. `/research/new` を開く
2. ASIN指定フォームにリサーチ名を入力する
3. ASINを改行またはカンマ区切りで入力する
4. リサーチを実行する
5. 直近リサーチ履歴で `completed / failed` と件数を確認する

入力例:

```text
B0XXXXXXXX
B0YYYYYYYY
B0ZZZZZZZZ
```

または:

```text
B0XXXXXXXX, B0YYYYYYYY, B0ZZZZZZZZ
```

ASINは空白除去、大文字化、重複除外されます。

### 3. キーワードリサーチを実行する
1. `/research/new` を開く
2. キーワード検索フォームに条件を入力する
3. 取得上限件数を指定する
4. キーワードリサーチを実行する
5. 直近リサーチ履歴で結果を確認する
6. `/products/` で取得商品を確認する

入力できる主な条件:

- リサーチ名
- キーワード
- カテゴリーID
- 最低Amazon価格
- 最高Amazon価格
- 最低レビュー数
- 最大レビュー数
- 新品出品者数の最小・最大
- Amazon本体あり商品の除外
- 90日ランキング変動回数の最低条件
- 取得上限件数

取得上限件数はMVP安全運用として1〜100件です。

### キーワードリサーチの実運用目安
キーワードリサーチは、Keepaの `/search` でASINを取得したあと、各ASINの詳細データを `/product` で再取得します。
そのため、ASIN指定リサーチよりトークンを多く消費します。

推奨:

- `tokens_left` が 10〜19: `limit=1` 推奨
- `tokens_left` が 20〜29: `limit=1〜2` 推奨
- `tokens_left` が 30以上: `limit=5` を検討
- 初回や検証時は `limit=1〜2` から始める

実API検証では、`pet brush / limit=1〜2` で、`/search` → ASIN抽出 → `/product` 詳細再取得 → 正規化 → スコアリング → DB保存 → 商品一覧・詳細表示まで完走確認済みです。

注意:

- トークンが不足している場合は、実行前に安全停止します
- 取得上限を下げるか、トークン回復後に再実行してください
- `bad / excluded` になった場合でも、データ不足ではなく条件不一致による判定の場合があります

### 4. 商品一覧を見る
`/products/` で保存済み商品を確認できます。

表示項目:

- 商品画像
- 商品名
- ASIN
- ブランド
- Amazon現在価格
- 90日平均価格
- 新品出品者数
- Amazon本体の有無
- 90日ランキング変動回数
- Keepaスコア
- 判定
- ステータス
- 最終確認日時
- Amazonリンク
- Keepaリンク

フィルター:

- ステータス
- 判定
- ブランド
- 最低Keepaスコア
- 最高Keepaスコア

並び替え:

- 取得日新しい順
- Keepaスコア高い順
- ランキング変動回数多い順
- 価格安定度高い順
- 出品者数少ない順

### 5. 商品詳細を見る
商品一覧の商品名または詳細リンクから `/products/<id>` を開きます。

詳細画面では以下を確認できます。

- 商品基本情報
- 価格情報
- ランキング情報
- 出品者数
- Amazon本体在庫
- レビュー数・評価
- スコア内訳
- 判定
- ステータス
- 判定理由
- メモ
- Amazonリンク
- Keepaリンク

### 6. ステータス変更・メモ保存を行う
商品詳細画面で、以下のステータスへ手動変更できます。

- 未確認: `unreviewed`
- 候補: `candidate`
- 保留: `hold`
- 除外: `excluded`
- 仕入れ先検索待ち: `supplier_search_pending`

メモ欄に商品ごとのメモを保存できます。

### 7. CSV出力する
商品一覧画面からCSVをダウンロードできます。

- `全商品CSV出力`: すべての商品を出力
- `候補商品のみCSV出力`: `status = candidate` の商品のみ出力

CSV仕様:

- 文字コード: UTF-8 BOM付き
- 保存先: `exports/`
- ファイル名: `keepa_research_YYYYMMDD_HHMMSS.csv`
- `raw_keepa_json` は出力しない
- CSV本文内のAPI Key、token、Authorizationなどはマスク対象

## スコアリング・判定仕様
Keepaスコアは以下の合計です。

```text
Keepaスコア = 売れ行きスコア + 価格安定スコア + 競合スコア + リスクスコア
```

判定:

- 80点以上: `good`
- 60〜79点: `watch`
- 59点以下: `bad`
- 必要データ不足: `unknown`

判定後の初期ステータス:

- `good -> candidate`
- `watch -> unreviewed`
- `bad -> excluded`
- `unknown -> hold`

必要データ:

- `current_price`
- `avg_price_90`
- `sales_rank_drops_90`
- `new_offer_count`
- `amazon_in_stock`

## エラーハンドリング
以下のエラーは、安全なメッセージとして画面やDBに保存されます。

- API Key未設定
- API Key不正
- Keepa APIトークン不足
- Keepa API接続失敗
- Keepa APIレスポンス異常
- DB保存失敗
- CSV出力失敗
- 商品データ不足

方針:

- アプリ全体を落とさず、安全なメッセージを表示する
- `research_runs.error_message` に安全な日本語メッセージを保存する
- API Key、token、Authorizationはログ・画面・DB・CSVに出さない
- 機密値は `[REDACTED]` としてマスクする
- traceback全文を画面や `research_runs.error_message` に出さない

## Keepa APIトークン注意
ダッシュボードではKeepa APIトークン状態を表示します。

注意:

- トークン不足時はリサーチが失敗することがあります
- 失敗した場合は時間をおいて再実行してください
- API Key未設定または不正の場合は `/settings/` を確認してください
- Keepa API仕様やプランによりレスポンス構造が異なる可能性があります
- キーワードリサーチはASIN詳細を再取得するため、まず `limit=1〜2` から始めることを推奨します

## トラブルシューティング

### Keepa API Keyが未設定です
原因:
- `/settings/` にKeepa API Keyが保存されていない

対処:
- `/settings/` でKeepa API Keyを保存してください

### Keepa API Keyが正しくない可能性があります
原因:
- API Keyが間違っている
- Keepa側で認証に失敗している

対処:
- `/settings/` でAPI Keyを確認し、必要なら再保存してください

### Keepa APIのトークンが不足しています
原因:
- Keepa APIの利用可能トークンが不足している

対処:
- 時間をおいて再実行してください
- ダッシュボードのトークン状態を確認してください
- キーワードリサーチの場合は取得上限を `limit=1〜2` に下げてください

### Keepa APIへの接続に失敗しました
原因:
- ネットワーク不調
- Keepa API側の一時的な問題

対処:
- ネットワーク接続を確認してください
- 時間をおいて再実行してください

### CSV出力中にエラーが発生しました
原因:
- `exports/` へ書き込めない
- CSVファイル作成中にエラーが発生した

対処:
- `exports/` ディレクトリの書き込み権限を確認してください
- 既に開いているCSVファイルがあれば閉じてください

### DBが作成されない、またはテーブルがない
原因:
- DBマイグレーションが未実行

対処:

```powershell
flask --app run.py db upgrade
```

### ポート5000が使われている
原因:
- 既に別のアプリが5000番ポートを使っている

対処:
- 起動中の別アプリを停止してください
- 必要なら `run.py` のport設定を変更してください

## テスト実行
全体テスト:

```powershell
python -m pytest -q
```

Phase 11の横断エラーハンドリング確認:

```powershell
python -m pytest tests/test_error_handling.py -q
```

最新確認結果:

```text
python -m pytest tests/test_error_handling.py -q -> 11 passed
python -m pytest -q -> 337 passed
```

既知の警告:

- `datetime.utcnow()` の非推奨警告
- SQLAlchemy `Query.get()` のlegacy warning
- OneDrive環境でのpytest cache書き込み権限警告

現時点ではテスト失敗はありません。

## MVPの制限事項
- 仕入れ先検索は実装していない
- 利益計算は実装していない
- 実Keepa APIサンプルによる価格配列インデックス検証は今後必要
- Keepa検索レスポンスはプランやAPI仕様差分があり得る
- ユーザーログインや権限管理は実装していない
- UI/UX改善は主要画面の視認性改善まで。高度なデザインシステム化は今後の拡張対象

## 今後の拡張予定
- MVP仕上げの統合テスト
- セットアップ手順の実環境再確認
- 実Keepa APIサンプルによる正規化ロジック検証
- UIの追加磨き込み、アイコンやグラフ表示の検討
- CSV出力項目の追加検討
- 価格・利益計算機能の検討

## 補足
- `data/app.db` はGit管理しない
- `.env` はGit管理しない
- `exports/` のCSV出力ファイルは必要に応じて管理する
- API Keyや秘密情報をREADME、ログ、CSV、画面、テスト出力に出さない
