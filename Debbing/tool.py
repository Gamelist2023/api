import requests
import json
import uuid
from haralyzer import HarParser

# HARファイルのパス
har_file_path = 'har/test.har'  # 実際のHARファイル名に置き換える

# HARファイルを解析
with open(har_file_path, 'r', encoding='utf-8') as f:  # encoding='utf-8' を追加
    har_parser = HarParser(json.load(f))

# 必要なリクエストのエントリを取得 (適宜修正)
entries = har_parser.har_data['entries']
target_entry = next(
    (entry for entry in entries if 'api/chat/openai' in entry['request']['url']),
    None
)

if target_entry:
    # 認証情報とトレース情報を取得
    headers = target_entry['request']['headers']
    auth_token = next(
        (header['value'] for header in headers if header['name'] == 'X-lobe-chat-auth'),
        None
    )
    trace_info = next(
        (header['value'] for header in headers if header['name'] == 'X-lobe-trace'),
        None
    )
    session_cookie = next(
        (cookie['value'] for cookie in target_entry['request']['cookies'] if cookie['name'] == 'sl-session'),
        None
    )
else:
    print('Error: Target request entry not found in HAR file')
    auth_token = None
    trace_info = None
    session_cookie = None

if auth_token and trace_info and session_cookie:
    # トピックIDを生成
    topic_id = str(uuid.uuid4())

    url = 'https://robot.liujiarong.top/api/chat/openai'

    headers = {
        'Content-Type': 'application/json',
        'X-lobe-chat-auth': auth_token,
        'X-lobe-trace': trace_info,
        'Accept': 'application/json',  # レスポンス形式をJSONに変更
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
        'Referer': f'https://robot.liujiarong.top/chat?agent=&session=inbox&topic={topic_id}',
        'Cookie': f'sl-session={session_cookie}; LOBE_LOCALE=ja; LOBE_THEME_APPEARANCE=dark'
    }

    # リクエストボディ
    data = {
        'model': 'gpt-3.5-turbo',
        'stream': False,  # ストリーミングを無効にする
        'frequency_penalty': 0,
        'presence_penalty': 0,
        'temperature': 0.6,
        'top_p': 1,
        'messages': [
            {'content': 'こんにちは', 'role': 'user'}
        ]
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 200:
        print(response.json())
    else:
        print('Error:', response.status_code, response.text)