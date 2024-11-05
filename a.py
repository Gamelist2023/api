import g4f.Provider
from g4f.client import Client
from g4f.cookies import read_cookie_files
import g4f.debug
import g4f
import os

g4f.debug.logging = True  # Enable debug logging
g4f.debug.version_check = True  # Disable automatic version checking

cookies_dir = os.path.join(os.path.dirname(__file__), "har")

client = Client(
        provider=g4f.Provider.Koala,
        #api_key="AIzaSyA_WGA0iKHarVC_XOEE_GkH4SPPypqWYsg"
        api_key=read_cookie_files(cookies_dir),
              )
response =  client.chat.completions.create(
    model="default",
    messages=[{"role": "user", "content": "hello"}],
    #stream=True,
)

print(response.choices[0].message.content)
#for chunk in response:
#  if chunk.choices[0].delta.content:
#    print(chunk.choices[0].delta.content, flush=True, end="")
