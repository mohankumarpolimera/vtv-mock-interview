from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os, time, asyncio
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wavfile
import tempfile
import pygame
from openai import OpenAI
import edge_tts

app = FastAPI()
client = OpenAI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")
app.mount("/audio", StaticFiles(directory="audio"), name="audio")

pygame.mixer.init()

SAMPLE_RATE = 16000
BLOCK_SIZE = 4096
SILENCE_THRESHOLD = 0.001
SILENCE_DURATION = 1.0
conversation_log = {
    "Communication": [],
    "Technical": [],
    "HR": []
}
round_sequence = ["Communication", "Technical", "HR"]
round_deadlines = {}

round_durations = {
    "Communication": 120,
    "Technical": 300,
    "HR": 120
}

SYSTEM_PROMPTS = {
    "Communication": (
        "You are a warm and articulate interviewer conducting a communication skills round. "
        "Begin with a friendly greeting, then ask open-ended questions that evaluate the candidate's ability "
        "to express ideas clearly, think critically, and engage in thoughtful conversation. "
        "Ask about global topics such as the impact of technology on society, environmental sustainability, education reforms, "
        "or cultural perspectives. Follow up naturally based on the candidate's answers to simulate a human conversation."
    ),
    "Technical": (
        "You are an experienced senior SAP Developer conducting a technical interview. "
        "Start with a short introduction, then ask practical, real-world technical questions related to SAP "
        "Your tone should be supportive but inquisitive, diving deeper into answers to assess depth of understanding. " 
    ),
    "HR": (
        "You are a seasoned HR professional conducting a behavioral interview. "
        "Start by making the candidate feel at ease. Then ask thoughtful questions related to their experiences, motivations, "
        "teamwork, conflict resolution, career goals, leadership style, and adaptability. "
        "Your tone should be professional, encouraging, and conversational. "
        "Try to understand the candidate’s personality and how well they align with an organization's culture."
    )
}

def record_audio():
    print("Listening... (start speaking)")
    # print("Available devices:", sd.query_devices())
    audio_chunks = []
    silence_start = None
    recording = True

    def audio_callback(indata, frames, time_info, status):
        rms = np.sqrt(np.mean(indata**2))
        audio_chunks.append(indata.copy())

        print(".", end="", flush=True)

        nonlocal silence_start, recording
        if rms < SILENCE_THRESHOLD:
            if silence_start is None:
                silence_start = time.time()
            elif time.time() - silence_start > SILENCE_DURATION:
                recording = False
                raise sd.CallbackStop()
        else:
            silence_start = None

    try:
        input_device = None  # Let sounddevice choose default mic
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, blocksize=BLOCK_SIZE,
                            callback=audio_callback, device=input_device):
            while recording:
                sd.sleep(100)

    except Exception as e:
        print(f"\nRecording error: {e}")
        return None

    if not audio_chunks:
        return None

    audio = np.concatenate(audio_chunks, axis=0)
    if len(audio) / SAMPLE_RATE < 0.5:
        print("\nToo short. Please speak longer.")
        return None

    temp_file = "temp_input.wav"
    wavfile.write(temp_file, SAMPLE_RATE, (audio * 32767).astype(np.int16))
    print("\nRecording complete.")
    return temp_file

def transcribe_audio(audio_file):
    try:
        with open(audio_file, "rb") as file:
            transcript = client.audio.transcriptions.create(
                file=file,
                model="whisper-1",
                response_format="text"
            )
        return transcript.strip()
    except Exception as e:
        print(f"Transcription error: {e}")
        return None

def generate_response(text, history, system_prompt):
    messages = [{"role": "system", "content": system_prompt}]
    for exchange in history[-2:]:
        messages.append({"role": "user", "content": exchange["user"]})
        messages.append({"role": "assistant", "content": exchange["assistant"]})
    messages.append({"role": "user", "content": text})

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.9,
            max_tokens=200
        )
        content = response.choices[0].message.content.strip()
        print("[AI Text]", content)
        return content
    except Exception as e:
        print(f"Response error: {e}")
        return "Could you repeat that, please?"

async def synthesize_speech(text):
    try:
        voice = "en-US-AriaNeural"
        timestamp = int(time.time() * 1000)
        temp_file = f"audio/ai_response_{timestamp}.mp3"

        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(temp_file)

        if not os.path.exists(temp_file):
            print("[ERROR] Audio file not created.")
            return None

        print("[Audio Path]", temp_file)
        return temp_file
    except Exception as e:
        print(f"Edge TTS error: {e}")
        return None

@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("frontend/index.html")

@app.get("/start_round")
async def start_round(round_name: str):
    greet = generate_response("Greet the candidate and start the interview with the first question.", [], SYSTEM_PROMPTS[round_name])
    conversation_log[round_name] = []
    round_deadlines[round_name] = time.time() + round_durations[round_name]
    audio_path = await synthesize_speech(greet)

    if not audio_path or not os.path.exists(audio_path):
        return JSONResponse({"message": greet, "audio_path": None})

    return JSONResponse({"message": greet, "audio_path": "/" + audio_path})

@app.get("/next_round")
async def next_round(current_round: str):
    idx = round_sequence.index(current_round)
    if idx < len(round_sequence) - 1:
        return {"next_round": round_sequence[idx+1]}
    return {"next_round": None}

@app.post("/record_and_respond")
async def record_and_respond(request: Request):
    data = await request.json()
    round_name = data.get("round")
    history = conversation_log[round_name]

    if time.time() > round_deadlines.get(round_name, 0):
        if round_name == "HR":
            farewell = "It was a wonderful experience interacting with you in this round. Thank you for completing the interview."
        else:
            farewell = "It was a wonderful experience interacting with you in this round. Please proceed to the next round."
        audio_path = await synthesize_speech(farewell)
        return JSONResponse({"response": farewell, "audio_path": "/" + audio_path})

    audio_file = record_audio()
    if not audio_file:
        return JSONResponse({"error": "No audio recorded"})

    user_text = transcribe_audio(audio_file)
    os.remove(audio_file)
    if not user_text:
        return JSONResponse({"error": "Could not transcribe"})

    print("[User Input]", user_text)

    ai_text = generate_response(user_text, history, SYSTEM_PROMPTS[round_name])
    history.append({"user": user_text, "assistant": ai_text})

    audio_path = await synthesize_speech(ai_text)
    if not audio_path or not os.path.exists(audio_path):
        print("[ERROR] Failed to synthesize audio.")
        return JSONResponse({"response": ai_text, "audio_path": None})

    return JSONResponse({"response": ai_text, "audio_path": "/" + audio_path})

@app.get("/evaluate")
async def evaluate():
    eval_prompt = "Evaluate the candidate's performance in each round (Communication, Technical, HR). Mention key strengths and improvement areas."
    combined = ""
    for rnd in round_sequence:
        for ex in conversation_log[rnd]:
            combined += f"User: {ex['user']}\nAI: {ex['assistant']}\n"
    result = generate_response(combined, [], eval_prompt)
    return JSONResponse({"summary": result})
