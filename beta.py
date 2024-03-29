from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Optional
from g4f.image import ImageResponse
from sydney import SydneyClient



import g4f, json,os
import logging
import shutil
import threading
import time
import re
import uvicorn
import aiohttp






g4f.debug.logging = True  # Enable debug logging
g4f.debug.version_check = False  # Disable automatic version checking


logging.basicConfig(level=logging.INFO)

Token = "15VBs_g92c5WcLeDh7F058OJrZOFeV0IsKBevB65QZsGCHX4eBXFAMm9HBHLnxXurk9PR0FMyN-aIUFx9aOYSDcCC6SUWjFMpz83jsmjmDCqiU9uyITa4z-xzu5BdxPp8zVNIj4o9nAnJTVQSFGeDhRC7r1Ge5t2xA_h946daH1GEfe9XCpHIawXez3RMokifNtyDXMgnPD-nPJnNxO-qXA"
os.environ["BING_COOKIES"] = Token

app = FastAPI()

app.mount("/home", StaticFiles(directory="home"), name="home")

with open('cookies.json', 'r') as file:
    data = json.load(file)

cookies={}
for cookie in data:
    cookies[cookie["name"]] = cookie["value"]




# Initialize the conversation history
    




# Set up logging to console
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(message)s',
                    handlers=[logging.StreamHandler()])

def cleanup_directories(root_dir, delay):
    while True:
        now = time.time()
        for dir in Path(root_dir).iterdir():
            if dir.is_dir() and re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', dir.name) and now - dir.stat().st_mtime > delay:
                shutil.rmtree(dir)
        time.sleep(delay)

# Start the cleanup task in a separate thread
threading.Thread(target=cleanup_directories, args=('.', 5*60)).start()

@app.get('/')
def home(request: Request):
    templates = Jinja2Templates(directory="templates")
    return templates.TemplateResponse("index.html", {"request": request})

conversation_history = {}

geminis = {}
@app.get('/ask')
async def ask(request: Request):
    global conversation_history
    global geminis
    text = request.query_params.get('text')
    user_id = request.query_params.get('user_id')  # Get the user ID from the request

    # If no user_id is provided, use the IP address as the identifier
    if not user_id:
        user_id = request.client.host

    if not text:
        return JSONResponse(content={"response": "No question asked"}, status_code=200)

    # If this user ID is new, initialize a new conversation history for it
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    # Add the new message to the conversation history
    conversation_history[user_id].append({"role": "user", "content": text})

    # Initialize a new conversation for geminis[user_id] for each request
    geminis[user_id] = [{"role":"user", "content": text}]

    # If the conversation history exceeds 5 messages, remove the oldest message
    if len(conversation_history[user_id]) > 5:
        conversation_history[user_id].pop(0)

    # If the prompt is "!reset", reset the conversation and continue
    if text == "!reset":
        await sydney.reset_conversation()
        return JSONResponse(content={"response": "Conversation reset"}, status_code=200)

    # If the prompt is "!bing", use sydney.ask() to get the response
    if text == "!bing":   
        async with SydneyClient() as sydney:
            response = await sydney.ask(f"{text}", citations=False,search=True)
            logging.info("Successfully called sydney.ask()")
            return JSONResponse(content=response, status_code=200)

    try:
        response = await g4f.ChatCompletion.create_async(
          model="gemini-pro",
          messages=geminis[user_id],
          provider=g4f.Provider.GeminiPro,
          api_key="AIzaSyDHCVkGkQ0d5lQ230ssHzf3rg2XZBjNCZM",
        )
    except Exception as e:
        logging.error(f"Error occurred: {str(e)}")
        try:
          async with SydneyClient() as sydney:
              logging.info("Attempting to call sydney.ask()")
              response = await sydney.ask(f"{text}", citations=False)
              logging.info("Successfully called sydney.ask()")
        except Exception as e:
         if 'candidates' in str(e):
            logging.error("A 'candidates' error occurred. Please check your input and try again.")
            return JSONResponse(content={"error": "A 'candidates' エラーが起きましたこのエラーは修正まだしてません、一応修正パッチ出してるけど効いてない[しりとりなどで起きます]"}, status_code=500)
        else:
            logging.error(f"Error occurred: {str(e)}")
            return JSONResponse(content={"error": str(e)}, status_code=500)

        # Check if the response is a dictionary
        if isinstance(response, dict):
            # Check if the response is a reply to the user's message
            if response['role'] == 'assistant' and geminis[user_id][-1]['role'] == 'user':
                # Add the assistant's response to the conversation history
                conversation_history[user_id].append({"role": "assistant", "content": response['content']})
            else:
                # Handle the case where the AI initiates the conversation
                conversation_history[user_id].append({"role": "assistant", "content": ""})
                geminis[user_id].append({"role": "assistant", "content": ""})
        elif isinstance(response, str):
            # If the response is a string, convert it to a dictionary
            response_dict = {"role": "assistant", "content": response}
            conversation_history[user_id].append(response_dict)
            geminis[user_id].append(response_dict)
        else:
            logging.error(f"Unexpected response type: {type(response)}")


    # Decode the Unicode escaped string
    try:
        decoded_response = json.loads(json.dumps(response))
    except json.decoder.JSONDecodeError:
        error_message = "Invalid JSON response"
        logging.error(f"{error_message}: {response.text}")
        return JSONResponse(content={"error": error_message}, status_code=500)
    else:
        return JSONResponse(content=decoded_response, status_code=200)



bing = {}

@app.get("/chat")
async def ask(request: Request):
    global bing
    text = request.query_params.get('text')
    user_id = request.query_params.get('user_id')  # Get the user ID from the request

    # If no user_id is provided, use the IP address as the identifier
    if not user_id:
        user_id = request.client.host

    if not text:
        return JSONResponse(content={"response": "No question asked"}, status_code=200)
    
    if user_id not in bing:
        bing[user_id] = []
    
    bing[user_id].append({"comment": text, "user_id": user_id})

    try:
        async with SydneyClient(style="precise") as sydney:
            logging.info("SydneyClient has started.")
            response = await sydney.ask(f"{text}", citations=False)
            logging.info("SydneyClient is processing.")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        return JSONResponse(content={"response": f"An error occurred while processing your request: {str(e)}."}, status_code=500)

    logging.info("SydneyClient has finished processing.")
    print(f"AI:{response}")
    return JSONResponse(content={"response":response}, status_code=200)







    
@app.get("/generate_image")
async def generate_image(prompt: Optional[str] = None):
    # Ensure a prompt was provided
    if prompt is None:
        return JSONResponse(content={"error": "No prompt provided"}, status_code=400)

    # Create the image
    chunks = await g4f.ChatCompletion.create_async(
        model="gemini-pro-vision", # Using the default model
        provider=g4f.Provider.GeminiPro, # Specifying the provider as OpenaiChat
        messages=[{"role": "user", "content": f"Create images with {prompt}"}],
        
    )

    # Get image links from response
    images = []
    for chunk in chunks:
        if isinstance(chunk, ImageResponse):
            images.append({
                "image_links": chunk.images, # Generated image links
                "alt": chunk.alt # Used prompt for image generation
            })

    # Return the images in a JSON response
    return {"images": images}




