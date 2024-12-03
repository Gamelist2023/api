from __future__ import annotations

import logging
import json
import uvicorn
import secrets
import os
import shutil

import os.path
from fastapi import FastAPI, Response, Request, UploadFile, Depends
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.responses import StreamingResponse, RedirectResponse, HTMLResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.security import APIKeyHeader
from starlette.exceptions import HTTPException
from starlette.status import (
    HTTP_200_OK,
    HTTP_422_UNPROCESSABLE_ENTITY, 
    HTTP_404_NOT_FOUND,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from fastapi.encoders import jsonable_encoder
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Union, Optional, List
try:
    from typing import Annotated
except ImportError:
    class Annotated:
        pass

import g4f
import g4f.debug
from g4f.client import AsyncClient, ChatCompletion, ImagesResponse, convert_to_provider
from g4f.providers.response import BaseConversation
from g4f.client.helper import filter_none
from g4f.image import is_accepted_format, is_data_uri_an_image, images_dir
from g4f.typing import Messages
from g4f.errors import ProviderNotFoundError, ModelNotFoundError, MissingAuthError
from g4f.cookies import read_cookie_files, get_cookies_dir
from g4f.Provider import ProviderType, ProviderUtils, __providers__
from g4f.gui import get_gui_app

logger = logging.getLogger(__name__)

DEFAULT_PORT = 1337

def create_app(g4f_api_key: str = None):
    app = FastAPI()

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = Api(app, g4f_api_key=g4f_api_key)

    if AppConfig.gui:
        @app.get("/")
        async def home():
            return HTMLResponse(f'g4f v-{g4f.version.utils.current_version}:<br><br>'
                                'Start to chat: <a href="/chat/">/chat/</a><br>'
                                'Open Swagger UI at: '
                                '<a href="/docs">/docs</a>')

    api.register_routes()
    api.register_authorization()
    api.register_validation_exception_handler()

    if AppConfig.gui:
        gui_app = WSGIMiddleware(get_gui_app())
        app.mount("/", gui_app)

    # Read cookie files if not ignored
    if not AppConfig.ignore_cookie_files:
        read_cookie_files()

    return app

def create_app_debug(g4f_api_key: str = None):
    g4f.debug.logging = True
    return create_app(g4f_api_key)

class ChatCompletionsConfig(BaseModel):
    messages: Messages = Field(examples=[[{"role": "system", "content": ""}, {"role": "user", "content": ""}]])
    model: str = Field(default="")
    provider: Optional[str] = None
    stream: bool = False
    image: Optional[str] = None
    image_name: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stop: Union[list[str], str, None] = None
    api_key: Optional[str] = None
    web_search: Optional[bool] = None
    proxy: Optional[str] = None
    conversation_id: Optional[str] = None
    history_disabled: Optional[bool] = None
    auto_continue: Optional[bool] = None
    timeout: Optional[int] = None

class ImageGenerationConfig(BaseModel):
    prompt: str
    model: Optional[str] = None
    provider: Optional[str] = None
    response_format: str = "url"
    api_key: Optional[str] = None
    proxy: Optional[str] = None

class ProviderResponseModel(BaseModel):
    id: str
    object: str = "provider"
    created: int
    url: Optional[str]
    label: Optional[str]

class ProviderResponseDetailModel(ProviderResponseModel):
    models: list[str]
    image_models: list[str]
    vision_models: list[str]
    params: list[str]

class ModelResponseModel(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: Optional[str]

class ErrorResponseModel(BaseModel):
    error: ErrorResponseMessageModel
    model: Optional[str] = None
    provider: Optional[str] = None

class ErrorResponseMessageModel(BaseModel):
    message: str

class FileResponseModel(BaseModel):
    filename: str
    
class ErrorResponse(Response):
    media_type = "application/json"

    @classmethod
    def from_exception(cls, exception: Exception,
                       config: Union[ChatCompletionsConfig, ImageGenerationConfig] = None,
                       status_code: int = HTTP_500_INTERNAL_SERVER_ERROR):
        return cls(format_exception(exception, config), status_code)

    @classmethod
    def from_message(cls, message: str, status_code: int = HTTP_500_INTERNAL_SERVER_ERROR):
        return cls(format_exception(message), status_code)

    def render(self, content) -> bytes:
        return str(content).encode(errors="ignore")

class AppConfig:
    ignored_providers: Optional[list[str]] = None
    g4f_api_key: Optional[str] = None
    ignore_cookie_files: bool = False
    model: str = None,
    provider: str = None
    image_provider: str = None
    proxy: str = None
    gui: bool = False

    @classmethod
    def set_config(cls, **data):
        for key, value in data.items():
            setattr(cls, key, value)

list_ignored_providers: list[str] = None

def set_list_ignored_providers(ignored: list[str]):
    global list_ignored_providers
    list_ignored_providers = ignored

class Api:
    def __init__(self, app: FastAPI, g4f_api_key=None) -> None:
        self.app = app
        self.client = AsyncClient()
        self.g4f_api_key = g4f_api_key
        self.get_g4f_api_key = APIKeyHeader(name="g4f-api-key")
        self.conversations: dict[str, dict[str, BaseConversation]] = {}

    security = HTTPBearer(auto_error=False)

    def register_authorization(self):
        @self.app.middleware("http")
        async def authorization(request: Request, call_next):
            if self.g4f_api_key and request.url.path not in ("/", "/v1"):
                try:
                    user_g4f_api_key = await self.get_g4f_api_key(request)
                except HTTPException as e:
                    if e.status_code == 403:
                        return ErrorResponse.from_message("G4F API key required", HTTP_401_UNAUTHORIZED)
                if not secrets.compare_digest(self.g4f_api_key, user_g4f_api_key):
                    return ErrorResponse.from_message("Invalid G4F API key", HTTP_403_FORBIDDEN)
            return await call_next(request)

    def register_validation_exception_handler(self):
        @self.app.exception_handler(RequestValidationError)
        async def validation_exception_handler(request: Request, exc: RequestValidationError):
            details = exc.errors()
            modified_details = []
            for error in details:
                modified_details.append({
                    "loc": error["loc"],
                    "message": error["msg"],
                    "type": error["type"],
                })
            return JSONResponse(
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                content=jsonable_encoder({"detail": modified_details}),
            )

    def register_routes(self):
        @self.app.get("/")
        async def read_root():
            return RedirectResponse("/v1", 302)

        @self.app.get("/v1")
        async def read_root_v1():
            return HTMLResponse('g4f API: Go to '
                                '<a href="/v1/models">models</a>, '
                                '<a href="/v1/chat/completions">chat/completions</a>, or '
                                '<a href="/v1/images/generate">images/generate</a> <br><br>'
                                'Open Swagger UI at: '
                                '<a href="/docs">/docs</a>')

        @self.app.get("/v1/models", responses={
            HTTP_200_OK: {"model": List[ModelResponseModel]},
        })
        async def models():
            model_list = dict(
                (model, g4f.models.ModelUtils.convert[model])
                for model in g4f.Model.__all__()
            )
            return [{
                'id': model_id,
                'object': 'model',
                'created': 0,
                'owned_by': model.base_provider
            } for model_id, model in model_list.items()]

        @self.app.get("/v1/models/{model_name}", responses={
            HTTP_200_OK: {"model": ModelResponseModel},
            HTTP_404_NOT_FOUND: {"model": ErrorResponseModel},
        })
        async def model_info(model_name: str) -> ModelResponseModel:
            if model_name in g4f.models.ModelUtils.convert:
                model_info = g4f.models.ModelUtils.convert[model_name]
                return JSONResponse({
                    'id': model_name,
                    'object': 'model',
                    'created': 0,
                    'owned_by': model_info.base_provider
                })
            return ErrorResponse.from_message("The model does not exist.", HTTP_404_NOT_FOUND)

        @self.app.post("/v1/chat/completions", responses={
            HTTP_200_OK: {"model": ChatCompletion},
            HTTP_401_UNAUTHORIZED: {"model": ErrorResponseModel},
            HTTP_404_NOT_FOUND: {"model": ErrorResponseModel},
            HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponseModel},
            HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponseModel},
        })
        async def chat_completions(
            config: ChatCompletionsConfig,
            credentials: Annotated[HTTPAuthorizationCredentials, Depends(Api.security)] = None,
            provider: str = None
        ):
            try:
                config.provider = provider if config.provider is None else config.provider
                if config.provider is None:
                    config.provider = AppConfig.provider
                if credentials is not None:
                    config.api_key = credentials.credentials

                conversation = return_conversation = None
                if config.conversation_id is not None and config.provider is not None:
                    return_conversation = True
                    if config.conversation_id in self.conversations:
                        if config.provider in self.conversations[config.conversation_id]:
                            conversation = self.conversations[config.conversation_id][config.provider]

                if config.image is not None:
                    try:
                        is_data_uri_an_image(config.image)
                    except ValueError as e:
                        return ErrorResponse.from_message(f"The image you send must be a data URI. Example: data:image/webp;base64,...", status_code=HTTP_422_UNPROCESSABLE_ENTITY)

                # Create the completion response
                response = self.client.chat.completions.create(
                    **filter_none(
                        **{
                            "model": AppConfig.model,
                            "provider": AppConfig.provider,
                            "proxy": AppConfig.proxy,
                            **config.model_dump(exclude_none=True),
                            **{
                                "conversation_id": None,
                                "return_conversation": return_conversation,
                                "conversation": conversation
                            }
                        },
                        ignored=AppConfig.ignored_providers
                    ),
                )

                if not config.stream:
                    return await response

                async def streaming():
                    try:
                        async for chunk in response:
                            if isinstance(chunk, BaseConversation):
                                if config.conversation_id is not None and config.provider is not None:
                                    if config.conversation_id not in self.conversations:
                                        self.conversations[config.conversation_id] = {}
                                    self.conversations[config.conversation_id][config.provider] = chunk
                            else:
                                yield f"data: {chunk.json()}\n\n"
                    except GeneratorExit:
                        pass
                    except Exception as e:
                        logger.exception(e)
                        yield f'data: {format_exception(e, config)}\n\n'
                    yield "data: [DONE]\n\n"

                return StreamingResponse(streaming(), media_type="text/event-stream")

            except (ModelNotFoundError, ProviderNotFoundError) as e:
                logger.exception(e)
                return ErrorResponse.from_exception(e, config, HTTP_404_NOT_FOUND)
            except MissingAuthError as e:
                logger.exception(e)
                return ErrorResponse.from_exception(e, config, HTTP_401_UNAUTHORIZED)
            except Exception as e:
                logger.exception(e)
                return ErrorResponse.from_exception(e, config, HTTP_500_INTERNAL_SERVER_ERROR)

        responses = {
            HTTP_200_OK: {"model": ImagesResponse},
            HTTP_401_UNAUTHORIZED: {"model": ErrorResponseModel},
            HTTP_404_NOT_FOUND: {"model": ErrorResponseModel},
            HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponseModel},
        }

        @self.app.post("/v1/images/generate", responses=responses)
        @self.app.post("/v1/images/generations", responses=responses)
        async def generate_image(
            request: Request,
            config: ImageGenerationConfig,
            credentials: Annotated[HTTPAuthorizationCredentials, Depends(Api.security)] = None
        ):
            if credentials is not None:
                config.api_key = credentials.credentials
            try:
                response = await self.client.images.generate(
                    prompt=config.prompt,
                    model=config.model,
                    provider=AppConfig.image_provider if config.provider is None else config.provider,
                    **filter_none(
                        response_format = config.response_format,
                        api_key = config.api_key,
                        proxy = config.proxy
                    )
                )
                for image in response.data:
                    if hasattr(image, "url") and image.url.startswith("/"):
                        image.url = f"{request.base_url}{image.url.lstrip('/')}"
                return response
            except (ModelNotFoundError, ProviderNotFoundError) as e:
                logger.exception(e)
                return ErrorResponse.from_exception(e, config, HTTP_404_NOT_FOUND)
            except MissingAuthError as e:
                logger.exception(e)
                return ErrorResponse.from_exception(e, config, HTTP_401_UNAUTHORIZED)
            except Exception as e:
                logger.exception(e)
                return ErrorResponse.from_exception(e, config, HTTP_500_INTERNAL_SERVER_ERROR)

        @self.app.get("/v1/providers", responses={
            HTTP_200_OK: {"model": List[ProviderResponseModel]},
        })
        async def providers():
            return [{
                'id': provider.__name__,
                'object': 'provider',
                'created': 0,
                'url': provider.url,
                'label': getattr(provider, "label", None),
            } for provider in __providers__ if provider.working]

        @self.app.get("/v1/providers/{provider}", responses={
            HTTP_200_OK: {"model": ProviderResponseDetailModel},
            HTTP_404_NOT_FOUND: {"model": ErrorResponseModel},
        })
        async def providers_info(provider: str):
            if provider not in ProviderUtils.convert:
                return ErrorResponse.from_message("The provider does not exist.", 404)
            provider: ProviderType = ProviderUtils.convert[provider]
            def safe_get_models(provider: ProviderType) -> list[str]:
                try:
                    return provider.get_models() if hasattr(provider, "get_models") else []
                except:
                    return []
            return {
                'id': provider.__name__,
                'object': 'provider',
                'created': 0,
                'url': provider.url,
                'label': getattr(provider, "label", None),
                'models': safe_get_models(provider),
                'image_models': getattr(provider, "image_models", []) or [],
                'vision_models': [model for model in [getattr(provider, "default_vision_model", None)] if model],
                'params': [*provider.get_parameters()] if hasattr(provider, "get_parameters") else []
            }

        @self.app.post("/v1/upload_cookies", responses={
            HTTP_200_OK: {"model": List[FileResponseModel]},
        })
        def upload_cookies(files: List[UploadFile]):
            response_data = []
            for file in files:
                try:
                    if file and file.filename.endswith(".json") or file.filename.endswith(".har"):
                        filename = os.path.basename(file.filename)
                        with open(os.path.join(get_cookies_dir(), filename), 'wb') as f:
                            shutil.copyfileobj(file.file, f)
                        response_data.append({"filename": filename})
                finally:
                    file.file.close()
            return response_data

        @self.app.get("/v1/synthesize/{provider}", responses={
            HTTP_200_OK: {"content": {"audio/*": {}}},
            HTTP_404_NOT_FOUND: {"model": ErrorResponseModel},
            HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponseModel},
        })
        async def synthesize(request: Request, provider: str):
            try:
                provider_handler = convert_to_provider(provider)
            except ProviderNotFoundError as e:
                return ErrorResponse.from_exception(e, status_code=HTTP_404_NOT_FOUND)
            if not hasattr(provider_handler, "synthesize"):
                return ErrorResponse.from_message("Provider doesn't support synthesize", HTTP_404_NOT_FOUND)
            if len(request.query_params) == 0:
                return ErrorResponse.from_message("Missing query params", HTTP_422_UNPROCESSABLE_ENTITY)
            response_data = provider_handler.synthesize({**request.query_params})
            content_type = getattr(provider_handler, "synthesize_content_type", "application/octet-stream")
            return StreamingResponse(response_data, media_type=content_type)

        @self.app.get("/images/{filename}", response_class=FileResponse, responses={
            HTTP_200_OK: {"content": {"image/*": {}}},
            HTTP_404_NOT_FOUND: {}
        })
        async def get_image(filename):
            target = os.path.join(images_dir, filename)

            if not os.path.isfile(target):
                return Response(status_code=404)

            with open(target, "rb") as f:
                content_type = is_accepted_format(f.read(12))

            return FileResponse(target, media_type=content_type)

