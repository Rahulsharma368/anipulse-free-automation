import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

import cloudinary
import cloudinary.uploader
import requests
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).parent
LINKS_FILE = ROOT / "videos.txt"
STATE_FILE = ROOT / "processed.json"
WORK = ROOT / "work"
WORK.mkdir(exist_ok=True)

def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing GitHub Actions secret: {name}")
    return value

def read_state():
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))

def read_links():
    if not LINKS_FILE.exists():
        raise FileNotFoundError("videos.txt not found.")
    links = []
    for raw in LINKS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("https://"):
            print(f"Skipping non-HTTPS line: {line[:80]}")
            continue
        if line not in links:
            links.append(line)
    return links

def link_id(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

def title_from_url(url):
    name = unquote(Path(urlparse(url).path).name)
    name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name)
    name = re.sub(r"[_-]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name or len(name) < 3:
        name = "Anime moment"
    return (name[:85] + " | Anime Shorts")[:100]

def download_file(url, dest, max_mb):
    with requests.get(url, stream=True, timeout=(20, 180)) as r:
        r.raise_for_status()
        total = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_mb * 1024 * 1024:
                    raise ValueError(f"Source is larger than {max_mb} MB.")
                f.write(chunk)
    return dest

def make_srt(video_path, srt_path):
    from faster_whisper import WhisperModel
    model = WhisperModel(os.getenv("WHISPER_MODEL", "tiny.en"), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(video_path), beam_size=1, vad_filter=True)
    def stamp(seconds):
        ms = int(seconds * 1000)
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"
    out = []
    for i, seg in enumerate(segments, 1):
        txt = (seg.text or "").strip()
        if txt:
            out += [str(i), f"{stamp(seg.start)} --> {stamp(seg.end)}", txt, ""]
    if not out:
        print("No speech detected; continuing without subtitles.")
        return None
    srt_path.write_text("\n".join(out), encoding="utf-8")
    return srt_path

def render_video(source, output, srt_path=None):
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    if srt_path:
        escaped = str(srt_path.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        style = "FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginV=130"
        vf += f",subtitles='{escaped}':force_style='{style}'"
    cmd = [
        "ffmpeg", "-y", "-i", str(source), "-vf", vf, "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-ar", "48000", "-movflags", "+faststart", "-shortest", str(output)
    ]
    subprocess.run(cmd, check=True)

def upload_cloudinary(video_path, public_id):
    cloudinary.config(
        cloud_name=required("CLOUDINARY_CLOUD_NAME"),
        api_key=required("CLOUDINARY_API_KEY"),
        api_secret=required("CLOUDINARY_API_SECRET"),
        secure=True
    )
    result = cloudinary.uploader.upload(
        str(video_path), resource_type="video", folder="anipulse",
        public_id=public_id, overwrite=True, unique_filename=False
    )
    return result["secure_url"]

def youtube_upload(video_path, title, caption):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    info = json.loads(required("YOUTUBE_TOKEN_JSON"))
    creds = Credentials.from_authorized_user_info(
        info, scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds.valid:
        raise RuntimeError("YouTube OAuth token invalid/expired. Generate a fresh token.")
    yt = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": title,
            "description": caption + "\n\n#Shorts #Anime",
            "categoryId": "24",
            "defaultLanguage": "en"
        },
        "status": {
            "privacyStatus": os.getenv("PRIVACY_STATUS", "unlisted"),
            "selfDeclaredMadeForKids": False
        }
    }
    req = yt.videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    )
    response = None
    while response is None:
        _, response = req.next_chunk()
    print("YouTube upload complete:", response.get("id"))
    return response.get("id")

def instagram_publish(public_url, caption):
    version = os.getenv("GRAPH_API_VERSION", "v23.0")
    base = f"https://graph.facebook.com/{version}"
    user_id = required("IG_USER_ID")
    token = required("IG_ACCESS_TOKEN")
    res = requests.post(
        f"{base}/{user_id}/media",
        data={
            "media_type": "REELS",
            "video_url": public_url,
            "caption": caption,
            "share_to_feed": "true",
            "access_token": token
        }, timeout=60
    )
    res.raise_for_status()
    container = res.json()["id"]
    deadline = time.time() + 420
    while time.time() < deadline:
        status_res = requests.get(
            f"{base}/{container}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=30
        )
        status_res.raise_for_status()
        status = status_res.json()
        print("Instagram processing:", status.get("status_code"), status.get("status", ""))
        if status.get("status_code") == "FINISHED":
            break
        if status.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram processing failed: {status}")
        time.sleep(15)
    else:
        raise TimeoutError("Instagram Reel processing timed out.")
    pub = requests.post(
        f"{base}/{user_id}/media_publish",
        data={"creation_id": container, "access_token": token},
        timeout=60
    )
    pub.raise_for_status()
    media_id = pub.json().get("id")
    print("Instagram published:", media_id)
    return media_id

def process_one(url, state):
    key = link_id(url)
    record = state.setdefault(key, {"url": url})
    title = title_from_url(url)
    caption = f"{title}\\n\\nFollow for more anime moments!\\n#anime #animeedit #animemoments #shorts"
    source = WORK / f"{key}_source.mp4"
    output = WORK / f"{key}_vertical.mp4"
    srt = WORK / f"{key}.srt"

    max_mb = int(os.getenv("MAX_VIDEO_MB", "95"))
    if not source.exists():
        download_file(url, source, max_mb)
    srt_path = None
    if os.getenv("TRANSCRIBE", "true").lower() == "true":
        srt_path = make_srt(source, srt)
    render_video(source, output, srt_path)
    if output.stat().st_size > max_mb * 1024 * 1024:
        raise RuntimeError(f"Rendered video exceeds {max_mb} MB. Use a shorter/smaller source.")

    if not record.get("cloudinary_url"):
        record["cloudinary_url"] = upload_cloudinary(output, key)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    if not record.get("youtube_id"):
        record["youtube_id"] = youtube_upload(output, title, caption)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    if not record.get("instagram_id"):
        record["instagram_id"] = instagram_publish(record["cloudinary_url"], caption)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    record["done"] = True
    record["completed_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print("Finished:", title)

def main():
    links = read_links()
    state = read_state()
    pending = [u for u in links if not state.get(link_id(u), {}).get("done")]
    if not pending:
        print("No new video links. Add more HTTPS MP4 links to videos.txt.")
        return
    # One clip per workflow run to stay within free runner time/usage.
    process_one(pending[0], state)

if __name__ == "__main__":
    main()
