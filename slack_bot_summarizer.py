import os
import logging
import re
import time
import json
from datetime import datetime
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import requests
from dotenv import load_dotenv
from llm_service import LLMService

# 環境変数のロード
load_dotenv()

# ロギングの設定
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, f"bot_{datetime.now().strftime('%Y%m%d')}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 環境変数から認証情報を取得
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")

# 使用するLLMプロバイダー（デフォルトはclaude）
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "claude").lower()

# ラウンドトリップタイムの記録用ディクショナリ
request_times = {}

# LLMサービスの初期化
llm_service = LLMService(provider=LLM_PROVIDER)

# Bolt アプリの初期化
app = App(token=SLACK_BOT_TOKEN)

@app.event("app_mention")
def handle_app_mentions(body, say, client):
    """
    @bot_nameメンションを処理する
    """
    event = body["event"]
    channel_id = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    user_id = event["user"]
    text = event["text"]
    
    # リクエスト開始時間を記録
    request_id = f"{channel_id}_{thread_ts}_{int(time.time())}"
    request_times[request_id] = time.time()
    
    logger.info(f"要約リクエストを受信: channel={channel_id}, thread={thread_ts}, user={user_id}")
    
    # Notionへの保存フラグ
    save_to_notion = "notion" in text.lower() or "ノーション" in text
    logger.info(f"Notionへの保存フラグ: {save_to_notion}")
    
    # プロバイダの切り替えフラグをチェック
    if "use_claude" in text.lower() or "クロード" in text:
        llm_service.switch_provider("claude")
        logger.info("LLMプロバイダをClaudeに切り替えました")
    elif "use_azure" in text.lower() or "アジュール" in text:
        llm_service.switch_provider("azure_openai")
        logger.info("LLMプロバイダをAzure OpenAIに切り替えました")
    
    # 現在のプロバイダをログに記録
    logger.info(f"現在のLLMプロバイダ: {llm_service.provider}")
    
    # スレッド内でのメンションかチェック
    if thread_ts and event.get("thread_ts"):  # スレッド内のメンションのみ処理
        # 処理中メッセージを送信
        initial_message = "スレッドを要約しています..."
        if save_to_notion:
            initial_message += "\nNotionにも保存します。"
            
        response = say(
            text=initial_message,
            thread_ts=thread_ts
        )
        processing_ts = response["ts"]
        
        try:
            # スレッド内のメッセージを取得
            logger.info(f"スレッドメッセージの取得を開始: {thread_ts}")
            thread_messages = get_thread_messages(client, channel_id, thread_ts)
            logger.info(f"取得したメッセージ数: {len(thread_messages)}")
            
            # チャンネル情報を取得
            channel_info = get_channel_info(client, channel_id)
            channel_name = channel_info.get("name", "unknown-channel")
            
            # LLM用にフォーマット
            thread_text = format_messages_for_llm(client, thread_messages)
            
            # スレッドのURLを生成
            thread_url = f"https://slack.com/archives/{channel_id}/p{thread_ts.replace('.', '')}"
            logger.info(f"スレッドURL: {thread_url}")
            
            # 要約の生成
            logger.info("LLMによる要約生成を開始")
            summary_start_time = time.time()
            summary = llm_service.generate_summary(thread_text)
            summary_duration = time.time() - summary_start_time
            logger.info(f"要約生成完了: 処理時間={summary_duration:.2f}秒")
            
            # 参加者とメールアドレスを取得（user_idも含む）
            participants = extract_participants_with_email(thread_messages, client)
            logger.info(f"スレッド参加者数: {len(participants)}")
            
            # Notionに保存するか判断
            notion_url = None
            if save_to_notion and NOTION_API_KEY and NOTION_DATABASE_ID:
                try:
                    # キーワードの抽出
                    logger.info("重要キーワードの抽出を開始")
                    keywords = llm_service.extract_keywords(summary)
                    logger.info(f"抽出されたキーワード: {keywords}")
                    
                    # Notionに保存
                    notion_response = save_summary_to_notion(
                        summary=summary,
                        channel_name=channel_name,
                        thread_url=thread_url,
                        thread_ts=thread_ts,
                        keywords=keywords,
                        participants=participants
                    )
                    
                    if notion_response and "url" in notion_response:
                        notion_url = notion_response["url"]
                        logger.info(f"Notionへの保存完了: {notion_url}")
                    else:
                        logger.error(f"Notionへの保存に失敗: {notion_response}")
                except Exception as e:
                    logger.error(f"Notionへの保存中にエラー発生: {e}", exc_info=True)
            
            # 応答メッセージの作成
            response_text = summary
            if notion_url:
                response_text += f"\n\n*<{notion_url}|📝 Notionにも保存しました>*"
            
            # 使用したLLMプロバイダを表示
            response_text += f"\n\n_Generated by: {llm_service.provider}_"
            
            # 処理中メッセージを更新
            client.chat_update(
                channel=channel_id,
                ts=processing_ts,
                text=response_text
            )
            
            # 処理時間の記録
            if request_id in request_times:
                total_duration = time.time() - request_times[request_id]
                logger.info(f"要約処理完了: リクエストID={request_id}, 合計処理時間={total_duration:.2f}秒")
                del request_times[request_id]
            
        except Exception as e:
            logger.error(f"Error processing thread: {e}", exc_info=True)
            # エラーメッセージを送信
            client.chat_update(
                channel=channel_id,
                ts=processing_ts,
                text=f"スレッドの要約中にエラーが発生しました: {str(e)}"
            )
    else:
        # スレッド外でのメンションの場合
        response_text = "スレッド内で @呼び出してください。スレッドの内容を要約します。\n"
        response_text += "利用可能なオプション:\n"
        response_text += "- `@summary_bot notion` - 要約をNotionにも保存\n"
        response_text += "- `@summary_bot use_claude` - Claudeを使用\n"
        response_text += "- `@summary_bot use_azure` - Azure OpenAIを使用\n"
        response_text += f"\n現在のLLMプロバイダ: *{llm_service.provider}*"
        
        say(response_text)
        logger.info("スレッド外でのメンションを検出: 処理をスキップします")

