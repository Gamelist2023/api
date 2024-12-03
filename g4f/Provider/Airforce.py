from __future__ import annotations

import random
import json
import re

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
from urllib.parse import quote

from ..typing import AsyncResult, Messages
from .base_provider import AsyncGeneratorProvider, ProviderModelMixin
from ..image import ImageResponse
from ..requests import StreamSession, raise_for_status

def split_message(message: str, max_length: int = 1000) -> list[str]:
    """Splits the message into parts up to (max_length)."""
    chunks = []
    while len(message) > max_length:
        split_point = message.rfind(' ', 0, max_length)
        if split_point == -1:
            split_point = max_length
        chunks.append(message[:split_point])
        message = message[split_point:].strip()
    if message:
        chunks.append(message)
    return chunks

class Airforce(AsyncGeneratorProvider, ProviderModelMixin):
    url = "https://llmplayground.net"
    api_endpoint_completions = "https://api.airforce/chat/completions"
    api_endpoint_imagine = "https://api.airforce/imagine2"
    working = True
    supports_system_message = True
    supports_message_history = True

    @classmethod
    def fetch_completions_models(cls):
        response = requests.get('https://api.airforce/models', verify=False)
        response.raise_for_status()
        data = response.json()
        return [model['id'] for model in data['data']]

    @classmethod
    def fetch_imagine_models(cls):
        response = requests.get('https://api.airforce/imagine/models', verify=False)
        response.raise_for_status()
        return response.json()

    default_model = "gpt-4o-mini"
    default_image_model = "flux"
    additional_models_imagine = ["stable-diffusion-xl-base", "stable-diffusion-xl-lightning", "flux-1.1-pro"]

    @classmethod
    def get_models(cls):
        if not cls.models:
            cls.image_models = [*cls.fetch_imagine_models(), *cls.additional_models_imagine]
            cls.models = [
                *cls.fetch_completions_models(),
                *cls.image_models
            ]
        return cls.models

    model_aliases = {        
        ### completions ###
        # openchat
        "openchat-3.5": "openchat-3.5-0106",
        
        # deepseek-ai
        "deepseek-coder": "deepseek-coder-6.7b-instruct",
        
        # NousResearch
        "hermes-2-dpo": "Nous-Hermes-2-Mixtral-8x7B-DPO",
        "hermes-2-pro": "hermes-2-pro-mistral-7b",
        
        # teknium
        "openhermes-2.5": "openhermes-2.5-mistral-7b",
        
        # liquid
        "lfm-40b": "lfm-40b-moe",
        
        # DiscoResearch
        "german-7b": "discolm-german-7b-v1",
            
        # meta-llama
        "llama-2-7b": "llama-2-7b-chat-int8",
        "llama-2-7b": "llama-2-7b-chat-fp16",
        "llama-3.1-70b": "llama-3.1-70b-chat",
        "llama-3.1-8b": "llama-3.1-8b-chat",
        "llama-3.1-70b": "llama-3.1-70b-turbo",
        "llama-3.1-8b": "llama-3.1-8b-turbo",
        
        # inferless
        "neural-7b": "neural-chat-7b-v3-1",
        
        # HuggingFaceH4
        "zephyr-7b": "zephyr-7b-beta",
        
        
        ### imagine ###
        "sdxl": "stable-diffusion-xl-base",
        "sdxl": "stable-diffusion-xl-lightning", 
        "flux-pro": "flux-1.1-pro",
    }

    @classmethod
    def create_async_generator(
        cls,
        model: str,
        messages: Messages,
        proxy: str = None,
        prompt: str = None,
        seed: int = None,
        size: str = "1:1", # "1:1", "16:9", "9:16", "21:9", "9:21", "1:2", "2:1"
        stream: bool = False,
        **kwargs
    ) -> AsyncResult:
        model = cls.get_model(model)

        if model in cls.image_models:
            if prompt is None:
                prompt = messages[-1]['content']
            return cls._generate_image(model, prompt, proxy, seed, size)
        else:
            return cls._generate_text(model, messages, proxy, stream, **kwargs)

    @classmethod
    async def _generate_image(
        cls,
        model: str,
        prompt: str,
        proxy: str = None,
        seed: int = None,
        size: str = "1:1",
        **kwargs
    ) -> AsyncResult:
        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "no-cache",
            "user-agent": "Mozilla/5.0"
        }
        if seed is None:
            seed = random.randint(0, 100000)

        async with StreamSession(headers=headers, proxy=proxy) as session:
            params = {
                "model": model,
                "prompt": prompt,
                "size": size,
                "seed": seed
            }
            async with session.get(f"{cls.api_endpoint_imagine}", params=params) as response:
                await raise_for_status(response)
                content_type = response.headers.get('Content-Type', '').lower()

                if 'application/json' in content_type:
                    raise RuntimeError(await response.json().get("error", {}).get("message"))
                elif content_type.startswith("image/"):
                    image_url = f"{cls.api_endpoint_imagine}?model={model}&prompt={quote(prompt)}&size={size}&seed={seed}"
                    yield ImageResponse(images=image_url, alt=prompt)

    @classmethod
    async def _generate_text(
        cls,
        model: str,
        messages: Messages,
        proxy: str = None,
        stream: bool = False,
        max_tokens: int = 4096,
        temperature: float = 1,
        top_p: float = 1,
        **kwargs
    ) -> AsyncResult:
        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "authorization": "Bearer missing api key",
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0"
        }

        full_message = "\n".join(
            [f"{msg['role'].capitalize()}: {msg['content']}" for msg in messages]
        )

        message_chunks = split_message(full_message, max_length=1000)

        async with StreamSession(headers=headers, proxy=proxy) as session:
            full_response = ""
            for chunk in message_chunks:
                data = {
                    "messages": [{"role": "user", "content": chunk}],
                    "model": model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p,
                    "stream": stream
                }

                async with session.post(cls.api_endpoint_completions, json=data) as response:
                    await raise_for_status(response)
                    content_type = response.headers.get('Content-Type', '').lower()
                    
                    if 'application/json' in content_type:
                        json_data = await response.json()
                        if json_data.get("model") == "error":
                            raise RuntimeError(json_data['choices'][0]['message'].get('content', ''))
                    if stream:
                        async for line in response.iter_lines():
                            if line:
                                line = line.decode('utf-8').strip()
                                if line.startswith("data: ") and line != "data: [DONE]":
                                    json_data = json.loads(line[6:])
                                    content = json_data['choices'][0]['delta'].get('content', '')
                                    if content:
                                        yield cls._filter_content(content)
                    else:
                        content = json_data['choices'][0]['message']['content']
                        full_response += cls._filter_content(content)

            yield full_response

    @classmethod
    def _filter_content(cls, part_response: str) -> str:
        part_response = re.sub(
            r"One message exceeds the \d+chars per message limit\..+https:\/\/discord\.com\/invite\/\S+",
            '',
            part_response
        )
        
        part_response = re.sub(
            r"Rate limit \(\d+\/minute\) exceeded\. Join our discord for more: .+https:\/\/discord\.com\/invite\/\S+",
            '',
            part_response
        )
        
        part_response = re.sub(
            r"\[ERROR\] '\w{8}-\w{4}-\w{4}-\w{4}-\w{12}'", # any-uncensored 
            '',
            part_response
        )
        return part_response
