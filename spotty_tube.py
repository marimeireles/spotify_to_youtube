#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import re
from typing import List, Optional, Tuple

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# ---- YouTube OAuth scopes ----
SCOPES = ["https://www.googleapis.com/auth/youtube"]

BAD_WORDS = {
    "remaster","remastered","anniversary","deluxe","expanded","bonus","reissue",
    "edition","original","mono","stereo","instrumental","re-recorded","rerecorded",
    "feat","featuring"
}

def squash_spaces(s: str) -> str:
    return " ".join(s.split())

def drop_junk_brackets(s: str) -> str:
    # remove (...) or [...] segments if they contain BAD_WORDS
    def repl(m):
        inside = (m.group(1) or m.group(2) or "").lower()
        return "" if any(w in inside for w in BAD_WORDS) else m.group(0)
    pat = re.compile(r"\(([^)]*)\)|\[([^\]]*)\]")
    prev = None
    cur = s
    while prev != cur:
        prev = cur
        cur = pat.sub(repl, cur)
    return cur

def drop_junk_suffix(s: str) -> str:
    # if trailing " - blah" and blah has bad words, drop it
    while True:
        m = re.search(r"[\s\-\/]+([^\/\-]+)$", s)
        if not m:
            return s
        tail = m.group(1).strip().lower()
        if any(w in tail for w in BAD_WORDS):
            s = s[:m.start()].rstrip()
        else:
            return s

def clean_tag(s: str) -> str:
    return squash_spaces(drop_junk_suffix(drop_junk_brackets(s))).strip()

def iso8601_duration_to_seconds(iso_dur: str) -> int:
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_dur)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h*3600 + mi*60 + s

def youtube_auth(client_secret_file: str = "client_secret.json", token_file: str = "yt_token.json"):
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)

def ensure_playlist(youtube, title: str, description: str = "") -> str:
    # Try to find an existing playlist with same title (avoid duplicates)
    pls = youtube.playlists().list(part="snippet,contentDetails", mine=True, maxResults=50).execute()
    for it in pls.get("items", []):
        if it["snippet"]["title"] == title:
            return it["id"]
    # Create new
    body = {
        "snippet": {"title": title, "description": description},
        "status": {"privacyStatus": "private"}
    }
    res = youtube.playlists().insert(part="snippet,status", body=body).execute()
    return res["id"]

def add_to_playlist(youtube, playlist_id: str, video_id: str) -> None:
    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }
    }
    youtube.playlistItems().insert(part="snippet", body=body).execute()

def choose_best_video(youtube, query: str, target_seconds: Optional[int], search_max: int) -> Optional[str]:
    """Search YouTube for query, then pick best candidate (closest duration; slight preference for official channels)."""
    try:
        sr = youtube.search().list(
            q=query, part="id,snippet", type="video", maxResults=min(search_max, 50)
        ).execute()
    except HttpError as e:
        print(f"Search error: {e}")
        return None

    items = sr.get("items", [])
    if not items:
        return None

    ids = ",".join(it["id"]["videoId"] for it in items)
    vd = youtube.videos().list(part="contentDetails,snippet", id=ids).execute()
    details = {v["id"]: v for v in vd.get("items", [])}

    def score(video_id: str):
        d = details.get(video_id)
        if not d:
            return (10**6, 0, 0)
        dur = iso8601_duration_to_seconds(d["contentDetails"]["duration"])
        diff = abs(dur - target_seconds) if target_seconds else 0
        ch = (d["snippet"]["channelTitle"] or "").lower()
        channel_bonus = -5 if ("topic" in ch or "official" in ch) else 0
        title_penalty = len(d["snippet"]["title"] or "")
        return (diff + channel_bonus, title_penalty, -dur)

    return min((it["id"]["videoId"] for it in items), key=score, default=None)

