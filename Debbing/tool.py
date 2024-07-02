import asyncio
import json
import base64
import time
import uuid
import requests

from g4f.Provider.openai.har_file import NoValidHarFileError, getArkoseAndAccessToken
from g4f.Provider.openai.proofofwork import generate_proof_token


class OpenAIChat:
    """
    A standalone class for interacting with OpenAI's ChatGPT using requests library.
    """

    url = "https://chatgpt.com"
    needs_auth = True

    def __init__(self, model: str = "gpt-3.5-turbo", proxy: str = None, timeout: int = 180):
        self.model = model
        self.proxy = proxy
        self.timeout = timeout
        self._api_key = None
        self._headers = None
        self._cookies = None
        self._expires = None
        self.conversation_id = None
        self.parent_id = str(uuid.uuid4())

    def _get_chat_requirements(self, session: requests.Session, proofTokens: list):
        """Retrieves the requirements for initiating a chat session."""
        with session.post(
            f"{self.url}/backend-api/sentinel/chat-requirements",
            json={"p": generate_proof_token(True, user_agent=self._headers["user-agent"], proofTokens=proofTokens)},
            headers=self._headers,
            proxies={"https": self.proxy} if self.proxy else None
        ) as response:
            self._update_request_args(session)
            response.raise_for_status()
            requirements = response.json()
            return requirements.get("arkose", {}).get("required"), requirements["token"]

    def _send_message(
        self,
        session: requests.Session,
        message: str,
        chat_token: str,
        arkose_token: str = None,
        proofofwork: str = None
    ):
        """Sends a message to the chat endpoint and returns the full response."""
        websocket_request_id = str(uuid.uuid4())
        data = {
            "action": "next" if self.conversation_id is None else "continue",
            "conversation_mode": {"kind": "primary_assistant"},
            "force_paragen": False,
            "force_rate_limit": False,
            "conversation_id": self.conversation_id,
            "parent_message_id": self.parent_id,
            "model": self.model,
            "history_and_training_disabled": False,
            "websocket_request_id": websocket_request_id,
            "messages": self._create_messages([{"role": "user", "content": message}])
        }
        headers = {
            "accept": "text/event-stream",
            "Openai-Sentinel-Chat-Requirements-Token": chat_token,
            **self._headers
        }
        if arkose_token:
            headers["Openai-Sentinel-Arkose-Token"] = arkose_token
        if proofofwork:
            headers["Openai-Sentinel-Proof-Token"] = proofofwork
        with session.post(
            f"{self.url}/backend-api/conversation",
            json=data,
            headers=headers,
            proxies={"https": self.proxy} if self.proxy else None,
            stream=True  # データをチャンクごとに受信
        ) as response:
            self._update_request_args(session)
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith("data: "):
                        json_data = json.loads(decoded_line[5:])
                        self.parent_id = json_data["message"]["id"]
                        if self.conversation_id is None:
                            self.conversation_id = json_data["conversation_id"]
                        message = base64.b64decode(json_data["message"]["content"]["parts"][0]).decode('utf-8')
                        return message

    def ask(self, message: str) -> str:
        """
        Asks a question to ChatGPT and returns the response as a single string.
        """
        arkose_token = None
        proofTokens = None
        if self._expires is not None and self._expires < time.time():
            self._headers = self._api_key = None
        try:
            arkose_token, api_key, cookies, headers, proofTokens = getArkoseAndAccessToken(self.proxy)
            self._create_request_args(cookies, headers)
            self._set_api_key(api_key)
        except NoValidHarFileError as e:
            raise e
        with requests.Session() as session:
            need_arkose, chat_token = self._get_chat_requirements(session, proofTokens)
            if need_arkose and arkose_token is None:
                raise RuntimeError("Arkose token required but not provided.")
            response = self._send_message(session, message, chat_token, arkose_token)
            return response

    def _create_messages(self, messages: list[dict]):
        """Formats messages for the chat endpoint."""
        return [{
            "id": str(uuid.uuid4()),
            "author": {"role": message["role"]},
            "content": {"content_type": "text", "parts": [message["content"]]},
        } for message in messages]

    @staticmethod
    def get_default_headers() -> dict:
        """Returns default headers for requests."""
        return {
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "ja,en;q=0.9,en-GB;q=0.8,en-US;q=0.7",
            "referer": "https://chatgpt.com/",
            "sec-ch-ua": "\"Not/A)Brand\";v=\"8\", \"Chromium\";v=\"126\", \"Microsoft Edge\";v=\"126\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"Windows\"",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "sec-gpc": "1",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
        }

    def _create_request_args(self, cookies: dict = None, headers: dict = None, user_agent: str = None):
        """Sets up request headers and cookies."""
        self._headers = self.get_default_headers() if headers is None else headers
        if user_agent is not None:
            self._headers["user-agent"] = user_agent
        self._cookies = {} if cookies is None else {k: v for k, v in cookies.items() if k != "access_token"}
        self._update_cookie_header()

    def _update_request_args(self, session: requests.Session):
        """Updates request cookies from the session."""
        if session.cookies:
            self._cookies.update(dict(session.cookies))
        self._update_cookie_header()

    def _set_api_key(self, api_key: str):
        """Sets the API key for authentication."""
        self._api_key = api_key
        self._expires = int(time.time()) + 60 * 60 * 4
        self._headers["authorization"] = f"Bearer {api_key}"

    def _update_cookie_header(self):
        """Formats and updates the cookie header."""
        cookie_string = "; ".join([f"{name}={value}" for name, value in self._cookies.items()])
        self._headers["cookie"] = cookie_string
        if "oai-did" in self._cookies:
            self._headers["oai-device-id"] = self._cookies["oai-did"]


async def main():
    """
    Starts an interactive chat session.
    """
    chat = OpenAIChat()
    while True:
        message = input("You: ")
        if message.lower() in ("quit", "exit"):
            break
        response = chat.ask(message)
        print("ChatGPT:", response)


if __name__ == "__main__":
    asyncio.run(main())