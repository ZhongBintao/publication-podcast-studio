#!/usr/bin/env python3
import base64
import json
import os
import pathlib
import urllib.error
import urllib.request
import wave


ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "google-tts-test"
OUT.mkdir(parents=True, exist_ok=True)


def load_dotenv(path: pathlib.Path):
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


env = load_dotenv(ROOT / ".env")
api_key = os.environ.get("GOOGLE_AI_STUDIO_API_KEY") or env.get("GOOGLE_AI_STUDIO_API_KEY")
if not api_key:
    raise SystemExit("GOOGLE_AI_STUDIO_API_KEY is not available")

prompt = """TTS the following relaxed, informed Chinese podcast conversation.
Make Speaker1 sound warm and curious, and Speaker2 sound calm and lightly amused.
Use natural conversational pacing, brief pauses, and clear Mandarin pronunciation.
Speaker1: 欢迎收听我们的测试节目。今天我们只用几十秒，听听这段对话能不能像两个主持人在聊天。
Speaker2: 如果声音自然、接话顺畅，那它就很适合拿来做我们后面的文章播客。
Speaker1: 重点不是把文章机械地念出来，而是先写好真正适合听的对话，再让模型负责表演。
Speaker2: 没错。那我们开始吧。"""

payload = {
    "model": "gemini-3.1-flash-tts-preview",
    "input": prompt,
    "response_format": {"type": "audio"},
    "generation_config": {
        "speech_config": [
            {"speaker": "Speaker1", "voice": "Aoede"},
            {"speaker": "Speaker2", "voice": "Charon"},
        ]
    },
}

request = urllib.request.Request(
    "https://generativelanguage.googleapis.com/v1beta/interactions",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    method="POST",
)

try:
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    raise SystemExit(f"HTTP {exc.code}: {detail}")

audio = body.get("output_audio", {}).get("data")
if not audio:
    # The Interactions API may return the audio block inside steps[].content[].
    for step in body.get("steps", []):
        for block in step.get("content", []):
            if block.get("type") == "audio" and block.get("data"):
                audio = block["data"]
                break
        if audio:
            break
if not audio:
    raise SystemExit("No output_audio.data in response: " + json.dumps(body)[:1000])

pcm = base64.b64decode(audio)
wav_path = OUT / "gemini-multispeaker-zh.wav"
with wave.open(str(wav_path), "wb") as wav_file:
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)
    wav_file.setframerate(24000)
    wav_file.writeframes(pcm)

(OUT / "response.json").write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {wav_path}")
print(f"PCM bytes: {len(pcm)}")
