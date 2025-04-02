import os
import logging
import anthropic
from openai import AzureOpenAI

logger = logging.getLogger(__name__)

class LLMService:
    """
    LLMサービスを抽象化するクラス
    Claude と Azure OpenAI を切り替え可能
    """
    
    def __init__(self, provider="claude"):
        """
        LLMサービスの初期化
        
        Parameters:
        provider (str): "claude" または "azure_openai" を指定
        """
        self.provider = provider.lower()
        
        # 環境変数の取得
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.azure_openai_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        self.azure_openai_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        self.azure_openai_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4")
        self.azure_openai_api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2023-12-01-preview")
        
        # クライアントの初期化
        self.claude_client = None
        self.azure_openai_client = None
        
        # プロバイダに基づいてクライアントを初期化
        self._initialize_client()
    
    def _initialize_client(self):
        """
        指定されたプロバイダに基づいてクライアントを初期化
        """
        if self.provider == "claude":
            if not self.anthropic_api_key:
                logger.error("ANTHROPIC_API_KEY環境変数が設定されていません")
                raise ValueError("ANTHROPIC_API_KEY環境変数が必要です")
            
            self.claude_client = anthropic.Anthropic(api_key=self.anthropic_api_key)
            logger.info("Claudeクライアントを初期化しました")
            
        elif self.provider == "azure_openai":
            if not self.azure_openai_api_key or not self.azure_openai_endpoint:
                logger.error("Azure OpenAIの設定が不完全です")
                raise ValueError("AZURE_OPENAI_API_KEYとAZURE_OPENAI_ENDPOINTの両方が必要です")
            
            self.azure_openai_client = AzureOpenAI(
                api_key=self.azure_openai_api_key,
                api_version=self.azure_openai_api_version,
                azure_endpoint=self.azure_openai_endpoint
            )
            logger.info("Azure OpenAIクライアントを初期化しました")
            
        else:
            logger.error(f"未対応のプロバイダ: {self.provider}")
            raise ValueError(f"プロバイダは'claude'または'azure_openai'のいずれかを指定してください")
    
    def switch_provider(self, provider):
        """
        LLMプロバイダを切り替える
        
        Parameters:
        provider (str): "claude" または "azure_openai" を指定
        """
        if provider.lower() not in ["claude", "azure_openai"]:
            logger.error(f"未対応のプロバイダ: {provider}")
            raise ValueError(f"プロバイダは'claude'または'azure_openai'のいずれかを指定してください")
        
        # プロバイダが変更された場合のみ初期化
        if provider.lower() != self.provider:
            self.provider = provider.lower()
            self._initialize_client()
            logger.info(f"LLMプロバイダを{self.provider}に切り替えました")
        
        return self.provider
    
    def generate_summary(self, thread_text):
        """
        スレッドの要約を生成する
        
        Parameters:
        thread_text (str): 要約するスレッドのテキスト
        
        Returns:
        str: 生成された要約
        """
        system_prompt = """
あなたはSlackのスレッドを要約する専門AIアシスタントです。
以下のSlackスレッドの内容を分析し、次の形式で簡潔に要約してください：

## スレッド要約
- **主題**: [議論の主なテーマ]
- **参加者**: [会話に参加している人々のリスト]

## 主要ポイント
- [重要なポイントを箇条書きで、最大5つ]

## 結論/次のアクション
- [合意された事項や次のアクションがあれば記載]

## 未解決の質問
- [未解決の質問があれば記載]

要約は簡潔でありながら、元のスレッドの重要な情報をすべて含むものにしてください。
各ユーザーの発言内容を「〜さんが〜と言った」という形式で要約に含めてください。
"""
        
        if self.provider == "claude":
            return self._generate_with_claude(system_prompt, thread_text)
        else:
            return self._generate_with_azure_openai(system_prompt, thread_text)
    
    def extract_keywords(self, summary):
        """
        要約から重要なキーワードを抽出する
        
        Parameters:
        summary (str): 要約テキスト
        
        Returns:
        str: 抽出されたキーワード（カンマ区切り）
        """
        system_prompt = """
以下のSlackスレッド要約から重要なキーワード（専門用語、プロジェクト名、技術名など）を最大10個抽出してください。
キーワードはカンマ区切りのリストとして返してください。
"""
        
        if self.provider == "claude":
            return self._generate_with_claude(system_prompt, summary, max_tokens=100)
        else:
            return self._generate_with_azure_openai(system_prompt, summary, max_tokens=100)
    
    def _generate_with_claude(self, system_prompt, content, max_tokens=1000):
        """
        Claude APIを使用して生成する
        """
        try:
            response = self.claude_client.messages.create(
                model="claude-3-haiku-20240307",
                system=system_prompt,
                max_tokens=max_tokens,
                messages=[
                    {"role": "user", "content": content}
                ]
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Claude APIでのエラー: {e}", exc_info=True)
            raise
    
    def _generate_with_azure_openai(self, system_prompt, content, max_tokens=1000):
        """
        Azure OpenAI APIを使用して生成する
        """
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ]
            
            response = self.azure_openai_client.chat.completions.create(
                model=self.azure_openai_deployment,
                messages=messages,
                max_tokens=max_tokens
            )
            
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Azure OpenAI APIでのエラー: {e}", exc_info=True)
            raise