import time
from datetime import datetime, timedelta

# ユーザーのブロック状態を管理する辞書
blocked_users = {}

# リクエスト間隔（秒）
request_interval = 1

# ユーザーIDと最後のリクエスト時間のマッピング
last_request = {}

# ユーザーIDとリクエストカウントのマッピング
request_count = {}

# 1秒あたりの最大リクエスト数
max_requests_per_second = 8

# 1日あたりの最大リクエスト数
max_requests_per_day = 300

# BANの持続時間（時間）
ban_duration = timedelta(hours=3)

# BANの持続時間（時間）
short_ban_duration = timedelta(minutes=5) 
long_ban_duration = timedelta(hours=24)  

# BAN履歴を保持するリスト
ban_history = []

def check_and_ban(user_id: str, request, token: str = None):
    """ユーザーがボットかどうかチェックし、必要に応じてBANします。

    Args:
        user_id (str): ユーザーID。
        request: FastAPIのリクエストオブジェクト。
        token (str, optional): ユーザーのトークン。 Defaults to None.

    Returns:
        tuple: (bool, str): 
            - True: ユーザーがBANされた場合。
            - False: ユーザーがBANされなかった場合。
            - str: BANされた場合の理由。
    """

    # 最後のリクエスト時間を更新
    last_request[user_id] = datetime.now()

    # リクエストカウントを更新
    if user_id in request_count:
        request_count[user_id] += 1
    else:
        request_count[user_id] = 1

    # 1秒あたりのリクエスト数が最大値を超えた場合、またはBANされている場合
    if (datetime.now() - last_request[user_id] < timedelta(seconds=request_interval) and
        request_count[user_id] > max_requests_per_second) or (
        user_id in blocked_users and datetime.now() < blocked_users[user_id]):
        # 短期間のBAN
        blocked_users[user_id] = datetime.now() + short_ban_duration  # BAN時間を変更
        reason = f"短時間に大量のリクエストを検知しました。{short_ban_duration.total_seconds() // 60}分間アクセスできません。" 
        ban_user(user_id)
        return True, reason
    # トークンの有無でリクエスト制限を変更
    if token:
        max_requests_per_day = 1000  # トークンありの場合のリクエスト制限
    else:
        max_requests_per_day = 2  # トークンなしの場合のリクエスト制限


    # 1日あたりのリクエスト数が最大値を超えた場合
    if request_count[user_id] > max_requests_per_day:
        # 長期間のBAN
        blocked_users[user_id] = datetime.now() + long_ban_duration  # BAN時間を変更
        reason = f"1日のリクエスト上限を超えました。{long_ban_duration.total_seconds() // 3600}時間はアクセスできません。"
        ban_user(user_id)
        return True, reason

    return False, ""


def ban_user(user_id: str):
    """ユーザーをBANします。

    Args:
        user_id (str): ユーザーID。
    """
    blocked_users[user_id] = datetime.now() + ban_duration
    ban_history.append({"user_id": user_id, "ban_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

def unban_user(user_id: str):
    """ユーザーのBANを解除します。

    Args:
        user_id (str): ユーザーID。
    """
    if user_id in blocked_users:
        del blocked_users[user_id]

    # ban_history から user_id に対応する履歴を削除
    global ban_history
    ban_history = [entry for entry in ban_history if entry["user_id"] != user_id] 

    # リクエストカウントを初期化
    if user_id in request_count:
        del request_count[user_id]

def get_ban_history():
    """BAN履歴を取得します。

    Returns:
        list: BAN履歴のリスト。各エントリはユーザーID、BAN時間、残り時間を含む辞書です。
    """

    # user_id をキーとした辞書を作成して重複を排除
    unique_bans = {}
    for user_id, ban_time in blocked_users.items():
        unique_bans[user_id] = ban_time  # 同じ user_id があれば、最後の ban_time で上書き

    ban_history = []
    for user_id, ban_time in unique_bans.items():
        remaining_time = ban_time - datetime.now()
        ban_history.append({
            "user_id": user_id,
            "ban_time": ban_time.strftime("%Y-%m-%d %H:%M:%S"),
            "remaining_time": str(remaining_time)
        })
    return ban_history

def get_banned_count():
    """現在のBAN人数を取得します。

    Returns:
        int: 現在のBAN人数。
    """
    return len(blocked_users)
