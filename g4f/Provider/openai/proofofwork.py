import random
import hashlib
import json
import base64
from datetime import datetime, timezone
from typing import Dict, Optional

def generate_proof_token(
    required: bool,
    seed: str = "",
    difficulty: str = "",
    user_agent: str = None,
    proofTokens: list = None,
    har_data: Optional[Dict] = None, 
):
    """
    Proof of Work トークンを生成する。

    Args:
        required (bool): PoW が必須かどうか。
        seed (str, optional): シード値. Defaults to "".
        difficulty (str, optional): 難易度. Defaults to "".
        user_agent (str, optional): ユーザーエージェント. Defaults to None.
        proofTokens (list, optional): 過去の proof token 情報. Defaults to None.
        har_data (Dict, optional): HAR データ. Defaults to None.

    Returns:
        str: 生成された PoW トークン。必須でない場合は None、生成に失敗した場合はフォールバックトークンを返す。
    """
    if not required:
        return None

    # extract_har_info_for_pow 関数をこのモジュール内に移動
    pow_info = extract_har_info_for_pow(har_data) if har_data else {}
    api_js_url = pow_info.get("api_js_url")
    dpl_value = pow_info.get("dpl_value")

    if proofTokens:
        config = proofTokens[-1]
    else:
        screen = random.choice([3008, 4010, 6000]) * random.choice([1, 2, 4])
        now_utc = datetime.now(timezone.utc)
        parse_time = now_utc.strftime('%a, %d %b %Y %H:%M:%S GMT')
        config = [
            screen,
            parse_time,
            None,
            0,
            user_agent,
            api_js_url if api_js_url else "https://tcr9i.chat.openai.com/v2/35536E1E-65B4-4D96-9D97-6ADB7EFF8147/api.js",
            dpl_value if dpl_value else "dpl=1440a687921de39ff5ee56b92807faaadce73f13",
            "en",
            "en-US",
            None,
            "plugins−[object PluginArray]",
            random.choice(["_reactListeningcfilawjnerp", "_reactListening9ne2dfo1i47", "_reactListening410nzwhan2a"]),
            random.choice(["alert", "ontransitionend", "onprogress"])
        ]

    diff_len = len(difficulty)
    for i in range(100000):
        config[3] = i
        json_data = json.dumps(config)
        base = base64.b64encode(json_data.encode()).decode()
        hash_value = hashlib.sha3_512((seed + base).encode()).digest()

        if hash_value.hex()[:diff_len] <= difficulty:
            return "gAAAAAB" + base

    fallback_base = base64.b64encode(f'"{seed}"'.encode()).decode()
    return "gAAAAABwQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + fallback_base  # フォールバックトークン

def extract_har_info_for_pow(har_data: Dict) -> Dict:
    """
    proofofworkに必要な情報をHARデータから抽出する
    """
    result = {}
    result["api_js_url"] = extract_api_js_url(har_data)
    result["dpl_value"] = extract_dpl_value(har_data)
    return result

def extract_api_js_url(har_data: Dict) -> Optional[str]:
    """
    HAR データから api.js の URL を抽出する
    """
    for entry in har_data['log']['entries']:
        url = entry['request']['url']
        if "tcr9i.chat.openai.com" in url and "api.js" in url:
            return url
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
                    return f"dpl={cookie['value']}"
    return None