# 以下の関数は従来のまま
def get_thread_messages(client, channel_id, thread_ts):
    """
    スレッド内のメッセージを取得する
    """
    try:
        result = client.conversations_replies(
            channel=channel_id,
            ts=thread_ts
        )
        return result["messages"]
    except Exception as e:
        logger.error(f"Error fetching thread messages: {e}", exc_info=True)
        raise e

def get_channel_info(client, channel_id):
    """
    チャンネル情報を取得する
    """
    try:
        # チャンネルIDがCから始まる場合は標準的なパブリックチャンネル
        if channel_id.startswith('C'):
            result = client.conversations_info(channel=channel_id)
            return result["channel"]
        # Dから始まる場合はDM
        elif channel_id.startswith('D'):
            return {"name": "direct-message", "is_dm": True}
        # Gから始まる場合はグループDM
        elif channel_id.startswith('G'):
            return {"name": "group-message", "is_group": True}
        else:
            logger.warning(f"不明なチャンネルタイプ: {channel_id}")
            return {"name": f"unknown-channel-{channel_id}", "is_unknown": True}
    except Exception as e:
        logger.error(f"チャンネル情報取得中にエラー: {e}", exc_info=True)
        # エラーが発生しても最低限の情報を返す
        return {"name": f"channel-{channel_id}", "error": str(e)}

def format_messages_for_llm(client, messages):
    """
    LLM用にメッセージをフォーマットする
    """
    formatted_messages = []
    user_cache = {}  # ユーザー情報のキャッシュ
    
    for msg in messages:
        user_id = msg.get("user")
        # ボット自身のメッセージはスキップ
        if not user_id or msg.get("bot_id"):
            continue
            
        # ユーザー情報の取得（キャッシュから、なければAPIから）
        if user_id in user_cache:
            user_info = user_cache[user_id]
        else:
            try:
                user_info = client.users_info(user=user_id)["user"]
                user_cache[user_id] = user_info
            except Exception as e:
                logger.warning(f"ユーザー情報の取得に失敗: {user_id}, エラー: {e}")
                user_info = {"real_name": f"User {user_id}"}
        
        username = user_info.get("real_name", f"User {user_id}")
        
        # メッセージテキスト（メンションを処理）
        text = msg.get("text", "")
        text = process_mentions(text, client)
        
        # @botへのメンションを削除（要約対象から除外）
        text = re.sub(r'<@[A-Z0-9]+>', '', text).strip()
        
        # 空のメッセージはスキップ
        if not text:
            continue
            
        # タイムスタンプの処理
        ts = msg.get("ts", "unknown_time")
        
        formatted_messages.append(f"{username}: {text}")
    
    return "\n\n".join(formatted_messages)

