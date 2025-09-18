# Setup

## A) Python environment

~~~bash
pip install --upgrade pip
pip install spotipy google-api-python-client google-auth-oauthlib requests
~~~

## B) Spotify credentials

Create a Spotify app at <https://developer.spotify.com/dashboard>.

## C) YouTube Data API credentials (OAuth)

1. Go to <https://console.cloud.google.com/>.
2. “APIs & Services” → “Library” → enable **YouTube Data API v3**.
3. “Credentials” → “Create Credentials” → **OAuth client ID** → Application type: **Desktop**.
4. Download the client configuration as `client_secret.json` and put it next to the script.
5. Make sure to add yourself in the allowed list: <https://console.cloud.google.com/auth/audience> → **Add users**.
6. You’ll be prompted by a browser the first time to authorize your Google account. The script caches a token in `yt_token.json` for subsequent runs.

---

# Usage

~~~bash
python spotty_tube.py \
  --spotify-playlist "SPOTIFY_URL_PLAYLIST" \
  --client-id "ID" \
  --client-secret "SECRET" \
  --yt-title "YT_PLAYLIST_NAME" \
  --urls-out YOUTUBE_URLS.TXT
~~~

~~~bash
./download_from_urls.sh YOUTUBE_URLS.TXT ./DIRECTORY_TO_SAVE_SONGS
~~~
