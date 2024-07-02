import json
import re
from typing import List, Dict, Any

def extract_har_data(har_file_path: str, output_file_path: str) -> None:
    """
    HAR ファイルから必要な情報を抽出し、JSON ファイルに保存する。

    Args:
        har_file_path: HAR ファイルのパス。
        output_file_path: 出力 JSON ファイルのパス。
    """

    with open(har_file_path, 'r', encoding='utf-8') as f:
        har_data = json.load(f)

    extracted_data = {}

    # 1. "https://chatgpt.com/backend-api/conversation" を含み、
    #    "Accept: text/event-stream" を持つリクエストを抽出
    conversation_requests: List[Dict[str, Any]] = []
    for entry in har_data['log']['entries']:
        request = entry['request']
        if (
            "https://chatgpt.com/backend-api/conversation" in request['url']
            and any(header['name'].lower() == 'accept' and 'text/event-stream' in header['value'].lower()
                    for header in request['headers'])
        ):
            conversation_requests.append(request)
    extracted_data["conversation_requests"] = conversation_requests

    # 2. "https://chatgpt.com/" を含むリクエストを抽出
    session_requests: List[Dict[str, Any]] = []
    for entry in har_data['log']['entries']:
        request = entry['request']
        if "https://chatgpt.com/" in request['url']:
            session_requests.append(request)
    extracted_data["session_requests"] = session_requests

    # 3. アクセストークンの抽出
    access_token = None
    for entry in har_data['log']['entries']:
        response = entry.get('response')
        if response:
            content = response.get('content')
            if content:
                text = content.get('text')
                if text:
                    match = re.search(r'"accessToken":"(.*?)"', text)
                    if match:
                        access_token = match.group(1)
                        break
    extracted_data["access_token"] = access_token

    # 4. conversation_id の抽出
    conversation_id = None
    for entry in har_data['log']['entries']:
        request = entry.get('request')
        if request and "https://chatgpt.com/backend-api/conversation/init" in request['url']:
            response = entry.get('response')
            if response:
                content = response.get('content')
                if content:
                    text = content.get('text')
                    if text:
                        extracted_data["conversation_init_response"] = text
                        match = re.search(r'"conversation_id":"(.*?)"', text)
                        if match:
                            conversation_id = match.group(1)
                            break
    extracted_data["conversation_id"] = conversation_id

    with open(output_file_path, 'w', encoding='utf-8') as outfile:
        json.dump(extracted_data, outfile, indent=4)

# --- ファイルパスを指定 ---
har_file_path = "har/chatgpt.com.har"  # ここに HAR ファイルのパスを入力
output_file_path = "extracted_har_data.json"  # 出力 JSON ファイルのパス

# HAR ファイルから情報を抽出し、JSON ファイルに保存
extract_har_data(har_file_path, output_file_path)