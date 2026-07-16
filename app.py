import os
import sys
import time
import requests
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
from tavily import TavilyClient
from google import genai
from google.genai import types

# 各種設定値
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
USER_PROFILE = Path(os.getenv("USER_PROFILE_PATH")).read_text(encoding = "utf-8")
CURRENT_DATE = datetime.now().strftime("%Y年%m月%d日")

# APIクライアント
GEMINI_CLIENT = genai.Client(api_key=GEMINI_API_KEY)
SEARCH_CLIENT = TavilyClient(api_key=TAVILY_API_KEY)

# プロンプト
PROMPT = f"""
    あなたは優秀なITアシスタントです。
    以下のユーザープロフィールに基づき、
    この人が今日最も興味を持ちそうな最新(特に24時間以内に発表されたものが望ましい)のニュースやトピックを【10個】【関心を幅広くカバーするように】ピックアップして、
    2000文字程度で要約してください。

    {USER_PROFILE}

    現在の日付：
    {CURRENT_DATE}

    【出力フォーマット】
    実行日時をyyyy/MM/ddで教えてください。
    各ニュースは以下の形式で2000文字程度で解説してください。
    
    ■ [タイトル]
    - 概要: （3行程度で分かりやすく要約）
    - 出典URL：(必ず記載し、特にURLの記載を忘れないでください。)
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
    # 検索
    response = SEARCH_CLIENT.search(
        query=query,
        max_results=max_results,
        search_depth="basic",
    )
    # タイトル・URL・要約を結果として返却
    results = [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "content": r.get("content"),
        }
        for r in response.get("results", [])
    ]
    return {"query": query, "results": results}


# Geminiがツールとして呼び出す機能を定義
search_function_declaration = types.FunctionDeclaration(
    name="web_search",
    description=(
        "現在の情報を取得するためのWeb検索機能です。"
        "検索クエリには過去の知識カットオフ時点ではなく、"
        "現在の日付を基準にした時点を使用してください。"
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
# 機能名とメソッドのマッピング
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
    # discordは一度に2000字以上送れないため、1900字ずつ分割送信する
    chunk_length = 1900
    for i in range(0, len(content), chunk_length):
        chunk = content[i : i + chunk_length]
        payload = {"content": chunk}
        response = requests.post(webhook_url, json=payload)
        time.sleep(0.5)
        if response.status_code not in (200, 204):
            print(f"Discord送信エラー: {response.status_code} {response.text}")


def ask_gemini():

    # 送信内容に最初の指示を設定
    contents = [
        types.Content(
            role="user",
            parts=[types.Part(text=PROMPT)],
        )
    ]

    MAX_ATTEMPT_COUNT = 5
    CURRENT_ATTEMPT_COUNT = 0
    try:
        # ツール呼び出しが終わるまでGeminiに聞く
        while CURRENT_ATTEMPT_COUNT < MAX_ATTEMPT_COUNT:

            response = GEMINI_CLIENT.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=contents,
                config=genai.types.GenerateContentConfig(
                    tools=[tools],
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(mode="ANY") #AUTOだと全く使わなくなるので、必ず使わせる
                    ),
                ),
            )

            # 最大試行回数以内で最終回答を得られた場合、終了
            if not response.function_calls:
                return response.text

            # ツールを実行する場合
            print(f"検索{CURRENT_ATTEMPT_COUNT+1}回目")

            # 送信内容にGeminiからの応答を追加
            contents.append(
                types.Content(
                    role="model",
                    parts=response.candidates[0].content.parts,
                )
            )

            # ツール実行
            for call in response.function_calls:
                print(call.args)
                # 未定義の機能を実行しようとした場合はエラー
                func = AVAILABLE_FUNCTIONS.get(call.name)
                if func is None:
                    raise Exception(f"未定義function: {call.name}")

                # 送信内容にツールの実行結果を追加
                result = func(**call.args)
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
                CURRENT_ATTEMPT_COUNT += 1

        # 最大試行回数に到達した場合はその旨を伝え、最終回答を生成させて返却
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
        response = GEMINI_CLIENT.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=contents,
            config=genai.types.GenerateContentConfig(tools=[]),
        )
        return response.text

    except Exception as e:
        print(f"GeminiのAPI呼び出し中にエラーが発生しました: {e}", file=sys.stderr)
        sys.exit(1)


def main():

    MAX_RETRY_COUNT = 5
    CURRENT_RETRY_COUNT = 0

    while CURRENT_RETRY_COUNT < MAX_RETRY_COUNT:

        try:
            # ニュースを取得・要約してもらう
            result_text = ask_gemini()
            print(result_text)

            # discordへ通知
            send_to_discord(DISCORD_WEBHOOK, result_text)

            return
        except Exception as e:

            CURRENT_RETRY_COUNT += 1

            print(f"処理失敗 {CURRENT_RETRY_COUNT}/{MAX_RETRY_COUNT}: {e}")
 
            # リトライ回数制限内であれば、少し待機してから再実行する
            if CURRENT_RETRY_COUNT >= MAX_RETRY_COUNT:
                raise

            time.sleep(2**CURRENT_RETRY_COUNT)


# エントリポイント
if __name__ == "__main__":
    main()
