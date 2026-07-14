import os
import sys
import time
import requests
from dotenv import load_dotenv
from datetime import datetime
from tavily import TavilyClient
from google import genai
from google.genai import types

# 各種設定値
load_dotenv()
AI_API_KEY = os.getenv("AI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
CURRENT_DATE = datetime.now().strftime("%Y年%m月%d日")

# APIクライアント
AI_CLIENT = genai.Client(api_key=AI_API_KEY)
SEARCH_CLIENT = TavilyClient(api_key=TAVILY_API_KEY)

# ユーザーの好み・プロンプト
USER_PROFILE = """
    【ユーザープロフィール】
    - 年齢・職種: 2001年生まれのITエンジニア
    - 関心のある技術分野: 
        - ソフトウェアアーキテクチャ、クリーンコード、DDD（ドメイン駆動設計）
        - バックエンド開発（Java, Python）
    - その他の趣味: ウェイトトレーニング（ベンチプレスなど）、ボディメイク・栄養管理
    """
PROMPT = f"""
    あなたは優秀なITアシスタントです。
    以下のユーザープロフィールに基づき、この人が今日最も興味を持ちそうな最新のニュースや技術動向、トピックを【10個】ピックアップして、
    2000文字以内で要約してください。

    {USER_PROFILE}

    現在の日付：
    {CURRENT_DATE}

    【出力フォーマット】
    実行日時をyyyy/MM/ddで教えてください。
    各ニュースは以下の形式で2000文字以内で解説してください。
    
    ■ [タイトル]
    - 概要: （3行程度で分かりやすく要約）
    - なぜおすすめか: （ユーザーの興味とどう関連しているか）
    """


def web_search(query: str, max_results: int = 5) -> dict:
    """
    Tavily APIでWeb検索を行い、結果を返す

    Args:
        query:検索クエリ
        max_results:最大検索回数

    Returns:
        渡したクエリと、検索結果（タイトル・URL・要約）のリスト
    """
    response = SEARCH_CLIENT.search(
        query=query,
        max_results=max_results,
        search_depth="basic",
    )
    # Geminiに返すのは軽量なJSONにしておく（タイトル・URL・要約のみ）
    results = [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "content": r.get("content"),
        }
        for r in response.get("results", [])
    ]
    return {"query": query, "results": results}


# 検索機能（function calling）
search_function_declaration = types.FunctionDeclaration(
    name="web_search",
    description=(
        "現在の情報を取得するためのWeb検索機能です。"
        "検索クエリには過去の知識カットオフ年ではなく、"
        "現在の日付を基準にした年を使用してください。"
        "最新ニュース、リリース情報、アップデート情報を調査する場合は必ず使用してください。"
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "query": types.Schema(
                type=types.Type.STRING,
                description="検索したいクエリ文字列",
            ),
            "max_results": types.Schema(
                type=types.Type.INTEGER,
                description="取得する検索結果の最大件数（デフォルト5）",
            ),
        },
        required=["query"],
    ),
)
tools = types.Tool(function_declarations=[search_function_declaration])
# 実際に呼び出す関数名 -> Python関数のマッピング
AVAILABLE_FUNCTIONS = {
    "web_search": web_search,
}


def send_to_discord(webhook_url: str, content: str):
    """
    指定された宛先と送信内容で、discordのメッセージ送信を行います。
    2000文字を超過した場合、1900字ずつに分けて送信します。

    Args:
        webhook_url: 送信宛先のWebHookURL
        content: 送信内容
    """
    # discordは一度に2000字以上送れないので分割送信する
    chunk_length = 1900
    for i in range(0, len(content), chunk_length):
        chunk = content[i : i + chunk_length]
        payload = {"content": chunk}
        response = requests.post(webhook_url, json=payload)
        time.sleep(0.5)
        if response.status_code not in (200, 204):
            print(f"Discord送信エラー: {response.status_code} {response.text}")


def ask_ai():

    contents = [
        types.Content(
            role="user",
            parts=[types.Part(text=PROMPT)],
        )
    ]

    max_attempt_count = 5
    current_attempt_count = 1

    try:
        # ツール呼び出し（fuction calling）が終わるまでGeminiに聞く
        while current_attempt_count <= max_attempt_count:

            response = AI_CLIENT.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=contents,
                config=genai.types.GenerateContentConfig(
                    tools=[tools],
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(mode="ANY")
                    ),
                ),
            )

            # ツール呼び出しなし時
            if not response.function_calls:
                return response.text

            # ツール呼び出しあり時
            print(f"検索{current_attempt_count}回目")
            # 履歴へ追加
            contents.append(
                types.Content(
                    role="model",
                    parts=response.candidates[0].content.parts,
                )
            )
            # ツール呼び出し実行
            for call in response.function_calls:
                print(call.args)
                func = AVAILABLE_FUNCTIONS.get(call.name)

                if func is None:
                    raise Exception(f"未定義function: {call.name}")

                result = func(**call.args)

                # 実行結果をGeminiへ返す
                contents.append(
                    types.Content(
                        role="tool",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=call.name,
                                    response=result,
                                )
                            )
                        ],
                    )
                )
                current_attempt_count += 1

        # 最大回数到達
        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=(
                            "検索回数の上限に達しました。"
                            "これ以上ツールを使用せず、"
                            "現在取得済みの情報のみを元に最終回答してください。"
                        )
                    )
                ],
            )
        )
        # 最大回数まで検索した結果をもとに、最終回答を生成・返却
        response = AI_CLIENT.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=contents,
            config=genai.types.GenerateContentConfig(tools=[]),
        )
        return response.text

    except Exception as e:
        # エラーログ吐き出し・呼び出し元に異常終了ステータス返却で終了
        print(f"AIのAPI呼び出し中にエラーが発生しました: {e}", file=sys.stderr)
        sys.exit(1)


def main():

    retry_count = 0
    retry_max_count = 5

    while retry_count < retry_max_count:

        try:
            # AIにニュースを取得してもらう
            result_text = ask_ai()
            print(result_text)

            # discordへ通知
            send_to_discord(DISCORD_WEBHOOK, result_text)

            return  # 成功したら終了

        except Exception as e:

            retry_count += 1

            print(f"処理失敗 {retry_count}/{retry_max_count}: {e}")
            ## 少し待機してから再実行
            time.sleep(2**retry_count)

            if retry_count >= retry_max_count:
                raise


# エントリポイント
if __name__ == "__main__":
    main()