def process_mentions(text, client):
    """
    テキスト内のSlackのメンション形式（<@USER_ID>）をユーザー名に置換
    """
    mention_pattern = r'<@([A-Z0-9]+)>'
    mentions = re.findall(mention_pattern, text)
    
    for user_id in mentions:
        try:
            user_info = client.users_info(user=user_id)
            user_name = user_info["user"]["real_name"]
            text = text.replace(f"<@{user_id}>", f"@{user_name}")
        except Exception as e:
            logger.warning(f"メンション処理中にエラー: {user_id}, エラー: {e}")
            # ユーザー情報の取得に失敗した場合はそのまま
            pass
    
    return text

def extract_participants_with_email(messages, client):
    """
    スレッドメッセージから参加者とそのメールアドレスを抽出する
    user_idも含めて返す（要約者の除外に使用）
    """
    participants = []  # 参加者情報のリスト
    user_cache = {}    # ユーザー情報のキャッシュ
    processed_users = set()  # 処理済みユーザーID
    
    for msg in messages:
        user_id = msg.get("user")
        # ボット自身のメッセージはスキップ
        if not user_id or msg.get("bot_id"):
            continue
            
        # すでに処理済みのユーザーはスキップ
        if user_id in processed_users:
            continue
            
        processed_users.add(user_id)
            
        # ユーザー情報の取得（キャッシュから、なければAPIから）
        if user_id in user_cache:
            user_info = user_cache[user_id]
        else:
            try:
                user_info = client.users_info(user=user_id)["user"]
                user_cache[user_id] = user_info
            except Exception as e:
                logger.warning(f"ユーザー情報の取得に失敗: {user_id}, エラー: {e}")
                user_info = {"real_name": f"User {user_id}", "profile": {}}
        
        username = user_info.get("real_name", f"User {user_id}")
        email = user_info.get("profile", {}).get("email", "")
        
        # ユーザー情報を追加（user_idも含める）
        participants.append({
            "user_id": user_id,
            "name": username,
            "email": email
        })
    
    return participants

