import os
import g4f
from g4f.cookies import read_cookie_files,set_cookies_dir
from g4f.image import ImageResponse
import asyncio
import g4f.Provider
from g4f.client import Client

cookies_dir = os.path.join(os.path.dirname(__file__), "har")


async def main():
    client = Client(api_key=read_cookie_files(cookies_dir),provider=g4f.Provider.BingCreateImages)
    
    response = await client.images.async_generate(
        prompt="White Cat Jumping",
        model="dall-e"
    )
    
    image_url = response.data[0].url
    print(f"Generated image URL: {image_url}")

asyncio.run(main())
