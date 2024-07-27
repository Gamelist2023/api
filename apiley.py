import asyncio
import json
import time
import hashlib
import base64
import re
from datetime import datetime, timezone
from playwright.async_api import async_playwright

# ChatGPTのURL
CHATGPT_URL = "https://chatgpt.com/"


async def get_cloudflare_turnstile_token(page):
    """
    Playwrightを使ってCloudflare Turnstileを解き、トークンを取得する。
    """
    print("Cloudflare Turnstileチャレンジを解決中...")
    try:
        # Turnstileのiframeを待つ
        frame = page.frame_locator("iframe[title='widget containing checkbox for hCaptcha security challenge']")
        await frame.locator("input[type='checkbox']").wait_for(timeout=30000)

        # チェックボックスをクリックしてチャレンジを完了させる
        await frame.locator("input[type='checkbox']").click()

        # トークンを取得するまで待つ
        token = await page.evaluate(
            "() => {"
            "return new Promise((resolve) => {"
            "const intervalId = setInterval(() => {"
            "const iframe = document.querySelector('iframe[title=\"widget containing checkbox for hCaptcha security challenge\"]');"
            "if (iframe && iframe.contentDocument.querySelector('.challenge-container')) {"
            "clearInterval(intervalId);"
            "resolve(null);"  # 成功した場合は resolve(null)
            "}"
            "const token = window.__cf_chl_opt && window.__cf_chl_opt.c;"
            "if (token) {"
            "clearInterval(intervalId);"
            "resolve(token);"  # トークンを取得できた場合はresolve(token)
            "}"
            "}, 100);"
            "});"
        )
        print("Cloudflare Turnstileトークンを取得しました:", token)
        return token
    except Exception as e:
        print(f"Cloudflare Turnstileトークンの取得に失敗しました: {e}")
        return None


async def solve_proof_of_work(page, data):
    """
    Proof of Workを解決する。
    """
    print("Proof of Workを解決中...")
    try:
        # PoWパラメータを取得
        required = data.get("proofofwork", {}).get("required", False)
        if not required:
            return None
        seed = data.get("proofofwork", {}).get("seed", "")
        difficulty = data.get("proofofwork", {}).get("difficulty", "")

        # PoWトークンを生成
        user_agent = await page.evaluate("() => navigator.userAgent")
        token = generate_proof_token(required, seed, difficulty, user_agent, proofTokens=None) 

        print("Proof of Workトークンを生成しました:", token)
        return token
    except Exception as e:
        print(f"Proof of Workの解決に失敗しました: {e}")
        return None


async def main():
    async with async_playwright() as p:
        # プロキシ設定があれば追加 (例: --proxy-server=http://localhost:8080)
        browser = await p.chromium.launch(headless=False) 
        page = await browser.new_page()
        
        # ChatGPTにアクセス
        await page.goto(CHATGPT_URL)
        await page.wait_for_load_state("domcontentloaded")

        # 認証情報を取得
        access_token = await page.evaluate(
            "(async () => {"
            "let session = await fetch('/api/auth/session');"
            "let data = await session.json();"
            "let accessToken = data['accessToken'];"
            "let expires = new Date(); expires.setTime(expires.getTime() + 60 * 60 * 4 * 1000);"
            "document.cookie = 'access_token=' + accessToken + ';expires=' + expires.toUTCString() + ';path=/';"
            "return accessToken;"
            "})();",
            await_promise=True
        )

        cookies = await page.context.cookies()  # クッキーを取得
        headers = await page.evaluate("() => Object.fromEntries(Object.entries(this.headers).filter(([key]) => !key.startsWith(':')))")  # :で始まるものを除く

        print("accessToken:", access_token)
        print("Cookies:", cookies)
        print("Headers:", headers)
        print(headers)

        # chat-requirementsリクエスト
        while True:
            try:
                response = await page.request.post(
                    "https://chatgpt.com/backend-api/sentinel/chat-requirements",
                    data=json.dumps({"p": generate_proof_token(True, user_agent=headers.get("user-agent"))}),
                    headers=headers
                )
                data = await response.json()
                print("Chat requirements:", data)

                # Cloudflare Turnstile
                if data.get("turnstile", {}).get("required", False):
                    turnstile_token = await get_cloudflare_turnstile_token(page)
                    # トークン取得に失敗した場合はループを続ける
                    if turnstile_token is None:
                        print("Turnstileトークン取得を再試行...")
                        continue  # 再度chat-requirementsから
                    else:
                        headers["openai-sentinel-turnstile-token"] = turnstile_token  

                # Proof of Work
                proof_token = await solve_proof_of_work(page, data)
                headers["Openai-Sentinel-Proof-Token"] = proof_token
                chat_token = data["token"]
                headers["Openai-Sentinel-Chat-Requirements-Token"] = chat_token

                break  # すべてのトークンが取得できたのでループを抜ける

            except Exception as e:
                print("認証情報の取得中にエラーが発生しました。:", e)
                await asyncio.sleep(5) 

        await browser.close()

asyncio.run(main())