def save_summary_to_notion(summary, channel_name, thread_url, thread_ts, keywords="", participants=None):
    """
    要約をNotionデータベースに保存する
    参加者のメールアドレスをリッチテキストとして保存する（APIの制限により）
    """
    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        logger.error("Notion API KeyまたはDatabase IDが設定されていません")
        return None
    
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    # 現在の日時を取得
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # スレッドのタイムスタンプから日時を解析
    thread_time = datetime.fromtimestamp(float(thread_ts)).strftime("%Y-%m-%d")
    
    # チャンネル名が辞書型の場合、名前フィールドを使用
    if isinstance(channel_name, dict):
        channel_name = channel_name.get("name", "unknown-channel")
    
    # タイトルを生成（主題の行から抽出）
    title = "Slack スレッド要約"
    for line in summary.split("\n"):
        if "**主題**:" in line:
            title_match = re.search(r'\*\*主題\*\*:\s*(.*)', line)
            if title_match:
                title = title_match.group(1).strip()
                break
    
    # データベースプロパティの設定
    properties = {
        "タイトル": {
            "title": [
                {
                    "text": {
                        "content": title
                    }
                }
            ]
        },
        "チャンネル": {
            "rich_text": [
                {
                    "text": {
                        "content": f"#{channel_name}"
                    }
                }
            ]
        },
        "保存日時": {
            "date": {
                "start": now.split()[0]  # YYYY-MM-DD形式
            }
        },
        "スレッド日時": {
            "date": {
                "start": thread_time  # YYYY-MM-DD形式
            }
        },
        "スレッドURL": {
            "url": thread_url
        }
    }
    
    # キーワードが提供されている場合は追加
    if keywords:
        properties["キーワード"] = {
            "rich_text": [
                {
                    "text": {
                        "content": keywords
                    }
                }
            ]
        }
    
    # 参加者情報が提供されている場合 - リッチテキストとして保存
    if participants and isinstance(participants, list):
        try:
            # 参加者のメールアドレスをリストとして整形
            participant_emails = []
            
            for person in participants:
                if person.get("email"):
                    name = person.get("name", "Unknown")
                    email = person.get("email")
                    participant_emails.append(f"{name} ({email})")
            
            # 参加者リストが空でなければプロパティに追加（リッチテキストとして）
            if participant_emails:
                logger.info(f"参加者情報を保存: {len(participant_emails)}人")
                # カンマと改行で区切ったテキストにする
                participant_text = ", ".join(participant_emails)
                
                properties["参加者情報"] = {
                    "rich_text": [
                        {
                            "text": {
                                "content": participant_text
                            }
                        }
                    ]
                }
            else:
                logger.warning("有効なメールアドレスを持つ参加者はいませんでした")
        except Exception as e:
            logger.error(f"参加者情報の処理中にエラー: {e}")
    
    # 参加者のタグもMultiSelectとして追加
    if participants and isinstance(participants, list):
        try:
            # 参加者の名前をマルチセレクトとして追加
            participant_names = []
            
            for person in participants:
                name = person.get("name", "")
                if name and len(name) > 0:
                    # Notionのマルチセレクトオプション形式に変換
                    participant_names.append({"name": name[:100]})  # 100文字を超えないようにする
            
            if participant_names:
                properties["参加者"] = {
                    "multi_select": participant_names[:100]  # 最大100個までのオプション
                }
        except Exception as e:
            logger.error(f"参加者タグの処理中にエラー: {e}")
    
    data = {
        "parent": { "database_id": NOTION_DATABASE_ID },
        "properties": properties,
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": f"元のスレッド: {thread_url}"
                            },
                            "annotations": {
                                "bold": True
                            }
                        }
                    ]
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": ""
                            }
                        }
                    ]
                }
            }
        ]
    }
    
    # 要約の内容をブロックに追加
    blocks = convert_summary_to_notion_blocks(summary)
    data["children"].extend(blocks)
    
    try:
        response = requests.post(
            "https://api.notion.com/v1/pages",
            headers=headers,
            json=data
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Notion APIエラー: {response.status_code}, {response.text}")
            return None
    except Exception as e:
        logger.error(f"Notion保存中のエラー: {e}", exc_info=True)
        return None

def convert_summary_to_notion_blocks(summary):
    """
    要約テキストをNotionのブロック形式に変換する
    """
    blocks = []
    current_heading = None
    bullet_points = []
    
    for line in summary.split("\n"):
        # 見出し行の処理
        if line.startswith("##"):
            # 前のセクションのリストがあれば追加
            if bullet_points:
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {"content": bullet_points[0]}}]
                    }
                })
                
                for point in bullet_points[1:]:
                    blocks.append({
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [{"type": "text", "text": {"content": point}}]
                        }
                    })
                bullet_points = []
            
            # 見出しを追加
            heading_text = line.strip('# ').strip()
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": heading_text}}]
                }
            })
            current_heading = heading_text
        
        # 箇条書きの処理
        elif line.strip().startswith("- "):
            bullet_text = line.strip()[2:].strip()
            bullet_points.append(bullet_text)
        
        # 空行の処理
        elif line.strip() == "":
            # 前のセクションのリストがあれば追加
            if bullet_points:
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {"content": bullet_points[0]}}]
                    }
                })
                
                for point in bullet_points[1:]:
                    blocks.append({
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [{"type": "text", "text": {"content": point}}]
                        }
                    })
                bullet_points = []
            
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": ""}}]
                }
            })
        
        # 通常のテキスト行の処理
        else:
            # 箇条書きの途中でなければ、段落として追加
            if not line.strip().startswith("-") and not bullet_points:
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": line.strip()}}]
                    }
                })
    
    # 最後のリストが残っていれば追加
    if bullet_points:
        blocks.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": bullet_points[0]}}]
            }
        })
        
        for point in bullet_points[1:]:
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": point}}]
                }
            })
    
    return blocks

@app.event("message")
def handle_message_events(body, logger):
    """
    デバッグ用: メッセージイベントをログに記録
    """
    logger.debug(f"Message event received: {body}")

if __name__ == "__main__":
    # Socket Mode でアプリを起動
    if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
        logger.error("環境変数 SLACK_BOT_TOKEN と SLACK_APP_TOKEN を設定してください")
        exit(1)
    
    # 使用するLLMプロバイダに基づいて必要な環境変数を確認
    if LLM_PROVIDER == "claude":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            logger.error("環境変数 ANTHROPIC_API_KEY が設定されていません")
            exit(1)
    elif LLM_PROVIDER == "azure_openai":
        if not os.environ.get("AZURE_OPENAI_API_KEY") or not os.environ.get("AZURE_OPENAI_ENDPOINT"):
            logger.error("環境変数 AZURE_OPENAI_API_KEY と AZURE_OPENAI_ENDPOINT が設定されていません")
            exit(1)
    
    # Notion 設定の確認
    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        logger.warning("Notion APIの設定が不完全です: NOTION_API_KEY または NOTION_DATABASE_ID が設定されていません")
        logger.warning("Notionへの保存機能は無効になります")
    
    # アプリケーションの起動
    try:
        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        logger.info(f"⚡️ Bolt アプリを起動しました！(LLM プロバイダ: {LLM_PROVIDER})")
        handler.start()
    except Exception as e:
        logger.critical(f"アプリの起動に失敗しました: {e}", exc_info=True)