def get_spotify_tracks(
    playlist_url_or_id: str,
    client_id: str,
    client_secret: Optional[str],
    redirect_uri: str,
) -> List[Tuple[str, str, int]]:
    """
    Return list of (artist, title, duration_seconds).
    Uses Client Credentials if client_secret is provided; otherwise PKCE.
    """
    # Robustly extract the playlist ID:
    raw = playlist_url_or_id.strip()
    pid = None

    # If it looks like a URL, parse path; ignore query/fragment
    try:
        u = urlparse(raw)
        if u.scheme and u.netloc:
            # /playlist/<id>[/...]
            parts = [p for p in u.path.split("/") if p]
            if len(parts) >= 2 and parts[0] == "playlist":
                pid = parts[1]
    except Exception:
        pass

    # Fallbacks: spotify:playlist:<id> or bare id
    if not pid:
        m = re.search(r"(?:spotify:playlist:|playlist/)?([A-Za-z0-9]{22})", raw)
        if m:
            pid = m.group(1)

    if not pid:
        raise ValueError(f"Could not extract playlist ID from: {playlist_url_or_id}")

    # auth (same as before) …
    if client_secret:
        auth = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
    else:
        auth = SpotifyOAuth(
            client_id=client_id,
            client_secret=None,
            redirect_uri=redirect_uri,
            scope="playlist-read-private",
            open_browser=True,
            cache_path=".spotipy_cache",
            show_dialog=False,
        )
    sp = spotipy.Spotify(auth_manager=auth)

    tracks: List[Tuple[str, str, int]] = []
    results = sp.playlist_items(pid, additional_types=("track",), fields=None, market=None, limit=100, offset=0)
    while True:
        for it in results.get("items", []):
            t = it.get("track") or {}
            if not t or t.get("is_local"):
                continue
            name = t.get("name") or ""
            artists = ", ".join(a.get("name","") for a in (t.get("artists") or []))
            dur_ms = t.get("duration_ms") or 0
            if name and artists and dur_ms:
                tracks.append((clean_tag(artists), clean_tag(name), int(dur_ms // 1000)))
        if results.get("next"):
            results = sp.next(results)
        else:
            break
    return tracks

def main():
    ap = argparse.ArgumentParser(description="Spotify → YouTube URL resolver (and optional YouTube playlist creation)")
    ap.add_argument("--spotify-playlist", required=True, help="Spotify playlist URL or ID")
    ap.add_argument("--client-id", required=True, help="Spotify Client ID")
    ap.add_argument("--client-secret", help="Spotify Client Secret (omit to use PKCE)")
    ap.add_argument("--redirect-uri", default="http://localhost:9090/callback",
                    help="Redirect URI to register in Spotify app (used only for PKCE)")
    ap.add_argument("--yt-title", required=True, help="Target YouTube playlist title (ignored with --no-yt)")
    ap.add_argument("--search-max", type=int, default=8, help="Max YouTube search results to consider per track")
    ap.add_argument("--dry-run", action="store_true", help="Do not add to YouTube playlist; still writes URLs")
    ap.add_argument("--no-yt", action="store_true", help="Disable all YouTube playlist writes (resolve URLs only)")
    ap.add_argument("--urls-out", default="urls.txt", help="Path to write deduplicated URL list")
    ap.add_argument("--yt-client-json", default="client_secret.json", help="YouTube OAuth client file")
    ap.add_argument("--yt-token-json", default="yt_token.json", help="YouTube token cache file")
    args = ap.parse_args()

    # 1) Fetch tracks from Spotify
    tracks = get_spotify_tracks(args.spotify_playlist, args.client_id, args.client_secret, args.redirect_uri)
    print(f"Fetched {len(tracks)} tracks from Spotify")

    # 2) YouTube auth + (optional) playlist creation
    yt = youtube_auth(client_secret_file=args.yt_client_json, token_file=args.yt_token_json)
    playlist_id = None
    if not (args.dry_run or args.no_yt):
        playlist_id = ensure_playlist(yt, args.yt_title)

    # 3) Resolve each track; collect URLs; optionally add to playlist
    urls: List[str] = []
    successes = failures = 0

    for artist, title, secs in tracks:
        base_q = f"{artist} - {title}"
        vid = choose_best_video(yt, base_q, secs, args.search_max)

        if not vid:
            # Backoff: remove featuring/brackets
            stripped = re.sub(r"\b(feat\.?|featuring)\b.*", "", base_q, flags=re.IGNORECASE)
            stripped = re.sub(r"[\(\[\{].*?[\)\]\}]", "", stripped)
            stripped = squash_spaces(stripped)
            if stripped and stripped != base_q:
                vid = choose_best_video(yt, stripped, secs, args.search_max)

        if vid:
            url = f"https://www.youtube.com/watch?v={vid}"
            print(f"OK: {artist} - {title} → {url}")
            if url not in urls:
                urls.append(url)
            if playlist_id and not args.dry_run and not args.no_yt:
                try:
                    add_to_playlist(yt, playlist_id, vid)
                except HttpError as e:
                    print(f"Add failed (continuing): {e}")
                    failures += 1
            successes += 1
        else:
            print(f"MISS: {artist} - {title}")
            failures += 1

    # 4) Persist URL list
    with open(args.urls_out, "w", encoding="utf-8") as f:
        for u in urls:
            f.write(u + "\n")
    print(f"Wrote {len(urls)} URLs to {args.urls_out}")

    # 5) Summary
    print(f"Done. Success={successes}, Misses/Errors={failures}")
    if playlist_id and not (args.dry_run or args.no_yt):
        print(f"YouTube playlist: https://www.youtube.com/playlist?list={playlist_id}")

if __name__ == "__main__":
    main()
