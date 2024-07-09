import os
import g4f
from g4f.Provider import HuggingChat,OpenRouter,Blackbox,You,Gemini,Bing,Liaobots,GeminiProChat,OpenaiChat,HuggingFace,Reka,Koala,GeminiPro,Pizzagpt,Openai
from g4f.cookies import read_cookie_files, set_cookies_dir

g4f.debug.logging = True  
g4f.debug.version_check = True 
cookies_dir = os.path.join(os.path.dirname(__file__), "har_and_cookies")

read_cookie_files(cookies_dir)

response = g4f.ChatCompletion.create(
    provider=OpenaiChat,
    model="auto",
    api_key=set_cookies_dir(cookies_dir),
    messages=[{"role": "user", "content": "Hello your speaking English?"}],
)  

print(response)