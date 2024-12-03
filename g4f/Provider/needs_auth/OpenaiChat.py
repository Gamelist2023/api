from __future__ import annotations

import re
import asyncio
import uuid
import json
import base64
import time
import requests
from copy import copy

try:
    import nodriver
    from nodriver.cdp.network import get_response_body
    has_nodriver = True
except ImportError:
    has_nodriver = False

from ..base_provider import AsyncGeneratorProvider, ProviderModelMixin
from ...typing import AsyncResult, Messages, Cookies, ImageType, AsyncIterator
from ...requests.raise_for_status import raise_for_status
from ...requests import StreamSession
from ...requests import get_nodriver
from ...image import ImageResponse, ImageRequest, to_image, to_bytes, is_accepted_format
from ...errors import MissingAuthError, NoValidHarFileError
from ...providers.response import BaseConversation, FinishReason, SynthesizeData
from ..helper import format_cookies
from ..openai.har_file import get_request_config
from ..openai.har_file import RequestConfig, arkReq, arkose_url, start_url, conversation_url, backend_url, backend_anon_url
from ..openai.proofofwork import generate_proof_token
from ..openai.new import get_requirements_token
from ... import debug

DEFAULT_HEADERS = {
    "accept": "*/*",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-US,en;q=0.5",
    "referer": "https://chatgpt.com/",
    "sec-ch-ua": "\"Brave\";v=\"123\", \"Not:A-Brand\";v=\"8\", \"Chromium\";v=\"123\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "sec-gpc": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
}

