from __future__ import annotations

import os
import json
import random
import re
import base64

from aiohttp import ClientSession, BaseConnector

try:
    import nodriver
    has_nodriver = True
except ImportError:
    has_nodriver = False

from ... import debug
from ...typing import Messages, Cookies, ImageType, AsyncResult, AsyncIterator
from ..base_provider import AsyncGeneratorProvider, BaseConversation, SynthesizeData
from ..helper import format_prompt, get_cookies
from ...requests.raise_for_status import raise_for_status
from ...requests.aiohttp import get_connector
from ...requests import get_nodriver
from ...errors import MissingAuthError
from ...image import ImageResponse, to_bytes
from ... import debug

REQUEST_HEADERS = {
    "authority": "gemini.google.com",
    "origin": "https://gemini.google.com",
    "referer": "https://gemini.google.com/",
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36',
    'x-same-domain': '1',
}
REQUEST_BL_PARAM = "boq_assistant-bard-web-server_20240519.16_p0"
REQUEST_URL = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
UPLOAD_IMAGE_URL = "https://content-push.googleapis.com/upload/"
UPLOAD_IMAGE_HEADERS = {
    "authority": "content-push.googleapis.com",
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.7",
    "authorization": "Basic c2F2ZXM6cyNMdGhlNmxzd2F2b0RsN3J1d1U=",
    "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    "origin": "https://gemini.google.com",
    "push-id": "feeds/mcudyrk2a4khkz",
    "referer": "https://gemini.google.com/",
    "x-goog-upload-command": "start",
    "x-goog-upload-header-content-length": "",
    "x-goog-upload-protocol": "resumable",
    "x-tenant-id": "bard-storage",
}

