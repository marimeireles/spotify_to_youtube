#!/usr/bin/env bash
set -Eeuo pipefail

usage() { echo "Usage: $0 <urls.txt> [output_dir]"; exit 1; }

URLS_FILE="${1:-}"; [[ -z "${URLS_FILE}" ]] && usage
OUTDIR="${2:-downloads}"

command -v yt-dlp >/dev/null || { echo "yt-dlp not found. Install it (e.g., 'pip install yt-dlp' or 'brew install yt-dlp')." >&2; exit 2; }
command -v ffmpeg >/dev/null || { echo "ffmpeg not found. Install it (e.g., 'brew install ffmpeg' or 'apt install ffmpeg')." >&2; exit 2; }

mkdir -p "$OUTDIR"
ARCHIVE="$OUTDIR/.downloaded.txt"
LOGFILE="$OUTDIR/download.log"

OPTS=(
  --ignore-errors
  --no-warnings
  --continue
  --no-overwrites
  --download-archive "$ARCHIVE"
  --add-metadata
  --embed-thumbnail
  -x --audio-format mp3
  -P "$OUTDIR"
  -o "%(title)s [%(id)s].%(ext)s"
)

echo "Starting downloads into: $OUTDIR"
echo "Logging to: $LOGFILE"
while IFS= read -r url; do
  [[ -z "$url" || "$url" =~ ^[[:space:]]*# ]] && continue
  echo "Downloading: $url"
  if ! yt-dlp "${OPTS[@]}" "$url" >>"$LOGFILE" 2>&1; then
    echo "Failed: $url (see $LOGFILE)" >&2
  fi
done < "$URLS_FILE"

echo "Done."
