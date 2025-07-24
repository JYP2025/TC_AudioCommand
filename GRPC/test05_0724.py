import os
import pyaudio
from six.moves import queue
from google.cloud import speech
import requests
import time
import threading
import re

# ✅ Google 인증 키 경로 설정
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "C:/Users/JYP/Documents/GitHub/TC_AudioCommand/GRPC/my-key01.json"

# 📡 TriCaster 설정
TRICASTER_IP = "172.30.20.6"
INPUT_MAP = {
    "1": "input1", "2": "input2", "3": "input3", "4": "input4",
    "5": "input5", "6": "input6", "7": "input7", "8": "input8",
    "p1": "input9", "p2": "input10",
    "m1": "input13", "m2": "input14",
}

# 🎧 오디오 설정
RATE = 16000
CHUNK = int(RATE / 10)


class MicrophoneStream:
    def __init__(self, rate, chunk):
        self._rate = rate
        self._chunk = chunk
        self._buff = queue.Queue()
        self.closed = True

    def __enter__(self):
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
            stream_callback=self._fill_buffer,
        )
        self.closed = False
        return self

    def __exit__(self, type, value, traceback):
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        self._buff.put(None)
        self._audio_interface.terminate()

    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self):
        while not self.closed:
            chunk = self._buff.get()
            if chunk is None:
                continue
            yield chunk

# 🧠 발음 보정 테이블
phonetic_map = {
    "one": "1", "two": "2", "too": "2", "to": "2", "three": "3", "tree": "3",
    "four": "4", "for": "4", "fo": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10",
    "mone": "m1", "m-one": "m1", "m1": "m1", "mtwo": "m2", "m2": "m2",
    "pone": "p1", "p1": "p1", "ptwo": "p2", "p2": "p2",
    "test": "test", "cut": "cut", "mix": "mix"
}

last_command = ""
last_command_time = 0
command_timeout = 1.5
last_preview_key = None
test_completed = False

def normalize_command(text):
    compact = text.replace(" ", "").lower()
    compact = re.sub(r'(\b\w+)\1+', r'\1', compact)
    compact = re.sub(r'(\w)\1+', r'\1', compact)
    return phonetic_map.get(compact, compact)

def remove_consecutive_duplicates(words):
    result = []
    prev = None
    for word in words:
        if word != prev:
            result.append(word)
            prev = word
    return result

# 📡 TriCaster 제어

def preview_input(input_key):
    global last_preview_key
    input_name = INPUT_MAP.get(input_key)
    if input_name:
        last_preview_key = input_key
        requests.get(f"http://{TRICASTER_IP}/v1/shortcut", params={"name": "main_b_row_named_input", "value": input_name})
        print(f"🎯 PREVIEW SET → {input_key} ({input_name})", flush=True)

def cut():
    requests.get(f"http://{TRICASTER_IP}/v1/shortcut", params={"name": "main_take"})
    print("✂️ CUT (Preview → Program)", flush=True)

def mix():
    requests.get(f"http://{TRICASTER_IP}/v1/shortcut", params={"name": "main_auto"})
    print("🎞️ MIX (Preview → Program)", flush=True)

def direct_cut(input_key):
    preview_input(input_key)
    cut()
    print(f"⚡ DIRECT CUT → {input_key} ({INPUT_MAP.get(input_key)})", flush=True)

# 🎤 음성 인식 루프

def listen_print_loop(client, streaming_config, stream):
    global last_command, test_completed, last_command_time, last_preview_key

    while True:
        audio_generator = stream.generator()
        requests_gen = (
            speech.StreamingRecognizeRequest(audio_content=content)
            for content in audio_generator
        )
        responses = client.streaming_recognize(streaming_config, requests_gen)

        try:
            for response in responses:
                if not response.results:
                    continue
                result = response.results[0]
                if not result.alternatives:
                    continue
                transcript = result.alternatives[0].transcript.strip()
                if transcript == "" or not result.is_final:
                    continue

                print(f"🎤 인식: {transcript}", flush=True)

                if not test_completed:
                    if normalize_command(transcript) == "test":
                        print("🟢 STT 안정화 완료. 명령어 인식을 시작합니다.", flush=True)
                        test_completed = True
                    continue

                raw_words = transcript.lower().split()
                normalized_words = [normalize_command(word) for word in raw_words if word.strip()]
                phrases = remove_consecutive_duplicates(normalized_words)

                current_time = time.time()

                for command in phrases:
                    if command == "stop":
                        print("👋 종료 명령 수신", flush=True)
                        return

                    if command.endswith("cut") and command != "cut":
                        key = command.replace("cut", "")
                        if key in INPUT_MAP:
                            direct_cut(key)
                            last_command = command
                            last_command_time = current_time
                        else:
                            print(f"🤖 인식 실패: {transcript}", flush=True)
                        continue

                    if command in INPUT_MAP:
                        preview_input(command)
                        last_command = command
                        last_command_time = current_time
                        continue

                    if command == "cut":
                        if last_preview_key:
                            cut()
                            print(f"⚡ DIRECT CUT → {last_preview_key} ({INPUT_MAP[last_preview_key]})", flush=True)
                        else:
                            print("⚠️ CUT 명령이 인식되었지만, 사전 PREVIEW 대상이 없습니다.", flush=True)
                        last_command = command
                        last_command_time = current_time
                        continue

                    if command == "mix":
                        mix()
                        last_command = command
                        last_command_time = current_time
                        continue

                    print(f"🤖 인식 실패: {transcript}", flush=True)

        except Exception as e:
            print(f"⚠️ 세션 오류 발생: {e}\n🔄 STT 세션을 재시작합니다...", flush=True)
            while not stream._buff.empty():
                try:
                    stream._buff.get_nowait()
                except queue.Empty:
                    break
            time.sleep(1)
            continue

# ⏱️ STT 초기화 타이머

def console_timer():
    print("AI 스위쳐 '대호야'를 시작합니다. (테스트 모드)", flush=True)
    print("🎙️ 'TEST'라고 말하세요.", flush=True)

# 🚀 메인 실행

def main():
    threading.Thread(target=console_timer).start()

    client = speech.SpeechClient()
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code="en-US"
    )
    streaming_config = speech.StreamingRecognitionConfig(
        config=config,
        interim_results=False,
    )

    with MicrophoneStream(RATE, CHUNK) as stream:
        listen_print_loop(client, streaming_config, stream)

if __name__ == "__main__":
    main()
