import os
import g4f
from g4f.cookies import read_cookie_files
import asyncio
import g4f.Provider
from g4f.client import AsyncClient

cookies_dir = os.path.join(os.path.dirname(__file__), "har")
g4f.debug.logging = True  # Enable debug logging
g4f.debug.version_check = False


async def main():
    client = AsyncClient(api_key=read_cookie_files(cookies_dir),response_format="b64_json",n=1)
    
    response = await client.images.generate(
        prompt="White Cat",
        model="dall-e-3",
        response_format="b64_json",
        n=1

    )
    try:      
        print(f"Generated image URL: {response.data[0].b64_json}")
    except Exception as e:
        print(f"An error occurred: {e}")
asyncio.run(main())
