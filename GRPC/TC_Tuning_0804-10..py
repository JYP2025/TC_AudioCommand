"""
🎬 TC_Tuning_0804-11_tricaster_fixed.py
TriCaster 연동 개선 버전 (GET 방식 + named_input)
"""

import tkinter as tk
import customtkinter as ctk
import threading
import queue
import time
import os
import pyttsx3
import requests
from six.moves import queue as six_queue
from google.cloud import speech
import pyaudio

TRICASTER_IP = "172.30.20.6"
TRICASTER_URL = f"http://{TRICASTER_IP}/v1/shortcut"

TRICASTER_INPUT_MAP = {
    "1": "input1", "2": "input2", "3": "input3", "4": "input4",
    "5": "input5", "6": "input6", "7": "input7", "8": "input8",
    "p1": "input9", "p2": "input10", "m1": "input13", "m2": "input14"
}

PHONETIC_MAP = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "p one": "p1", "p 1": "p1", "p two": "p2", "p 2": "p2",
    "m one": "m1", "m 1": "m1", "m two": "m2", "m 2": "m2",
    "cut cut": "cut", "cut mix": "cut", "cup": "cut", "c": "cut",
    "1 cup": "1 cut", "to cut": "2 cut", "for cut": "4 cut",
    "quart": "cut", "court": "cut", "pit 2 cut": "p2 cut",
    "pick 2 cut": "p2 cut", "p to cut": "p2 cut"
}

# 상태 변수
initialized = False
stt_ready = False
stt_thread = None
stt_stop_event = threading.Event()
last_command = ""
last_command_time = 0
should_stop = False
current_program = "input1"
current_preview = "input2"
first_input_received = True

print(f"[INIT] 초기 상태 설정 → PGM: {current_program}, PVW: {current_preview}")

def speak_message(text):
    try:
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    except RuntimeError:
        pass

def stop_program():
    global should_stop, stt_thread, stt_stop_event
    should_stop = True
    print("🛑 시스템 종료 명령 수신")
    speak_message("시스템을 종료합니다.")
    stt_stop_event.set()
    def delayed_exit():
        time.sleep(0.5)
        os._exit(0)
    threading.Thread(target=delayed_exit, daemon=True).start()

# ✅ TriCaster 단축키 전송 (GET 방식 + named_input 지원)
def send_shortcut(name, value=None, app=None):
    try:
        if value is not None:
            response = requests.get(TRICASTER_URL, params={"name": name, "value": value}, timeout=1.5)
            log_msg = f"[TRICASTER] {name} = {value} 명령 전송됨"
        else:
            response = requests.get(TRICASTER_URL, params={"name": name}, timeout=1.5)
            log_msg = f"[TRICASTER] {name} 명령 전송됨"
        print(log_msg)
        if app:
            app.log(log_msg)
    except Exception as e:
        err = f"[TRICASTER ERROR] 명령 '{name}' 전송 실패: {e}"
        print(err)
        if app:
            app.log(err)

def countdown_log(app, seconds=3, on_complete=None):
    def run():
        print("[DEBUG] countdown_log() 쓰레드 진입")
        if app:
            app.log("[DEBUG] 안정화 카운트다운 시작")
        for i in range(seconds, 0, -1):
            msg = f"[안정화 대기 중] {i}초..."
            print(msg)
            if app:
                app.log(msg)
            time.sleep(1)
        if on_complete:
            on_complete()
    threading.Thread(target=run, daemon=True).start()

def reset_stt_stream(app=None):
    global stt_thread, stt_stop_event, stt_ready
    stt_ready = False
    if app:
        app.log("[STT] 세션 재시작 중...")
        app.set_status("STT 재시작 중...", "yellow")

    if stt_thread and stt_thread.is_alive():
        if threading.current_thread() != stt_thread:
            stt_stop_event.set()
            stt_thread.join()
        else:
            stt_stop_event.set()
    stt_stop_event.clear()
    start_stt_thread(app)
    stt_ready = True

    if app:
        app.set_status("🟢 STT 활성화", "green")
        app.log("[STT] 세션 재시작 완료. 명령어 인식을 다시 시작합니다.")

