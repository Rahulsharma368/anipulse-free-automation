# AniPulse — link-only free-tier Shorts/Reels automation

## Add videos the easy way

Open `videos.txt` and paste **one direct, publicly accessible HTTPS MP4 URL per line**. No JSON editing and no title/caption/hashtag entry is needed.

Example:

```text
https://your-host.example/clip-one.mp4
https://your-host.example/clip-two.mp4
https://your-host.example/clip-three.mp4
```

Lines beginning with `#` and blank lines are ignored. Duplicate URLs in the file are ignored. The project generates a basic title from the video filename and a standard English caption. It does not use an AI text API.

## What happens

- Each scheduled GitHub Actions run processes the next unprocessed link (one video per run to limit free runner usage).
- Downloads the source MP4, creates 1080x1920 vertical video, and optionally transcribes English speech with local Whisper.
- Uploads the result to YouTube and publishes an Instagram Reel using Meta's API.
- Stores platform IDs in `processed.json`, so a successful platform is not uploaded again if the other platform fails.
- Runs on a schedule at 12:47 PM and 7:47 PM India time, subject to GitHub's schedule delays.

## Important requirements and limits

- Only add videos you own, have licensed, or have explicit permission to publish. The software does not discover, scrape, or download copyrighted anime episodes. Editing/subtitles do not grant copyright permission.
- This is free-tier automation, not unlimited free hosting. GitHub Actions has usage and scheduling limits; Cloudinary Free has monthly credit, storage, bandwidth and transformation limits. Check current plan limits before relying on it.
- Cloudinary is used to provide a public URL for Instagram to fetch. Meta's API requires a suitable Instagram Professional account, linked Meta setup, token and publishing permission.
- YouTube API OAuth setup is required. YouTube API access, quota and verification restrictions may apply.
- Video source must be a direct downloadable HTTPS MP4 URL, not a normal Google Drive/Dropbox share page. Keep source/output below the configured 95 MB cap.
- Whisper downloads a speech model during each fresh GitHub runner job; it can take time. If you don't need subtitles, change `TRANSCRIBE` to `"false"` in the workflow.
- Default YouTube privacy is `unlisted` for safer testing. Change `PRIVACY_STATUS` to `public` only after a successful test.
- GitHub scheduled workflows can be delayed. Public repositories with no activity for 60 days can have scheduled workflows disabled.

## Setup

### 1. GitHub

Create a GitHub repository. Upload all files and folders from this project. A public repository is eligible for free standard GitHub-hosted runner usage, subject to GitHub's current terms and limits.

### 2. Cloudinary

Create an account at https://cloudinary.com/users/register/free and copy Cloud Name, API Key and API Secret.

### 3. YouTube API

- Open https://console.cloud.google.com/
- Create a project and enable YouTube Data API v3.
- Configure OAuth consent screen.
- Create OAuth client credentials of type Desktop app and download JSON as `client_secrets.json`.
- On your own computer install dependencies (`pip install -r requirements.txt`), put `client_secrets.json` beside `get_youtube_token.py`, and run `python get_youtube_token.py`.
- Complete consent. Copy all contents of generated `token.json` into GitHub Actions secret `YOUTUBE_TOKEN_JSON`.
- Never commit `client_secrets.json` or `token.json`. If OAuth app remains in Testing, refresh token expiry restrictions may apply.

Official guide: https://developers.google.com/youtube/v3/guides/uploading_a_video

### 4. Instagram API

- Convert Instagram to a Creator or Business (Professional) account.
- Set up the Meta app and connect the Instagram account as required by Meta's current Instagram API setup.
- Enable the relevant content publishing permissions and generate an access token for your own account.
- Obtain the Instagram Professional account ID.

Official docs: https://developers.facebook.com/docs/instagram-platform/

### 5. Add GitHub secrets

Repository → Settings → Secrets and variables → Actions → New repository secret:

- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`
- `YOUTUBE_TOKEN_JSON`
- `IG_USER_ID`
- `IG_ACCESS_TOKEN`

Optional repository variable: `GRAPH_API_VERSION` (set to a currently supported Meta Graph API version; starter default is `v23.0`).

### 6. Add video links

Edit `videos.txt`, paste one direct HTTPS MP4 URL per line, save and commit. That's it. No JSON changes needed.

### 7. Test

Go to Actions → AniPulse link-based publisher → Run workflow. Check logs. The first run may take longer because Whisper downloads its model. Keep YouTube set to Unlisted until you have tested both platforms.

## Troubleshooting

- **Not a direct MP4:** URL must download the actual video file, not a preview/share webpage.
- **YouTube OAuth error:** regenerate token and update `YOUTUBE_TOKEN_JSON`; check API access and quota.
- **Instagram error:** check professional account, connected Meta setup, token expiry and content publishing permissions.
- **Cloudinary quota error:** reduce frequency/size or wait for monthly quota reset.
- **Whisper slow:** set `TRANSCRIBE` to `false` in workflow or supply pre-created subtitles (not yet supported through the simple link-only input).
- **Need to retry one failed clip:** inspect `processed.json`; successful platform IDs are preserved. Do not erase them unless you intentionally want to risk duplicate posting.

## Files

- `videos.txt` — only file you need to edit to add videos.
- `main.py` — automation code.
- `processed.json` — automatic upload history; do not edit normally.
- `.github/workflows/publish.yml` — scheduled GitHub Actions workflow.
- `get_youtube_token.py` — one-time YouTube OAuth helper.
