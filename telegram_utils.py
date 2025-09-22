import requests
from pathlib import Path

class TelegramError(RuntimeError):
    pass

def _post(url: str, data=None, files=None):
    r = requests.post(url, data=data, files=files, timeout=30)
    if not r.ok:
        try:
            detail = r.json()
        except Exception:
            detail = {"text": r.text}
        raise TelegramError(f"{r.status_code} {r.reason} | {detail}")
    return r.json()

def send_text(bot_token: str, chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    return _post(url, data=data)

def send_document(bot_token: str, chat_id: str, file_path: Path, caption: str = ""):
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    with open(file_path, "rb") as f:
        files = {"document": (file_path.name, f, "text/plain")}
        data = {"chat_id": chat_id, "caption": caption}
        return _post(url, data=data, files=files)
