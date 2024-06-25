## AI Chatbot Web API

このプロジェクトは、さまざまなAIプロバイダー（OpenAI、Googleなど）と連携してチャット形式で会話を楽しめるWeb APIを提供します。ユーザーは好みのAIを選択し、テキストを送信することで、人間らしい自然な回答を得ることができます。

### APIエンドポイント

**チャット:**

- `/chat`: 選択したAIプロバイダーとチャットを行う
    - メソッド: GET
    - パラメータ:
        - `provider`: AIプロバイダー名 (必須)
            - `OpenAI`
            - `Gemini`
            - `GeminiPro`
            - `Reka`
            - `Claude3`
            - `gpt-4o`
            - `ask`
            - `zundamon`
        - `prompt`: ユーザーが入力したテキスト (必須)
        - `system`: AIへの指示 (任意、デフォルトは"あなたは優秀なAIです。またユーザーの言語で回答します")
        - `user_id`: ユーザーを一意に識別するためのID（任意）
    - 返り値:
        - `response`: AIからの応答

**ストリーミングチャット:**

- `/stream`: 選択したAIプロバイダーとストリーミングチャットを行う
    - メソッド: POST
    - ボディ:
        - `provider`: AIプロバイダー名 (必須)
            - `OpenAI`
            - `Gemini`
        - `prompt`: ユーザーが入力したテキスト (必須)
        - `system`: AIへの指示 (任意、デフォルトは"あなたは優秀なAIです。またユーザーの言語で回答します")
        - `user_id`: ユーザーを一意に識別するためのID（任意）
    - 返り値:
        - `response`: AIからの応答 (ストリーミング形式)

**画像生成:**

- `/generate_image`: プロンプトに基づいて画像を生成する
    - メソッド: GET
    - パラメータ:
        - `prompt`: 生成する画像の説明文 (必須)
    - 返り値:
        - `images`: 生成された画像データ（Base64エンコード）のリスト



### リクエスト例 (Python)

```python
import requests
import base64

# APIエンドポイント
api_endpoint = "http://your-api-endpoint"  # WiFiのIPv4アドレスなどに置き換えてください

# チャットAPIへのリクエスト
def chat_with_ai(provider, prompt, user_id=None, system="あなたは優秀なAIです。またユーザーの言語で回答します"):
    url = f"{api_endpoint}/chat?provider={provider}&prompt={prompt}&system={system}"
    if user_id:
        url += f"&user_id={user_id}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()['response']
    else:
        return f"Error: {response.status_code}"

# ストリーミングチャットAPIへのリクエスト
def stream_chat_with_ai(provider, prompt, user_id=None, system="あなたは優秀なAIです。またユーザーの言語で回答します"):
    url = f"{api_endpoint}/stream"
    data = {
        "provider": provider,
        "prompt": prompt,
        "system": system
    }
    if user_id:
        data["user_id"] = user_id
    response = requests.post(url, json=data, stream=True)
    if response.status_code == 200:
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith("data: "):
                    print(decoded_line[6:], end='') # "data: " を削除して表示
    else:
        print(f"Error: {response.status_code}")

# 画像生成APIへのリクエスト
def generate_image(prompt):
    url = f"{api_endpoint}/generate_image?prompt={prompt}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()['images']
    else:
        return f"Error: {response.status_code}"

# 使用例
if __name__ == "__main__":
    provider = "OpenAI"  # 利用するAIプロバイダーを指定
    prompt = "こんにちは"
    user_id = "your-user-id"  # ユーザーIDを指定 (任意)

    # チャットAPIの呼び出し
    response_text = chat_with_ai(provider, prompt, user_id)
    print(f"AIからの応答: {response_text}")

    # ストリーミングチャットAPIの呼び出し
    print("ストリーミングチャットを開始します:")
    stream_chat_with_ai(provider, prompt, user_id)

    # 画像生成APIの呼び出し
    image_data = generate_image("美しい夕焼け")
    if isinstance(image_data, list):
        for i, image_base64 in enumerate(image_data):
            with open(f"image_{i}.png", "wb") as f:
                f.write(base64.b64decode(image_base64))
        print("画像を保存しました。")
    else:
        print(image_data)
```


### アンチボットシステム

このAPIには、不正なアクセスを防ぐためのアンチボットシステムが組み込まれています。

- 短時間に多数のリクエストを送信するユーザーは、一時的にブロックされる可能性があります。
- 同じコメントを繰り返し送信することも制限されます。

### 対応AIプロバイダー

- OpenAI: OpenAI の ChatGPT モデルを利用
- Gemini: Google の Gemini モデルを利用
- GeminiPro: Google の GeminiPro モデルを利用
- Reka: Reka.AI の Reka モデルを利用
- Claude3: Anthropic 社の Claude 3 モデルを利用 (Liaobots 経由)
- gpt-4o: Google の gpt-4o モデルを利用 (Liaobots 経由)
- DeepInfra: DeepInfra の Meta-Llama モデルを利用
- Zundamon: 東北ずん子公式 ChatGPT モデルを利用

**注記:**

- 各APIエンドポイントへのアクセスには、適切な認証が必要となる場合があります。
- 利用可能なAIプロバイダー、モデル、機能は、将来変更される可能性があります。
- `your-api-endpoint` を実際のAPIエンドポイントに置き換えてください。


