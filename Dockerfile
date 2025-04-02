
FROM python:3.9-slim

WORKDIR /app

# 依存関係をコピーしてインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションファイルをコピー
COPY slack_bot_summarizer.py .
COPY llm_service.py .
COPY .env .

# Pythonがバッファリングなしで出力するように
ENV PYTHONUNBUFFERED=1

# ログディレクトリを作成
RUN mkdir -p /app/logs

# アプリケーションを実行
CMD ["python", "slack_bot_summarizer.py"]