def format_exception(e: Union[Exception, str], config: Union[ChatCompletionsConfig, ImageGenerationConfig] = None, image: bool = False) -> str:
    last_provider = {} if not image else g4f.get_last_provider(True)
    provider = (AppConfig.image_provider if image else AppConfig.provider)
    model = AppConfig.model
    if config is not None:
        if config.provider is not None:
            provider = config.provider
        if config.model is not None:
            model = config.model
    if isinstance(e, str):
        message = e
    else:
        message = f"{e.__class__.__name__}: {e}"
    return json.dumps({
        "error": {"message": message},
        "model":  last_provider.get("model") if model is None else model,
        **filter_none(
            provider=last_provider.get("name") if provider is None else provider
        )
    })

def run_api(
    host: str = '0.0.0.0',
    port: int = None,
    bind: str = None,
    debug: bool = False,
    workers: int = None,
    use_colors: bool = None,
    reload: bool = False
) -> None:
    print(f'Starting server... [g4f v-{g4f.version.utils.current_version}]' + (" (debug)" if debug else ""))
    if use_colors is None:
        use_colors = debug
    if bind is not None:
        host, port = bind.split(":")
    if port is None:
        port = DEFAULT_PORT
    uvicorn.run(
        f"g4f.api:create_app{'_debug' if debug else ''}", 
        host=host, 
        port=int(port), 
        workers=workers, 
        use_colors=use_colors, 
        factory=True, 
        reload=reload
    )
