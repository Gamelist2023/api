import time
from datetime import datetime, timedelta
from collections import defaultdict
import json
import os

# ファイル名
BLOCKED_USERS_FILE = "blocked_users.json"
BAN_HISTORY_FILE = "ban_history.json"
USE_TOKEN_LIST_PATH = "useTokenList.json"

# リクエスト制限の設定
class RequestLimit:
    def __init__(self, interval, count):
        self.interval = timedelta(seconds=interval)
        self.count = count

# トークン有無別のリクエスト制限
request_limits = {
    True: RequestLimit(interval=1, count=10),    # トークンあり
    False: RequestLimit(interval=1, count=3)     # トークンなし
}

# 1日あたりの最大リクエスト数
max_requests_per_day = {
    True: 1000,  # トークンあり
    False: 100   # トークンなし
}

# BAN期間の設定
ban_durations = {
    "short": timedelta(minutes=5),  # 短期間BAN
    "long": timedelta(hours=24)     # 長期間BAN
}

# ユーザーごとのリクエスト履歴
user_requests = defaultdict(list)

# JSONファイルからデータを読み込む
def load_data(file_path):
    """JSONファイルからデータを読み込みます。ファイルが存在しない場合は空の辞書を返し、ファイルを新規作成します。

    Args:
        file_path (str): 読み込むJSONファイルのパス。

    Returns:
        dict: 読み込んだデータ。ファイルが存在しない場合は空の辞書。
    """
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return json.load(f)
    else:
        # ファイルが存在しない場合は空の辞書を書き込んで新規作成
        with open(file_path, 'w') as f:
            json.dump({}, f)
        return {}

# JSONファイルにデータを保存する
def save_data(file_path, data):
    with open(file_path, 'w') as f:
        json.dump(data, f)

# ブロックユーザー情報を読み込む
blocked_users = load_data(BLOCKED_USERS_FILE)

# BAN履歴を読み込む
ban_history = load_data(BAN_HISTORY_FILE)

# トークン使用回数情報を読み込む
use_token_list = load_data(USE_TOKEN_LIST_PATH)

def check_and_ban(user_id: str, request, token: str = None):
    """ユーザーがボットかどうかチェックし、必要に応じてBANします。
    トークンがある場合は、トークンの使用回数を記録します。

    Args:
        user_id (str): ユーザーID。
        request: FastAPIのリクエストオブジェクト。
        token (str, optional): ユーザーのトークン。 Defaults to None.

    Returns:
        tuple: (bool, str): 
            - bool: ユーザーがBANされた場合 True、そうでない場合 False。
            - str: BANされた理由（BANされていない場合は空文字列）。
    """

    global blocked_users, use_token_list

    now = datetime.now()
    has_token = bool(token)

    # BAN期間が過ぎたユーザーを unblock する
    expired_users = [
        user_id
        for user_id, ban_time in blocked_users.items()
        if datetime.fromisoformat(ban_time) < now
    ]
    for user_id in expired_users:
        del blocked_users[user_id]

    # ブロックユーザー情報を保存
    save_data(BLOCKED_USERS_FILE, blocked_users)

    if user_id in blocked_users:
        return True, f"あなたはBANされています。BAN期間終了まではアクセスできません。"

    # ユーザーのリクエスト履歴を取得
    requests = user_requests[user_id]

    # 古いリクエストを削除
    limit = request_limits[has_token]
    requests = [r for r in requests if now - r <= limit.interval]
    user_requests[user_id] = requests

    # リクエストを追加
    requests.append(now)

    # リクエスト制限のチェック
    if len(requests) > limit.count:
        ban_user(user_id, ban_durations["short"])
        return True, f"短時間に大量のリクエストを検知しました。{ban_durations['short'].total_seconds() // 60}分間アクセスできません。"

    # 1日あたりのリクエスト数のチェック
    if len(requests) > max_requests_per_day[has_token]:
        ban_user(user_id, ban_durations["long"])
        return True, f"1日のリクエスト上限を超えました。{ban_durations['long'].total_seconds() // 3600}時間はアクセスできません。"

    # トークンの使用回数を記録
    if token:
        if token in use_token_list:
            use_token_list[token] += 1
        else:
            use_token_list[token] = 1

        # トークン使用回数情報を保存
        save_data(USE_TOKEN_LIST_PATH, use_token_list)

    return False, ""

def ban_user(user_id: str, duration: timedelta):
    """ユーザーをBANします。

    Args:
        user_id (str): ユーザーID。
        duration (timedelta): BAN期間。
    """
    global blocked_users, ban_history
    blocked_users[user_id] = (datetime.now() + duration).isoformat()
    ban_history.append({"user_id": user_id, "ban_time": datetime.now().isoformat(), "duration": str(duration)})
    save_data(BLOCKED_USERS_FILE, blocked_users)
    save_data(BAN_HISTORY_FILE, ban_history)

def unban_user(user_id: str):
    """ユーザーのBANを解除します。

    Args:
        user_id (str): ユーザーID。
    """
    global blocked_users, ban_history
    if user_id in blocked_users:
        del blocked_users[user_id]
        save_data(BLOCKED_USERS_FILE, blocked_users)

    ban_history = [entry for entry in ban_history if entry["user_id"] != user_id]
    save_data(BAN_HISTORY_FILE, ban_history)

    if user_id in user_requests:
        del user_requests[user_id]

def get_ban_history():
    """BAN履歴を取得します。

    Returns:
        list: BAN履歴のリスト。各エントリはユーザーID、BAN時間、残り時間を含む辞書です。
    """
    global ban_history
    now = datetime.now()
    return [{
        "user_id": entry["user_id"],
        "ban_time": entry["ban_time"],
        "remaining_time": str(datetime.fromisoformat(entry["ban_time"]) + timedelta(seconds=int(entry["duration"][:entry["duration"].find(":")])) - now)
    } for entry in ban_history if datetime.fromisoformat(entry["ban_time"]) + timedelta(seconds=int(entry["duration"][:entry["duration"].find(":")])) > now]

def get_banned_count():
    """現在のBAN人数を取得します。

    Returns:
        int: 現在のBAN人数。
    """
    global blocked_users
    return len([user_id for user_id, ban_time in blocked_users.items() if datetime.fromisoformat(ban_time) > datetime.now()])