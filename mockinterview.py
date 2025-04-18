import os
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wavfile
import time
import pygame
from pydub import AudioSegment

USE_PYTTSX3 = False
USE_GTTS = False
USE_EDGE_TTS = True

if USE_PYTTSX3:
    import pyttsx3
if USE_GTTS:
    from gtts import gTTS
if USE_EDGE_TTS:
    import asyncio
    import edge_tts

from openai import OpenAI
client = OpenAI()

pygame.mixer.init()

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SIZE = 4096
SILENCE_THRESHOLD = 0.01
SILENCE_DURATION = 3.0

if USE_PYTTSX3:
    tts_engine = pyttsx3.init()
    tts_engine.setProperty('rate', 225)
    voices = tts_engine.getProperty('voices')
    for voice in voices:
        if "female" in voice.name.lower():
            tts_engine.setProperty('voice', voice.id)
            break

def record_audio():
    print("Listening... (start speaking)")
    audio_chunks = []
    silence_start = None
    recording = True

    def audio_callback(indata, frames, time_info, status):
        rms = np.sqrt(np.mean(indata**2))
        audio_chunks.append(indata.copy())

        print(".", end="", flush=True)  # Visual feedback

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
        input_device = sd.default.device[0]
        device_info = sd.query_devices(input_device, 'input')
        channels = device_info['max_input_channels']
        if channels < 1:
            print("No input channels found.")
            return None

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=channels, blocksize=BLOCK_SIZE,
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

def generate_response_with_prompt(text, history, system_prompt):
    messages = [{"role": "system", "content": system_prompt}]
    for exchange in history[-2:]:
        messages.append({"role": "user", "content": exchange["user"]})
        messages.append({"role": "assistant", "content": exchange["assistant"]})
    messages.append({"role": "user", "content": text})

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Response error: {e}")
        return "Could you repeat that, please?"

async def text_to_speech_edge(text):
    start_time = time.time()
    try:
        voice = "en-US-AriaNeural"
        communicate = edge_tts.Communicate(text, voice)
        temp_file = "temp_output.mp3"
        await communicate.save(temp_file)

        pygame.mixer.music.load(temp_file)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)

        pygame.mixer.music.unload()
        os.remove(temp_file)
        print(f"TTS time: {time.time() - start_time:.2f}s")
    except Exception as e:
        print(f"Edge TTS error: {e}")

def text_to_speech(text):
    if USE_PYTTSX3:
        tts_engine.say(text)
        tts_engine.runAndWait()
    elif USE_GTTS:
        try:
            tts = gTTS(text=text, lang='en', slow=False)
            temp_file = "temp_output.mp3"
            tts.save(temp_file)
            pygame.mixer.music.load(temp_file)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
            pygame.mixer.music.unload()
            os.remove(temp_file)
        except Exception as e:
            print(f"TTS error: {e}")
    elif USE_EDGE_TTS:
        asyncio.run(text_to_speech_edge(text))

def run_round(round_name, duration_seconds, system_prompt):
    print(f"\n=== {round_name} Round Started ({duration_seconds // 60} mins) ===")
    start_time = time.time()
    history = []

    welcome_msg = generate_response_with_prompt(
        text="Start this round by greeting the candidate and asking an opening question.",
        history=history,
        system_prompt=system_prompt
    )
    print(f"{round_name} Bot: {welcome_msg}")
    text_to_speech(welcome_msg)

    while time.time() - start_time < duration_seconds:
        audio_file = record_audio()
        if not audio_file:
            continue

        transcription = transcribe_audio(audio_file)
        os.remove(audio_file)
        if not transcription:
            continue

        print(f"You: {transcription}")
        response = generate_response_with_prompt(transcription, history, system_prompt)
        print(f"{round_name} Bot: {response}")

        history.append({"user": transcription, "assistant": response})
        if len(history) > 5:
            history.pop(0)

        text_to_speech(response)

COMMUNICATION_SYSTEM_PROMPT = (
    "You are a warm and conversational interviewer for a communication round. "
    "Start by welcoming the candidate with a friendly tone. Then ask engaging, global, open-ended topics "
    "like environment, AI in education, space exploration, or the future of work. Keep the tone informal but insightful."
)

TECHNICAL_SYSTEM_PROMPT = (
    "You're a technical interviewer with 10 years of experience in software development. "
    "Start the conversation by greeting the candidate and easing into technical topics like OOP, Python, DBMS, ML, etc. "
    "Follow up with relevant questions and assess the depth of understanding casually, not like a quiz."
)

HR_SYSTEM_PROMPT = (
    "You are a seasoned HR professional with a calm and encouraging demeanor. "
    "Start by making the candidate feel welcome and valued. Ask thoughtful HR and managerial questions "
    "such as 'tell me about a conflict you resolved', or 'what motivates you to lead a team'. "
    "Keep responses supportive and conversational."
)

def main():
    print("=== Mock Interview Assistant ===")
    print("Press Ctrl+C at any time to exit.\n")

    try:
        run_round("Communication", 1 * 60, COMMUNICATION_SYSTEM_PROMPT)
        run_round("Technical", 2 * 60, TECHNICAL_SYSTEM_PROMPT)
        run_round("Managerial & HR", 1 * 60, HR_SYSTEM_PROMPT)
        print("\n=== Interview Completed ===")
    except KeyboardInterrupt:
        print("\nInterview manually stopped.")

if __name__ == "__main__":
    main()
