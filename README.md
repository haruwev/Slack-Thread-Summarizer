# Slack Thread Summarizer

Slack上のスレッドを自動的に要約し、オプションでNotionデータベースに保存するボットです。AnthropicのClaudeとAzure OpenAIの両方のLLMを切り替えて使用できます。

## 機能

- Slackスレッドの自動要約
- 構造化されたフォーマットでの要約生成
- Notionデータベースへの要約保存
- LLMモデルの動的切り替え（Claude / Azure OpenAI）
- キーワード自動抽出による検索性向上
- 参加者情報の取得とNotion連携

## セットアップ

### 前提条件

- Python 3.9以上
- Slack API アクセス権限
- Anthropic API キー（Claude使用時）
- Azure OpenAI リソース（Azure OpenAI使用時）
- Notion APIインテグレーション（Notion連携使用時）

### インストール方法

1. リポジトリをクローン
```bash
git clone https://github.com/yourusername/slack-thread-summarizer.git
cd slack-thread-summarizer
```

2. 環境変数の設定
.envファイルを作成し、必要な認証情報を設定します：
```bash
# Slack API 認証情報
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_APP_TOKEN=xapp-your-app-token-here

# LLM 設定 (BASE　のLLMを設定)
LLM_PROVIDER=azure_openai  # または "claude"

# Anthropic API 認証情報
ANTHROPIC_API_KEY=your-anthropic-api-key-here

# Azure OpenAI 認証情報
AZURE_OPENAI_API_KEY=your-azure-openai-api-key-here
AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4-turbo
AZURE_OPENAI_API_VERSION=2023-12-01-preview

# Notion API 連携
NOTION_API_KEY=secret_your-notion-api-key-here
NOTION_DATABASE_ID=your-notion-database-id-here
```
3. コンテナの立ち上げ
```bash
docker-compose up -d
```
## 使用方法

チャンネルに@summary_botを追加します．  
### 基本的な使い方

Slackでスレッド内に以下のコマンドを入力します：

* `@summary_bot` - スレッドを要約
* `@summary_bot notion` - 要約してNotionに保存
* `@summary_bot use_claude` - Claudeで要約
* `@summary_bot use_azure` - Azure OpenAIで要約
* `@summary_bot use_claude notion` - Claudeで要約してNotionに保存