def execute_command_if_ready(command, app=None):
    global initialized, stt_ready, last_command, last_command_time
    now = time.time()
    if not command or command.strip() == "":
        return

    words = command.lower().split()
    original_phrase = ' '.join(words)
    normalized_command = PHONETIC_MAP.get(original_phrase, original_phrase)

    if normalized_command == original_phrase:
        normalized = [PHONETIC_MAP.get(w, w) for w in words]
        normalized_command = ' '.join(normalized).strip()

    if normalized_command.startswith("test"):
        normalized_command = "test"

    if normalized_command == "test":
        if not initialized:
            initialized = True
            stt_ready = True
            speak_message("STT 안정화 완료")
            print("[DEBUG] test 인식됨 → STT 안정화 완료 안내 출력")
            if app:
                app.set_status("🟢 STT 활성화", "green")
                app.log("[READY] STT 안정화 완료. 명령어 인식을 시작합니다.")
        else:
            if app:
                app.log("[TEST] 테스트 명령 인식됨 → 시스템 정상 작동 중")
        return

    if not stt_ready:
        print(f"[BLOCKED] STT 안정화 중: '{command}' 무시됨")
        if app:
            app.log(f"[BLOCKED] STT 안정화 중: 명령 '{command}' 무시됨")
        return

    if app:
        app.log(f"[DEBUG] 정규화 명령어: {normalized_command}")

    tokens = normalized_command.split()
    if len(tokens) == 2 and tokens[1] == "cut" and tokens[0] in TRICASTER_INPUT_MAP:
        pass
    elif len(tokens) >= 2:
        normalized_command = tokens[-1]
        if app:
            app.log(f"[DEBUG] 복합 명령어 → 마지막 명령만 유지: '{normalized_command}'")

    if len(normalized_command.split()) > 3:
        if app:
            app.log(f"[SKIP] 너무 긴 명령 무시됨: {normalized_command}")
        return

    if normalized_command == last_command and now - last_command_time < 0.25:
        if app:
            app.log(f"[SKIP] 너무 빠른 중복 명령 무시됨: {normalized_command}")
        return

    last_command = normalized_command
    last_command_time = now

    valid_cmds = list(TRICASTER_INPUT_MAP.keys()) + ["cut", "mix"]
    if not (normalized_command in valid_cmds or normalized_command.endswith("cut")):
        if app:
            app.log(f"[ERROR] 명령 '{normalized_command}' 인식 실패 → STT 리셋")
        reset_stt_stream(app)
        return

    process_command(normalized_command, app)

def process_command(command, app=None):
    global current_program, current_preview, first_input_received
    msg = f"[EXEC] 실행 명령어: {command}"
    print(msg)
    if app:
        app.log(msg)

    if command in TRICASTER_INPUT_MAP:
        selected_input = TRICASTER_INPUT_MAP[command]
        current_preview = selected_input
        send_shortcut("main_b_row_named_input", selected_input, app)
        if not first_input_received:
            current_program = selected_input
            first_input_received = True
            if app:
                app.log(f"[INITIAL] 프로그램/프리뷰 최초 설정됨: {selected_input}")
        if app:
            app.set_program(current_program)
            app.set_preview(current_preview)
            app.log(f"[PREVIEW] 설정됨 → PGM: {current_program}, PVW: {current_preview}")

    elif command.endswith("cut") and len(command.split()) == 2:
        cam_id = command.split()[0]
        if cam_id in TRICASTER_INPUT_MAP:
            selected_input = TRICASTER_INPUT_MAP[cam_id]
            send_shortcut("main_a_row_named_input", selected_input, app)
            current_program = selected_input
            if app:
                app.set_program(current_program)
                app.set_preview(current_preview)
                app.log(f"[QUICK CUT] 프로그램 전환됨: {current_program}")
                speak_message("컷 명령 수행됨")
            send_shortcut("main_take", app=app)

    elif command == "cut":
        current_program, current_preview = current_preview, current_program
        send_shortcut("main_take", app=app)
        if app:
            app.set_program(current_program)
            app.set_preview(current_preview)
            app.log(f"[CUT] 프로그램 전환됨 → PGM: {current_program}, PVW: {current_preview}")
            speak_message("컷 명령 수행됨")

    elif command == "mix":
        current_program, current_preview = current_preview, current_program
        send_shortcut("main_auto", app=app)
        if app:
            app.set_program(current_program)
            app.set_preview(current_preview)
            app.log(f"[MIX] 프로그램 전환됨 → PGM: {current_program}, PVW: {current_preview}")
            speak_message("믹스 명령 수행됨")

