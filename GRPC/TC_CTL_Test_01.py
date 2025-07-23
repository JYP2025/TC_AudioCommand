import os
import pyaudio
from six.moves import queue
from google.cloud import speech
import requests

# ✅ Google 인증 키 경로 설정
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "C:/Users/JYP/Documents/GitHub/TC_AudioCommand/GRPC/my-key01.json"

# 📡 TriCaster 설정
TRICASTER_IP = "172.30.20.6"
INPUT_MAP = {
    "1": "input1", "2": "input2", "3": "input3", "4": "input4",
    "5": "input5", "6": "input6", "7": "input7", "8": "input8",
    "9": "input9", "10": "input10",
    "m1": "input13", "m2": "input14",
    "p1": "input11", "p2": "input12",
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
                return
            yield chunk

# 🧠 간단한 발음 보정
phonetic_map = {
    "one": "1", "two": "2", "too": "2", "to": "2", "three": "3", "tree": "3",
    "four": "4", "for": "4", "fo": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10",
    "m one": "m1", "m1": "m1", "m two": "m2", "m2": "m2",
    "p one": "p1", "p1": "p1", "p two": "p2", "p2": "p2",
}

def normalize_command(text):
    compact = text.replace(" ", "").lower()
    return phonetic_map.get(compact, compact)

# 📡 TriCaster CUT
def send_tricaster_cut(input_key):
    input_name = INPUT_MAP.get(input_key)
    if not input_name:
        print(f"❌ 잘못된 입력: {input_key}")
        return
    try:
        # 바로 컷 전환
        requests.get(f"http://{TRICASTER_IP}/v1/shortcut", params={"name": "main_b_row_named_input", "value": input_name})
        requests.get(f"http://{TRICASTER_IP}/v1/shortcut", params={"name": "main_take"})
        print(f"✂️ TriCaster CUT → {input_name}")
    except Exception as e:
        print(f"🚨 전송 실패: {e}")

# 🎤 STT 루프
def listen_print_loop(responses):
    for response in responses:
        if not response.results:
            continue
        result = response.results[0]
        if not result.alternatives:
            continue

        transcript = result.alternatives[0].transcript.strip()
        if transcript == "":
            continue

        if result.is_final:
            print(f"✅ Final: {transcript}")
            if transcript.lower() == "stop":
                print("👋 종료 명령 수신")
                break

            cmd = normalize_command(transcript)
            send_tricaster_cut(cmd)

# 🚀 메인 실행
def main():
    client = speech.SpeechClient()
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code="en-US"
    )
    streaming_config = speech.StreamingRecognitionConfig(
        config=config,
        interim_results=True,
    )

    with MicrophoneStream(RATE, CHUNK) as stream:
        audio_generator = stream.generator()
        requests_gen = (
            speech.StreamingRecognizeRequest(audio_content=content)
            for content in audio_generator
        )
        responses = client.streaming_recognize(streaming_config, requests_gen)
        print("🎙️ 음성 인식 대기 중... (명령 후 'stop'으로 종료)")
        listen_print_loop(responses)

if __name__ == "__main__":
    main()
