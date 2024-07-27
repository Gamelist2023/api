from __future__ import annotations

import base64
import json
import os
import re
import logging
from typing import Optional, Dict, List, Tuple

from .crypt import decrypt, encrypt
from ...requests import StreamSession
from ...cookies import get_cookies_dir
from ... import debug
from .proofofwork import generate_proof_token, extract_har_info_for_pow  # extract_har_info_for_pow をインポート

# har_file.py のロガー設定
logger = logging.getLogger("har_file")

logger.setLevel(logging.DEBUG)

# ファイルハンドラーの設定
file_handler = logging.FileHandler('har_file.log')
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)



class NoValidHarFileError(Exception):
    """
    有効な HAR ファイルが見つからない、または必要な情報が抽出できない場合に発生するエラー。
    """



sessionUrl = "https://chatgpt.com/"
chatRequirementsUrl = "https://chatgpt.com/backend-api/sentinel/chat-requirements"
accessToken: Optional[str] = None
cookies: Optional[Dict[str, str]] = None
headers: Optional[Dict[str, str]] = None
proofTokens: List[List] = []
turnstileToken: Optional[str] = None
responseToken: Optional[str] = None
powResult: Optional[str] = None


def readHAR() -> Tuple[
    Optional[str], 
    Optional[Dict[str, str]], 
    Optional[Dict[str, str]], 
    List, 
    Optional[str], 
    Optional[str], 
    Optional[str], 
    Dict
]:
    """
    .har ファイルを検索し、必要な情報を抽出する。
    """
    logger.debug("readHAR() が呼び出されました")
    global accessToken, cookies, headers, proofTokens, turnstileToken, responseToken, powResult

    har_file_path = find_har_file()
    if not har_file_path:
        raise NoValidHarFileError("No valid .har file found.")

    logger.debug(f"処理する .har ファイル: {har_file_path}")

    try:
        with open(har_file_path, 'r', encoding='utf-8') as file:
            har_data = json.load(file)
    except (IOError, json.JSONDecodeError) as e:
        logger.exception(f".har ファイルの読み込み中にエラーが発生しました: {e}")
        raise NoValidHarFileError(f"Failed to read .har file: {e}") from e

    try:
        proofTokens = extract_proof_tokens(har_data)
        accessToken, cookies, headers = extract_auth_info(har_data)
        turnstileToken, responseToken, powResult = extract_chat_requirements_info(har_data)
    except Exception as e:
        logger.exception(f"データ抽出中にエラーが発生しました: {e}")
        raise NoValidHarFileError(f"Failed to extract data from .har file: {e}") from e

    if not accessToken:
        logger.error("accessToken が .har ファイル内に見つかりません")
        raise NoValidHarFileError("No accessToken found in .har file.")

    return accessToken, cookies, headers, proofTokens, turnstileToken, responseToken, powResult, har_data


def find_har_file():
    """
    指定ディレクトリから .har ファイルを検索する。

    Returns:
        str: 見つかった .har ファイルのパス。見つからない場合は None。
    """
    for root, _, files in os.walk(get_cookies_dir()):
        for file in files:
            if file.endswith(".har"):
                return os.path.join(root, file)
    return None

def extract_proof_tokens(har_data):
    """
    HAR データから proof tokens を抽出する。

    Args:
        har_data: HAR データ（辞書オブジェクト）。

    Returns:
        list: 抽出した proof tokens のリスト。
    """
    proofTokens = []
    for entry in har_data['log']['entries']:
        headers = {h['name'].lower(): h['value'] for h in entry['request']['headers']}
        if "openai-sentinel-proof-token" in headers:
            try:
                proof_token_str = headers["openai-sentinel-proof-token"].split("gAAAAAB", 1)[-1]
                proofTokens.append(json.loads(base64.b64decode(proof_token_str.encode()).decode()))
            except Exception as e:
                logger.error(f"Proof token のデコード中にエラー発生: {e}")
    return proofTokens



def extract_auth_info(har_data) -> Tuple[Optional[str], Dict[str, str], Dict[str, str]]:
    """
    HAR データから認証情報を抽出する。
    """
    for entry in har_data['log']['entries']:
        try:
            # レスポンスのcontentをチェック
            if (
                'content' in entry['response']
                and 'mimeType' in entry['response']['content']
                and entry['response']['content']['mimeType'] == "text/html"
                and 'text' in entry['response']['content']
            ):
                html_response = entry['response']['content']['text']

                # JavaScriptコード部分を抽出 (例: <script id="__NEXT_DATA__">〜</script>)
                match = re.search(
                    r'<script\s+id="__NEXT_DATA__"\s*type="application/json"\s*crossorigin="anonymous">[^<]*<\/script>',
                    html_response
                )
                
                if match:
                    script_content = match.group(0)

                    # script_content から accessToken を抽出
                    access_token_match = re.search(r'"accessToken":\s*"([^"]+)"', script_content)

                    if access_token_match:
                        accessToken = access_token_match.group(1)
                        logger.debug(f"JavaScript から accessToken を取得しました: {accessToken}")
                        cookies = {
                            c['name']: c['value']
                            for c in entry['request']['cookies']
                            if c['name'] != "oai-did"
                        }
                        headers = get_headers(entry)
                        return accessToken, cookies, headers

        except (KeyError, json.JSONDecodeError) as e:
            logger.warning(f"認証情報の抽出中にエラーが発生しました: {e}")
            continue

    return None, {}, {}  # デフォルト値として空の辞書を返す



