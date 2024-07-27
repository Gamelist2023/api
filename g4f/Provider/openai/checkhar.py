import argparse
import json
import os
import base64 # 追加
from urllib.parse import unquote

# decrypt 関数の仮実装 (今回は使用しません)
def decrypt(bda, key):
    print(f"WARNING: 'decrypt' function is not implemented. Returning raw 'bda' value.")
    return bda

def check_har_keys(har_file_path, keys_to_check):
    """
    指定された HAR ファイルから tcr9i.chat.openai.com へのリクエストを調査し、
    指定されたキーと値を JSON ファイルに出力する。
    """
    results = {}

    try:
        with open(har_file_path, 'r', encoding='utf-8') as f:
            har_data = json.load(f)
        print(f"HAR file loaded: {har_file_path}")

        for entry in har_data['log']['entries']:
            request_url = entry['request']['url']
            print(f"Processing request: {request_url}")

            # chatgpt.com/backend-api/sentinel/chat-requirements を解析
            if "chatgpt.com/backend-api/sentinel/chat-requirements" in request_url:
                print(f"Found chat-requirements request: {request_url}")
                # レスポンスボディからキーを検索
                if 'content' in entry['response'] and 'text' in entry['response']['content']:
                    try:
                        response_json = json.loads(entry['response']['content']['text'])
                        print("Found response JSON")
                        for key in keys_to_check:
                            if key in response_json:
                                print(f"Found key in response JSON: {key} - {response_json[key]}")
                                results[key] = response_json[key]
                    except json.JSONDecodeError as e:
                        print(f"Failed to decode response JSON: {e}")

            # chatgpt.com/ へのリクエストを解析
            elif "chatgpt.com/" in request_url: 
                print(f"Found chatgpt.com/ request: {request_url}")

                # '__Secure-next-auth.session-token' クッキーの値から accessToken を取得する
                if 'cookies' in entry['response']:
                    for cookie in entry['response']['cookies']:
                        if cookie['name'] == '__Secure-next-auth.session-token':
                            encoded_payload = cookie['value'].split('.')[1]
                            padding = '=' * (4 - (len(encoded_payload) % 4))  # パディングを追加
                            decoded_payload = base64.urlsafe_b64decode(encoded_payload + padding).decode("utf-8")
                            payload_json = json.loads(decoded_payload)
                            accessToken = payload_json.get("accessToken")
                            if accessToken: # accessToken が見つかったら結果に追加
                                print(f"Found accessToken in '__Secure-next-auth.session-token': {accessToken}")
                                results['accessToken'] = accessToken 
                            break  

        print(f"Results: {results}")
        with open('checked.json', 'w', encoding='utf-8') as outfile:
            json.dump(results, outfile, indent=4)
        print("Results saved to 'checked.json'")

    except (IOError, json.JSONDecodeError) as e:
        print(f"Error processing HAR file: {e}")


def get_headers(entry):
    return {h['name'].lower(): h['value'] for h in entry['request']['headers']}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check for specific keys in a HAR file.")
    parser.add_argument("har_file", help="Path to the HAR file.")
    args = parser.parse_args()

    har_file_path = args.har_file

    # チェックしたいキーのリスト
    keys_to_check = [
        "persona", "token", "arkose", "turnstile", "proofofwork", "accessToken"
    ]

    if har_file_path:
        print(f"Checking keys in HAR file: {har_file_path}")
        check_har_keys(har_file_path, keys_to_check)
        print("Key values extracted. See results in 'checked.json'")
    else:
        print("Error: Please specify the path to the HAR file.")