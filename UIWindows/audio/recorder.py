from typing import List

def record_pcm_realtime(duration: int = 5,
                       channels: int = 1,
                       rate: int = 16000,
                       chunk: int = 1024,
                       stop_event=None) -> bytes:
    try:
        import pyaudio
    except ImportError as exc:
        raise RuntimeError("未找到 PyAudio，请先安装：pip install pyaudio") from exc
    pa = pyaudio.PyAudio()
    try:
        stream = pa.open(format=pyaudio.paInt16,
                         channels=channels,
                         rate=rate,
                         input=True,
                         frames_per_buffer=chunk)
        frames: List[bytes] = []
        max_frames = int(rate / chunk * duration)
        for _ in range(max_frames):
            if stop_event and stop_event.is_set():
                break
            data = stream.read(chunk, exception_on_overflow=False)
            frames.append(data)
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
    audio_data = b''.join(frames)
    return audio_data