def extract_chat_requirements_info(har_data):
    """
    HAR データから chat-requirements 情報を抽出する。

    Args:
        har_data (dict): HAR データ（辞書オブジェクト）。

    Returns:
        tuple: (turnstileToken, responseToken, data)
    """
    global headers  # グローバル変数 headers を使用することを宣言
    turnstileToken = responseToken = powResult = None
    data = None  # data を None で初期化
    for entry in har_data['log']['entries']:
        if entry['request']['url'] == chatRequirementsUrl:
            try:
                data = json.loads(entry["response"]["content"]["text"])
                if "turnstile" in data and "dx" in data["turnstile"]:
                    turnstileToken = data["turnstile"]["dx"]
                if "token" in data:
                    responseToken = data["token"]
                if "proofofwork" in data and "seed" in data["proofofwork"] and "difficulty" in data["proofofwork"]:
                    # required=True を追加
                    powResult = generate_proof_token(
                        required=True,
                        seed=data["proofofwork"]["seed"],
                        difficulty=data["proofofwork"]["difficulty"],
                        user_agent=headers.get("user-agent", ""),
                        proofTokens=proofTokens,
                        har_data=har_data  # har_data を渡す
                    )
                return turnstileToken, responseToken, data  # data を返す
            except (KeyError, json.JSONDecodeError) as e:
                logger.warning(f"chat-requirements 情報の抽出中にエラーが発生しました: {e}")
                continue
    return turnstileToken, responseToken, data  # data を返す


def get_headers(entry) -> dict:
    logger.debug("get_headers() が呼び出されました")
    return {h['name'].lower(): h['value'] for h in entry['request']['headers'] if h['name'].lower() not in ['content-length', 'cookie'] and not h['name'].startswith(':')}


def extract_api_js_url(har_data: Dict) -> Optional[str]:
    """
    HAR データから api.js の URL を抽出する
    """
    for entry in har_data['log']['entries']:
        url = entry['request']['url']
        if "tcr9i.chat.openai.com" in url and "api.js" in url:
            logger.debug(f"api.js の URL を取得しました: {url}")
            return url
    logger.warning("api.js の URL が見つかりませんでした")
    return None

def extract_dpl_value(har_data: Dict) -> Optional[str]:
    """
    HAR データから dpl パラメータの値を抽出する
    """
    for entry in har_data['log']['entries']:
        url = entry['request']['url']
        if "tcr9i.chat.openai.com" in url:
            for cookie in entry['request'].get('cookies', []):
                if cookie['name'] == 'dpl':
                    logger.debug(f"dpl パラメータの値を取得しました: {cookie['value']}")
                    return f"dpl={cookie['value']}" 
    logger.warning("dpl パラメータの値が見つかりませんでした")
    return None



async def getArkoseAndAccessToken(proxy: str) -> tuple[
    Optional[str], 
    Optional[str], 
    Optional[Dict[str, str]], 
    Optional[Dict[str, str]], 
    List, 
    Optional[str], 
    Optional[str], 
    Optional[str],
    Dict # har_data を受け取るために Dict を追加
]:
    """
    .har ファイルから認証情報を取得する。
    """
    global accessToken, cookies, headers, proofTokens, turnstileToken, responseToken, powResult

    # 関数内で har_data を初期化
    har_data = {}  

    if accessToken is None:
        logger.debug("accessToken が None です。 readHAR() を呼び出します")
        # readHAR() の戻り値に har_data を追加
        (
            accessToken, 
            cookies, 
            headers, 
            proofTokens, 
            turnstileToken, 
            responseToken, 
            powResult, 
            har_data  #  har_data を受け取る
        ) = readHAR()

        #  修正: data を正しく取得
        turnstileToken, responseToken, data = extract_chat_requirements_info(har_data)

        if data is None:
            raise NoValidHarFileError("chat-requirements data not found in .har file.")

        pow_info = extract_har_info_for_pow(har_data) 
        powResult = generate_proof_token(
            required=True,
            seed=data.get("proofofwork", {}).get("seed", ""),  
            difficulty=data.get("proofofwork", {}).get("difficulty", ""),
            user_agent=headers.get("user-agent", ""),
            proofTokens=proofTokens,
            har_data=har_data
        )

    return turnstileToken, accessToken, cookies, headers, proofTokens, responseToken, powResult, har_data