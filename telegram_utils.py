import requests
from pathlib import Path

def send_document(bot_token: str, chat_id: str, file_path: Path, caption: str = ""):
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    with open(file_path, "rb") as f:
        files = {"document": (file_path.name, f, "text/plain")}
        data = {"chat_id": chat_id, "caption": caption}
        r = requests.post(url, data=data, files=files, timeout=30)
    r.raise_for_status()
    return r.json()