def start_stt_thread(app):
    global stt_thread, stt_stop_event
    RATE = 16000
    CHUNK = int(RATE / 10)

    def run_stt():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "C:/Users/JYP/Documents/GitHub/TC_AudioCommand/GRPC/my-key01.json"
        client = speech.SpeechClient()
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code="en-US",
        )
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            interim_results=False,
        )

        while not should_stop:
            print("🎙️ [INFO] STT 스트리밍 시작")
            start_time = time.time()
            stt_stop_event.clear()

            with MicrophoneStream(RATE, CHUNK) as stream:
                audio_generator = stream.generator()
                requests_gen = (speech.StreamingRecognizeRequest(audio_content=chunk) for chunk in audio_generator)
                responses = client.streaming_recognize(streaming_config, requests_gen)

                try:
                    for response in responses:
                        if stt_stop_event.is_set():
                            print("🔁 [INFO] STT 쓰레드 종료 요청 감지됨 → 종료")
                            return

                        if not response.results:
                            continue
                        result = response.results[0]
                        if not result.alternatives:
                            continue
                        transcript = result.alternatives[0].transcript.strip()
                        transcript = ' '.join(transcript.split())

                        if transcript == "":
                            continue

                        msg = f"🎧 [DEBUG] 전체 STT 인식 결과: '{transcript}'"
                        print(msg)
                        app.log(msg)

                        execute_command_if_ready(transcript, app=app)

                        if "stop" in transcript.lower():
                            stop_program()
                            return

                        if time.time() - start_time > 290:
                            print("🔁 [INFO] STT 세션 갱신 중...")
                            break
                except Exception as e:
                    print(f"❗[ERROR] STT 예외 발생: {e}")
                    reset_stt_stream(app)
                    continue

    stt_thread = threading.Thread(target=run_stt, daemon=True)
    stt_thread.start()

class MicrophoneStream:
    def __init__(self, rate, chunk):
        self._rate = rate
        self._chunk = chunk
        self._buff = six_queue.Queue()
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
            data = [chunk]
            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except six_queue.Empty:
                    break
            yield b"".join(data)

class DashboardApp:
    def __init__(self, root):
        self.root = root
        root.title("AI 스위쳐 대호야")
        root.geometry("650x500")

        self.label_header = ctk.CTkLabel(root, text="AI 스위쳐 대호야", text_color="white", font=("Arial", 36, "bold"))
        self.label_header.pack(pady=(10, 5))

        self.label_status = ctk.CTkLabel(root, text="STT 상태: 대기 중", text_color="white", font=("Arial", 24))
        self.label_status.pack(pady=10)

        self.label_program = ctk.CTkLabel(root, text=f"Program: {current_program}", text_color="white", font=("Arial", 22))
        self.label_program.pack(pady=5)

        self.label_preview = ctk.CTkLabel(root, text=f"Preview: {current_preview}", text_color="white", font=("Arial", 22))
        self.label_preview.pack(pady=5)

        self.text_log = ctk.CTkTextbox(root, width=600, height=250)
        self.text_log.pack(pady=10)
        self.text_log.insert(tk.END, "[대시보드 시작됨]\n")

        self.button_stop = ctk.CTkButton(root, text="🛑 시스템 종료", fg_color="red")
        self.button_stop.pack(pady=10)

        self.log_queue = queue.Queue()
        self.update_gui()

    def update_gui(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get()
            self.text_log.insert(tk.END, msg + "\n")
            self.text_log.see(tk.END)
        self.root.after(200, self.update_gui)

    def log(self, message):
        self.log_queue.put(message)

    def set_status(self, text, color="white"):
        self.label_status.configure(text=f"STT 상태: {text}", text_color=color)

    def set_program(self, name):
        self.label_program.configure(text=f"Program: {name}")

    def set_preview(self, name):
        self.label_preview.configure(text=f"Preview: {name}")

def main(test_mode=False):
    global stt_thread, stt_stop_event, stt_ready
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    app = DashboardApp(root)

    def on_button_stop():
        app.log("[MANUAL] 버튼을 통한 시스템 종료")
        stop_program()
    app.button_stop.configure(command=on_button_stop)

    def start_flow():
        speak_message("AI 스위쳐 대호야를 시작합니다.")
        countdown_log(app, seconds=3, on_complete=after_countdown)

    def after_countdown():
        speak_message("테스트라고 말하세요.")
        time.sleep(0.3)
        app.set_status("🟢 테스트 대기 중", "green")
        app.log("[INFO] 'test' 명령 인식 대기 중...")
        global stt_ready
        stt_ready = True
        print("[DEBUG] stt_ready = True → 'test' 허용 시작")

    start_stt_thread(app)
    root.after(1000, start_flow)
    root.mainloop()

if __name__ == "__main__":
    main(test_mode=False)