class Gemini(AsyncGeneratorProvider):
    url = "https://gemini.google.com"
    needs_auth = True
    working = True
    default_model = 'gemini'
    image_models = ["gemini"]
    default_vision_model = "gemini"
    models = ["gemini", "gemini-1.5-flash", "gemini-1.5-pro"]
    synthesize_content_type = "audio/vnd.wav"
    _cookies: Cookies = None
    _snlm0e: str = None
    _sid: str = None

    @classmethod
    async def nodriver_login(cls, proxy: str = None) -> AsyncIterator[str]:
        if not has_nodriver:
            if debug.logging:
                print("Skip nodriver login in Gemini provider")
            return
        browser = await get_nodriver(proxy=proxy)
        login_url = os.environ.get("G4F_LOGIN_URL")
        if login_url:
            yield f"Please login: [Google Gemini]({login_url})\n\n"
        page = await browser.get(f"{cls.url}/app")
        await page.select("div.ql-editor.textarea", 240)
        cookies = {}
        for c in await page.browser.cookies.get_all():
            if c.domain.endswith(".google.com"):
                cookies[c.name] = c.value
        await page.close()
        cls._cookies = cookies

    @classmethod
    async def create_async_generator(
        cls,
        model: str,
        messages: Messages,
        proxy: str = None,
        cookies: Cookies = None,
        connector: BaseConnector = None,
        image: ImageType = None,
        image_name: str = None,
        response_format: str = None,
        return_conversation: bool = False,
        conversation: Conversation = None,
        language: str = "en",
        **kwargs
    ) -> AsyncResult:
        prompt = format_prompt(messages) if conversation is None else messages[-1]["content"]
        cls._cookies = cookies or cls._cookies or get_cookies(".google.com", False, True)
        base_connector = get_connector(connector, proxy)

        async with ClientSession(
            headers=REQUEST_HEADERS,
            connector=base_connector
        ) as session:
            if not cls._snlm0e:
                await cls.fetch_snlm0e(session, cls._cookies) if cls._cookies else None
            if not cls._snlm0e:
                try:
                    async for chunk in cls.nodriver_login(proxy):
                        yield chunk
                except Exception as e:
                    raise MissingAuthError('Missing "__Secure-1PSID" cookie', e)
            if not cls._snlm0e:
                if cls._cookies is None or "__Secure-1PSID" not in cls._cookies:
                    raise MissingAuthError('Missing "__Secure-1PSID" cookie')
                await cls.fetch_snlm0e(session, cls._cookies)
            if not cls._snlm0e:
                raise RuntimeError("Invalid cookies. SNlM0e not found")

            yield SynthesizeData(cls.__name__, {"text": messages[-1]["content"]})
            image_url = await cls.upload_image(base_connector, to_bytes(image), image_name) if image else None

            async with ClientSession(
                cookies=cls._cookies,
                headers=REQUEST_HEADERS,
                connector=base_connector,
            ) as client:
                params = {
                    'bl': REQUEST_BL_PARAM,
                    'hl': language,
                    '_reqid': random.randint(1111, 9999),
                    'rt': 'c',
                    "f.sid": cls._sid,
                }
                data = {
                    'at': cls._snlm0e,
                    'f.req': json.dumps([None, json.dumps(cls.build_request(
                        prompt,
                        language=language,
                        conversation=conversation,
                        image_url=image_url,
                        image_name=image_name
                    ))])
                }
                async with client.post(
                    REQUEST_URL,
                    data=data,
                    params=params,
                ) as response:
                    await raise_for_status(response)
                    image_prompt = response_part = None
                    last_content_len = 0
                    async for line in response.content:
                        try:
                            try:
                                line = json.loads(line)
                            except ValueError:
                                continue
                            if not isinstance(line, list):
                                continue
                            if len(line[0]) < 3 or not line[0][2]:
                                continue
                            response_part = json.loads(line[0][2])
                            if not response_part[4]:
                                continue
                            if return_conversation:
                                yield Conversation(response_part[1][0], response_part[1][1], response_part[4][0][0])
                            content = response_part[4][0][1][0]
                        except (ValueError, KeyError, TypeError, IndexError) as e:
                            print(f"{cls.__name__}:{e.__class__.__name__}:{e}")
                            continue
                        match = re.search(r'\[Imagen of (.*?)\]', content)
                        if match:
                            image_prompt = match.group(1)
                            content = content.replace(match.group(0), '')
                        yield content[last_content_len:]
                        last_content_len = len(content)
                    if image_prompt:
                        try:
                            images = [image[0][3][3] for image in response_part[4][0][12][7][0]]
                            if response_format == "b64_json":
                                yield ImageResponse(images, image_prompt, {"cookies": cls._cookies})
                            else:
                                resolved_images = []
                                preview = []
                                for image in images:
                                    async with client.get(image, allow_redirects=False) as fetch:
                                        image = fetch.headers["location"]
                                    async with client.get(image, allow_redirects=False) as fetch:
                                        image = fetch.headers["location"]
                                    resolved_images.append(image)
                                    preview.append(image.replace('=s512', '=s200'))
                                yield ImageResponse(resolved_images, image_prompt, {"orginal_links": images, "preview": preview})
                        except TypeError:
                            pass

    @classmethod
    async def synthesize(cls, params: dict, proxy: str = None) -> AsyncIterator[bytes]:
        if "text" not in params:
            raise ValueError("Missing parameter text")
        async with ClientSession(
            cookies=cls._cookies,
            headers=REQUEST_HEADERS,
            connector=get_connector(proxy=proxy),
        ) as session:
            if not cls._snlm0e:
                await cls.fetch_snlm0e(session, cls._cookies) if cls._cookies else None
            inner_data = json.dumps([None, params["text"], "de-DE", None, 2])
            async with session.post(
                "https://gemini.google.com/_/BardChatUi/data/batchexecute",
                data={
                      "f.req": json.dumps([[["XqA3Ic", inner_data, None, "generic"]]]),
                      "at": cls._snlm0e,
                },
                params={
                    "rpcids": "XqA3Ic",
                    "source-path": "/app/2704fb4aafcca926",
                    "bl": "boq_assistant-bard-web-server_20241119.00_p1",
                    "f.sid": "" if cls._sid is None else cls._sid,
                    "hl": "de",
                    "_reqid": random.randint(1111, 9999),
                    "rt": "c"
                },
            ) as response:
                await raise_for_status(response)
                iter_base64_response = iter_filter_base64(response.content.iter_chunked(1024))
                async for chunk in iter_base64_decode(iter_base64_response):
                    yield chunk

    def build_request(
        prompt: str,
        language: str,
        conversation: Conversation = None,
        image_url: str = None,
        image_name: str = None,
        tools: list[list[str]] = []
    ) -> list:
        image_list = [[[image_url, 1], image_name]] if image_url else []
        return [
            [prompt, 0, None, image_list, None, None, 0],
            [language],
            [
                None if conversation is None else conversation.conversation_id,
                None if conversation is None else conversation.response_id,
                None if conversation is None else conversation.choice_id,
                None,
                None,
                []
            ],
            None,
            None,
            None,
            [1],
            0,
            [],
            tools,
            1,
            0,
        ]

    async def upload_image(connector: BaseConnector, image: bytes, image_name: str = None):
        async with ClientSession(
            headers=UPLOAD_IMAGE_HEADERS,
            connector=connector
        ) as session:
            async with session.options(UPLOAD_IMAGE_URL) as response:
                await raise_for_status(response)

            headers = {
                "size": str(len(image)),
                "x-goog-upload-command": "start"
            }
            data = f"File name: {image_name}" if image_name else None
            async with session.post(
                UPLOAD_IMAGE_URL, headers=headers, data=data
            ) as response:
                await raise_for_status(response)
                upload_url = response.headers["X-Goog-Upload-Url"]

            async with session.options(upload_url, headers=headers) as response:
                await raise_for_status(response)

            headers["x-goog-upload-command"] = "upload, finalize"
            headers["X-Goog-Upload-Offset"] = "0"
            async with session.post(
                upload_url, headers=headers, data=image
            ) as response:
                await raise_for_status(response)
                return await response.text()

    @classmethod
    async def fetch_snlm0e(cls, session: ClientSession, cookies: Cookies):
        async with session.get(cls.url, cookies=cookies) as response:
            await raise_for_status(response)
            response_text = await response.text()
        match = re.search(r'SNlM0e\":\"(.*?)\"', response_text)
        if match:
            cls._snlm0e = match.group(1)
        sid_match = re.search(r'"FdrFJe":"([\d-]+)"', response_text)
        if sid_match:
            cls._sid = sid_match.group(1)

class Conversation(BaseConversation):
    def __init__(self,
        conversation_id: str = "",
        response_id: str = "",
        choice_id: str = ""
    ) -> None:
        self.conversation_id = conversation_id
        self.response_id = response_id
        self.choice_id = choice_id

async def iter_filter_base64(response_iter: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    search_for = b'[["wrb.fr","XqA3Ic","[\\"'
    end_with = b'\\'
    is_started = False
    async for chunk in response_iter:
        if is_started:
            if end_with in chunk:
                yield chunk.split(end_with, 1).pop(0)
                break
            else:
                yield chunk
        elif search_for in chunk:
            is_started = True
            yield chunk.split(search_for, 1).pop()
        else:
            raise RuntimeError(f"Response: {chunk}")

async def iter_base64_decode(response_iter: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    buffer = b""
    async for chunk in response_iter:
        chunk = buffer + chunk
        rest = len(chunk) % 4
        buffer = chunk[-rest:]
        yield base64.b64decode(chunk[:-rest])