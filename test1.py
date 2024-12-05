from passlib.context import CryptContext

# パスワードコンテキストの設定
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ハッシュ化するパスワードの設定
password = "a"  # ここに検証するパスワードを入力
hashed_password = pwd_context.hash(password)
print(f"hashed password: {hashed_password}")

# ハッシュと入力されたパスワードを照合する関数
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# パスワードの照合
is_valid = verify_password("", hashed_password)
print(f"Password is valid: {is_valid}")
