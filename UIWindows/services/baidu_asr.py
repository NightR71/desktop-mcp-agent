import os
import json
import time
import base64
import requests

def get_access_token():
    url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {
        "grant_type": "client_credentials",
        "client_id": os.getenv("VOICE_API_KEY"),
        "client_secret": os.getenv("SECRET_API_KEY"),
    }
    if not params["client_id"] or not params["client_secret"]:
        return None
    try:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = requests.post(url, data=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token")
        return token if token else None
    except Exception:
        return None

def recognize_pcm(pcm_data: bytes, rate: int = 16000, channel: int = 1) -> str:
    token = get_access_token()
    if not token or str(token).strip().lower() == "none":
        raise RuntimeError("未能获取 access_token")
    url = "https://vop.baidu.com/pro_api"
    speech_b64 = base64.b64encode(pcm_data).decode("utf8")
    payload = {
        "format": "pcm",
        "rate": rate,
        "channel": channel,
        "cuid": "python_client",
        "dev_pid": 80001,
        "speech": speech_b64,
        "len": len(pcm_data),
        "token": token,
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    last_err = None
    for _ in range(2):
        try:
            resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("err_no") == 0:
                return data.get("result", [""])[0]
            last_err = RuntimeError(f"百度语音识别错误: {data}")
        except requests.RequestException as e:
            last_err = RuntimeError(f"网络错误: {str(e)}")
        except Exception as e:
            last_err = RuntimeError(f"识别异常: {str(e)}")
        time.sleep(0.6)
    if last_err:
        raise last_err
    raise RuntimeError("识别失败")
