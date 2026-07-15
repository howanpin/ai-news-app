# ai-news-app

ユーザープロフィールに基づいて、Gemini APIとTavily API（Web検索）を使い、
その人が興味を持ちそうな最新ニュースを毎日自動で要約し、Discordに通知するアプリです。

## 特徴

- `user_profile` に書かれたプロフィール内容をもとに、興味関心に合ったニュースを10件ピックアップ
- Gemini（`gemini-3.1-flash-lite`）のFunction Callingを使い、必要に応じてTavily APIでリアルタイムWeb検索を実行
- 生成された要約をDiscordのWebhookへ自動送信（2000文字超は自動分割）
- API呼び出し失敗時は指数バックオフで最大5回リトライ

## 動作の流れ

1. `user_profile` の内容と現在日付をプロンプトに埋め込み、Geminiに問い合わせ
2. `web_search`関数（Tavily API）を呼び出して最新情報を取得（5回）
3. 検索結果を踏まえて最終的な要約テキストを生成
4. 生成結果をDiscord Webhookへ送信

## ディレクトリ構成

```
.
├── .devcontainer/       # VS Code Dev Container設定
├── Dockerfile           # コンテナ実行用
├── app.py               # メインスクリプト
├── requirements.txt     # Python依存パッケージ
└── user_profile         # ニュース選定の基準となるユーザープロフィール（テキスト）
```

## 依存パッケージ

`requirements.txt`に記載されている主なパッケージ:

| パッケージ | 用途 |
|---|---|
| `google-genai` | Gemini APIクライアント |
| `tavily` | Tavily API（Web検索）クライアント |
| `requests` | Discord Webhookへの送信 |
| `python-dotenv` | `.env`ファイルからの環境変数読み込み |
| `black` | コードフォーマッタ（開発時のみ使用、実行には不要） |

## 必要な環境変数

`.env` ファイル（ローカル実行時）または実行環境の環境変数として、以下を設定してください。

| 変数名 | 説明 |
|---|---|
| `GEMINI_API_KEY` | Google Gemini APIキー |
| `TAVILY_API_KEY` | Tavily APIキー（Web検索用） |
| `DISCORD_WEBHOOK` | 通知先DiscordチャンネルのWebhook URL |
| `USER_PROFILE_PATH` | ユーザープロフィールファイルへのパス（例: `user_profile`） |

## ローカルでの実行方法

```bash
# 依存パッケージのインストール
pip install -r requirements.txt

# プロジェクト直下に.envファイルを作成し、上記の環境変数を記載
# 例:
# GEMINI_API_KEY=xxxx
# TAVILY_API_KEY=xxxx
# DISCORD_WEBHOOK=https://discord.com/api/webhooks/xxxx
# USER_PROFILE_PATH=user_profile

# 実行
python app.py
```

## コンテナでの実行
このプロジェクトは.devcontainerを使ったVS Code Dev Containers前提の構成です。
app.py内でload_dotenv()（python-dotenv）を呼んでおり、プロジェクト直下の.envファイルを実行時に自動で読み込みます。  
devcontainer内で以下を実行すればOKです。
```bash
pip install -r requirements.txt
python app.py
```
>補足：もし.devcontainerを使わず素のDockerイメージとして実行したい場合は、docker build -t ai-news-app .でビルドし、.envをコンテナにコピーしてからdocker run ai-news-appを実行する形になります。

## GitHub Actionsによる自動実行

`.github/workflows/`にワークフローを追加することで、毎朝自動実行できます。
リポジトリの **Settings → Secrets and variables → Actions** に `GEMINI_API_KEY` / `TAVILY_API_KEY` / `DISCORD_WEBHOOK` を登録し、`schedule`（cron）で定期実行するワークフローを設定してください。

> 補足：GitHub Actionsの`schedule`はUTC基準で指定します。また、60日間リポジトリへのコミットがないと自動的にスケジュール実行が無効化される点に注意してください。

## 注意事項

- 公開リポジトリで管理する場合、`user_profile`には興味関心のみを記載し、個人情報を含めないように注意してください。
- APIキー・Webhook URLは**絶対にリポジトリに直接コミットしない**でください（Secretsや`.env`で管理し、`.gitignore`に含めることを推奨します）。

## 補足情報
- Gemini APIは無料枠で運用する場合、新規発行のAPIキーでは一部モデルの使用が制限されたり、リクエスト過多でエラー落ちしたりすることがあります。  
リクエスト過多の場合は最大5回までリトライをかけていますが、モデル利用不可の場合はリトライしても実行不可となる点にご留意ください。

- 検索処理の実現については、Gemini API側に「グラウンディング機能」という内部検索機能が組み込まれていますが、2026年7月15日現在、無料枠だとまともに使えない（クレジット割り当てが枯渇してエラーになる）ため、別途Tavily（AI用検索API）を呼び出す形式にすることで対処しました。