class OpenaiChat(AsyncGeneratorProvider, ProviderModelMixin):
    """A class for creating and managing conversations with OpenAI chat service"""

    label = "OpenAI ChatGPT"
    url = "https://chatgpt.com"
    working = True
    needs_auth = True
    supports_gpt_4 = True
    supports_message_history = True
    supports_system_message = True
    default_model = "auto"
    default_vision_model = "gpt-4o"
    default_image_model = "dall-e-3"
    fallback_models = [default_model, "gpt-4", "gpt-4o", "gpt-4o-mini", "gpt-4o-canmore", "o1-preview", "o1-mini", default_image_model]
    vision_models = fallback_models
    image_models = fallback_models
    synthesize_content_type = "audio/mpeg"

    _api_key: str = None
    _headers: dict = None
    _cookies: Cookies = None
    _expires: int = None

    @classmethod
    def get_models(cls):
        if not cls.models:
            try:
                response = requests.get(f"{cls.url}/backend-anon/models")
                response.raise_for_status()
                data = response.json()
                cls.models = [model.get("slug") for model in data.get("models")]
                cls.models.append(cls.default_image_model)
            except Exception:
                cls.models = cls.fallback_models
        return cls.models

    @classmethod
    async def upload_image(
        cls,
        session: StreamSession,
        headers: dict,
        image: ImageType,
        image_name: str = None
    ) -> ImageRequest:
        """
        Upload an image to the service and get the download URL
        
        Args:
            session: The StreamSession object to use for requests
            headers: The headers to include in the requests
            image: The image to upload, either a PIL Image object or a bytes object
        
        Returns:
            An ImageRequest object that contains the download URL, file name, and other data
        """
        # Convert the image to a PIL Image object and get the extension
        data_bytes = to_bytes(image)
        image = to_image(data_bytes)
        extension = image.format.lower()
        data = {
            "file_name": "" if image_name is None else image_name,
            "file_size": len(data_bytes),
            "use_case":	"multimodal"
        }
        # Post the image data to the service and get the image data
        async with session.post(f"{cls.url}/backend-api/files", json=data, headers=headers) as response:
            cls._update_request_args(session)
            await raise_for_status(response, "Create file failed")
            image_data = {
                **data,
                **await response.json(),
                "mime_type": is_accepted_format(data_bytes),
                "extension": extension,
                "height": image.height,
                "width": image.width
            }
        # Put the image bytes to the upload URL and check the status
        async with session.put(
            image_data["upload_url"],
            data=data_bytes,
            headers={
                "Content-Type": image_data["mime_type"],
                "x-ms-blob-type": "BlockBlob",
                "x-ms-version": "2020-04-08",
                "Origin": "https://chatgpt.com",
                "Referer": "https://chatgpt.com/",
            }
        ) as response:
            await raise_for_status(response)
        # Post the file ID to the service and get the download URL
        async with session.post(
            f"{cls.url}/backend-api/files/{image_data['file_id']}/uploaded",
            json={},
            headers=headers
        ) as response:
            cls._update_request_args(session)
            await raise_for_status(response, "Get download url failed")
            image_data["download_url"] = (await response.json())["download_url"]
        return ImageRequest(image_data)

    @classmethod
    def create_messages(cls, messages: Messages, image_request: ImageRequest = None, system_hints: list = None):
        """
        Create a list of messages for the user input
        
        Args:
            prompt: The user input as a string
            image_response: The image response object, if any
        
        Returns:
            A list of messages with the user input and the image, if any
        """
        # Create a message object with the user role and the content
        messages = [{
            "author": {"role": message["role"]},
            "content": {"content_type": "text", "parts": [message["content"]]},
            "id": str(uuid.uuid4()),
            "create_time": int(time.time()),
            "id": str(uuid.uuid4()),
            "metadata": {"serialization_metadata": {"custom_symbol_offsets": []}, "system_hints": system_hints},
        } for message in messages]

        # Check if there is an image response
        if image_request is not None:
            # Change content in last user message
            messages[-1]["content"] = {
                "content_type": "multimodal_text",
                "parts": [{
                    "asset_pointer": f"file-service://{image_request.get('file_id')}",
                    "height": image_request.get("height"),
                    "size_bytes": image_request.get("file_size"),
                    "width": image_request.get("width"),
                }, messages[-1]["content"]["parts"][0]]
            }
            # Add the metadata object with the attachments
            messages[-1]["metadata"] = {
                "attachments": [{
                    "height": image_request.get("height"),
                    "id": image_request.get("file_id"),
                    "mimeType": image_request.get("mime_type"),
                    "name": image_request.get("file_name"),
                    "size": image_request.get("file_size"),
                    "width": image_request.get("width"),
                }]
            }
        return messages

    @classmethod
    async def get_generated_image(cls, session: StreamSession, headers: dict, element: dict, prompt: str = None) -> ImageResponse:
        """
        Retrieves the image response based on the message content.

        This method processes the message content to extract image information and retrieves the 
        corresponding image from the backend API. It then returns an ImageResponse object containing 
        the image URL and the prompt used to generate the image.

        Args:
            session (StreamSession): The StreamSession object used for making HTTP requests.
            headers (dict): HTTP headers to be used for the request.
            line (dict): A dictionary representing the line of response that contains image information.

        Returns:
            ImageResponse: An object containing the image URL and the prompt, or None if no image is found.

        Raises:
            RuntimeError: If there'san error in downloading the image, including issues with the HTTP request or response.
        """
        try:
            prompt = element["metadata"]["dalle"]["prompt"]
            file_id = element["asset_pointer"].split("file-service://", 1)[1]
        except TypeError:
            return
        except Exception as e:
            raise RuntimeError(f"No Image: {e.__class__.__name__}: {e}")
        try:
            async with session.get(f"{cls.url}/backend-api/files/{file_id}/download", headers=headers) as response:
                cls._update_request_args(session)
                await raise_for_status(response)
                download_url = (await response.json())["download_url"]
                return ImageResponse(download_url, prompt)
        except Exception as e:
            raise RuntimeError(f"Error in downloading image: {e}")

    @classmethod
    async def create_async_generator(
        cls,
        model: str,
        messages: Messages,
        proxy: str = None,
        timeout: int = 180,
        cookies: Cookies = None,
        auto_continue: bool = False,
        history_disabled: bool = False,
        action: str = "next",
        conversation_id: str = None,
        conversation: Conversation = None,
        parent_id: str = None,
        image: ImageType = None,
        image_name: str = None,
        return_conversation: bool = False,
        max_retries: int = 3,
        web_search: bool = False,
        **kwargs
    ) -> AsyncResult:
        """
        Create an asynchronous generator for the conversation.

        Args:
            model (str): The model name.
            messages (Messages): The list of previous messages.
            proxy (str): Proxy to use for requests.
            timeout (int): Timeout for requests.
            api_key (str): Access token for authentication.
            cookies (dict): Cookies to use for authentication.
            auto_continue (bool): Flag to automatically continue the conversation.
            history_disabled (bool): Flag to disable history and training.
            action (str): Type of action ('next', 'continue', 'variant').
            conversation_id (str): ID of the conversation.
            parent_id (str): ID of the parent message.
            image (ImageType): Image to include in the conversation.
            return_conversation (bool): Flag to include response fields in the output.
            **kwargs: Additional keyword arguments.

        Yields:
            AsyncResult: Asynchronous results from the generator.

        Raises:
            RuntimeError: If an error occurs during processing.
        """
        if model == cls.default_image_model:
            model = cls.default_model
        await cls.login(proxy)

        async with StreamSession(
            proxy=proxy,
            impersonate="chrome",
            timeout=timeout
        ) as session:
            try:
                image_request = await cls.upload_image(session, cls._headers, image, image_name) if image else None
            except Exception as e:
                image_request = None
                debug.log("OpenaiChat: Upload image failed")
                debug.log(f"{e.__class__.__name__}: {e}")
            model = cls.get_model(model)
            if conversation is None:
                conversation = Conversation(conversation_id, str(uuid.uuid4()) if parent_id is None else parent_id)
            else:
                conversation = copy(conversation)
            if cls._api_key is None:
                auto_continue = False
            conversation.finish_reason = None
            while conversation.finish_reason is None:
                async with session.post(
                    f"{cls.url}/backend-anon/sentinel/chat-requirements"
                    if cls._api_key is None else
                    f"{cls.url}/backend-api/sentinel/chat-requirements",
                    json={"p": get_requirements_token(RequestConfig.proof_token) if RequestConfig.proof_token else None},
                    headers=cls._headers
                ) as response:
                    cls._update_request_args(session)
                    await raise_for_status(response)
                    chat_requirements = await response.json()
                    need_turnstile = chat_requirements.get("turnstile", {}).get("required", False)
                    need_arkose = chat_requirements.get("arkose", {}).get("required", False) 
                    chat_token = chat_requirements.get("token")  

                if need_arkose and RequestConfig.arkose_token is None:
                    await get_request_config(proxy)
                    cls._create_request_args(RequestConfig,cookies, RequestConfig.headers)
                    cls._set_api_key(RequestConfig.access_token)
                    if RequestConfig.arkose_token is None:
                        raise MissingAuthError("No arkose token found in .har file")

                if "proofofwork" in chat_requirements:
                    proofofwork = generate_proof_token(
                        **chat_requirements["proofofwork"],
                        user_agent=cls._headers.get("user-agent"),
                        proof_token=RequestConfig.proof_token
                    )
                [debug.log(text) for text in (
                    f"Arkose: {'False' if not need_arkose else RequestConfig.arkose_token[:12]+'...'}",
                    f"Proofofwork: {'False' if proofofwork is None else proofofwork[:12]+'...'}",
                    f"AccessToken: {'False' if cls._api_key is None else cls._api_key[:12]+'...'}",
                )]
                data = {
                    "action": action,
                    "messages": None,
                    "parent_message_id": conversation.message_id,
                    "model": model,
                    "paragen_cot_summary_display_override": "allow",
                    "history_and_training_disabled": history_disabled and not auto_continue and not return_conversation,
                    "conversation_mode": {"kind":"primary_assistant"},
                    "websocket_request_id": str(uuid.uuid4()),
                    "supported_encodings": ["v1"],
                    "supports_buffering": True,
                    "system_hints": ["search"] if web_search else None
                }
                if conversation.conversation_id is not None:
                    data["conversation_id"] = conversation.conversation_id
                    debug.log(f"OpenaiChat: Use conversation: {conversation.conversation_id}")
                if action != "continue":
                    messages = messages if conversation_id is None else [messages[-1]]
                    data["messages"] = cls.create_messages(messages, image_request, ["search"] if web_search else None)
                headers = {
                    **cls._headers,
                    "accept": "text/event-stream",
                    "content-type": "application/json",
                    "openai-sentinel-chat-requirements-token": chat_token,
                }
                if RequestConfig.arkose_token:
                    headers["openai-sentinel-arkose-token"] = RequestConfig.arkose_token
                if proofofwork is not None:
                    headers["openai-sentinel-proof-token"] = proofofwork
                if need_turnstile and RequestConfig.turnstile_token is not None:
                    headers['openai-sentinel-turnstile-token'] = RequestConfig.turnstile_token
                async with session.post(
                    f"{cls.url}/backend-anon/conversation"
                    if cls._api_key is None else
                    f"{cls.url}/backend-api/conversation",
                    json=data,
                    headers=headers
                ) as response:
                    cls._update_request_args(session)
                    if response.status == 403 and max_retries > 0:
                        max_retries -= 1
                        debug.log(f"Retry: Error {response.status}: {await response.text()}")
                        await asyncio.sleep(5)
                        continue
                    await raise_for_status(response)
                    if return_conversation:
                        yield conversation
                    async for line in response.iter_lines():
                        async for chunk in cls.iter_messages_line(session, line, conversation):
                            yield chunk
                if not history_disabled:
                    yield SynthesizeData(cls.__name__, {
                        "conversation_id": conversation.conversation_id,
                        "message_id": conversation.message_id,
                        "voice": "maple",
                    })
                if auto_continue and conversation.finish_reason == "max_tokens":
                    conversation.finish_reason = None
                    action = "continue"
                    await asyncio.sleep(5)
                else:
                    break
            yield FinishReason(conversation.finish_reason)

    @classmethod
    async def iter_messages_line(cls, session: StreamSession, line: bytes, fields: Conversation) -> AsyncIterator:
        if not line.startswith(b"data: "):
            return
        elif line.startswith(b"data: [DONE]"):
            if fields.finish_reason is None:
                fields.finish_reason = "error"
            return
        try:
            line = json.loads(line[6:])
        except:
            return
        if isinstance(line, dict) and "v" in line:
            v = line.get("v")
            if isinstance(v, str) and fields.is_recipient:
                if "p" not in line or line.get("p") == "/message/content/parts/0":
                    yield v
            elif isinstance(v, list) and fields.is_recipient:
                for m in v:
                    if m.get("p") == "/message/content/parts/0":
                        yield m.get("v")
                    elif m.get("p") == "/message/metadata":
                        fields.finish_reason = m.get("v", {}).get("finish_details", {}).get("type")
                        break
            elif isinstance(v, dict):
                if fields.conversation_id is None:
                    fields.conversation_id = v.get("conversation_id")
                    debug.log(f"OpenaiChat: New conversation: {fields.conversation_id}")
                m = v.get("message", {})
                fields.is_recipient = m.get("recipient", "all") == "all"
                if fields.is_recipient:
                    c = m.get("content", {})
                    if c.get("content_type") == "multimodal_text":
                        generated_images = []
                        for element in c.get("parts"):
                            if isinstance(element, dict) and element.get("content_type") == "image_asset_pointer":
                                image = cls.get_generated_image(session, cls._headers, element)
                                generated_images.append(image)
                        for image_response in await asyncio.gather(*generated_images):
                            if image_response is not None:
                                yield image_response
                    if m.get("author", {}).get("role") == "assistant":
                        fields.message_id = v.get("message", {}).get("id")
            return
        if "error" in line and line.get("error"):
            raise RuntimeError(line.get("error"))

    @classmethod
    async def synthesize(cls, params: dict) -> AsyncIterator[bytes]:
        await cls.login()
        async with StreamSession(
            impersonate="chrome",
            timeout=900
        ) as session:
            async with session.get(
                f"{cls.url}/backend-api/synthesize",
                params=params,
                headers=cls._headers
            ) as response:
                await raise_for_status(response)
                async for chunk in response.iter_content():
                    yield chunk

    @classmethod
    async def login(cls, proxy: str = None):
        if cls._expires is not None and cls._expires < time.time():
            cls._headers = cls._api_key = None
        try:
            await get_request_config(proxy)
            cls._create_request_args(RequestConfig.cookies, RequestConfig.headers)
            cls._set_api_key(RequestConfig.access_token)
        except NoValidHarFileError:
            if has_nodriver:
                await cls.nodriver_auth(proxy)
            else:
                raise

    @classmethod
    async def nodriver_auth(cls, proxy: str = None):
        browser = await get_nodriver(proxy=proxy)
        page = browser.main_tab
        def on_request(event: nodriver.cdp.network.RequestWillBeSent):
            if event.request.url == start_url or event.request.url.startswith(conversation_url):
                RequestConfig.access_request_id = event.request_id
                RequestConfig.headers = event.request.headers
            elif event.request.url in (backend_url, backend_anon_url):
                if "OpenAI-Sentinel-Proof-Token" in event.request.headers:
                        RequestConfig.proof_token = json.loads(base64.b64decode(
                            event.request.headers["OpenAI-Sentinel-Proof-Token"].split("gAAAAAB", 1)[-1].encode()
                        ).decode())
                if "OpenAI-Sentinel-Turnstile-Token" in event.request.headers:
                    RequestConfig.turnstile_token = event.request.headers["OpenAI-Sentinel-Turnstile-Token"]
                if "Authorization" in event.request.headers:
                    RequestConfig.access_token = event.request.headers["Authorization"].split()[-1]
            elif event.request.url == arkose_url:
                RequestConfig.arkose_request = arkReq(
                    arkURL=event.request.url,
                    arkBx=None,
                    arkHeader=event.request.headers,
                    arkBody=event.request.post_data,
                    userAgent=event.request.headers.get("user-agent")
                )
        await page.send(nodriver.cdp.network.enable())
        page.add_handler(nodriver.cdp.network.RequestWillBeSent, on_request)
        page = await browser.get(cls.url)
        try:
            if RequestConfig.access_request_id is not None:
                body = await page.send(get_response_body(RequestConfig.access_request_id))
                if isinstance(body, tuple) and body:
                    body = body[0]
                if body:
                    match = re.search(r'"accessToken":"(.*?)"', body)
                    if match:
                        RequestConfig.access_token = match.group(1)
        except KeyError:
            pass
        for c in await page.send(nodriver.cdp.network.get_cookies([cls.url])):
            RequestConfig.cookies[c.name] = c.value
        user_agent = await page.evaluate("window.navigator.userAgent")
        await page.select("#prompt-textarea", 240)
        while True:
            if RequestConfig.proof_token:
                break
            await asyncio.sleep(1)
        await page.close()
        cls._create_request_args(RequestConfig.cookies, RequestConfig.headers, user_agent=user_agent)
        cls._set_api_key(RequestConfig.access_token)

    @staticmethod
    def get_default_headers() -> dict:
        return {
            **DEFAULT_HEADERS,
            "content-type": "application/json",
        }

    @classmethod
    def _create_request_args(cls, cookies: Cookies = None, headers: dict = None, user_agent: str = None):
        cls._headers = cls.get_default_headers() if headers is None else headers
        if user_agent is not None:
            cls._headers["user-agent"] = user_agent
        cls._cookies = {} if cookies is None else cookies
        cls._update_cookie_header()

    @classmethod
    def _update_request_args(cls, session: StreamSession):
        for c in session.cookie_jar if hasattr(session, "cookie_jar") else session.cookies.jar:
            cls._cookies[c.key if hasattr(c, "key") else c.name] = c.value
        cls._update_cookie_header()

    @classmethod
    def _set_api_key(cls, api_key: str):
        cls._api_key = api_key
        cls._expires = int(time.time()) + 60 * 60 * 4
        if api_key:
            cls._headers["authorization"] = f"Bearer {api_key}"

    @classmethod
    def _update_cookie_header(cls):
        cls._headers["cookie"] = format_cookies(cls._cookies)

class Conversation(BaseConversation):
    """
    Class to encapsulate response fields.
    """
    def __init__(self, conversation_id: str = None, message_id: str = None, finish_reason: str = None):
        self.conversation_id = conversation_id
        self.message_id = message_id
        self.finish_reason = finish_reason
        self.is_recipient = False