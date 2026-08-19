#!/usr/bin/env bash
# publish-image.sh — zip, checksum and publish an ethoscope SD image
#
# Replaces the old manual dance (zip -> md5 -> upload to box.com -> make a share
# link -> hand-edit links.json -> redeploy). One command does the lot:
#
#   ./accessories/publish-image.sh 20260819_ethoscope000_pi3_pi4.img
#
# It compresses the image, checksums it, uploads it to the lab server, verifies
# the upload byte-for-byte, and only then drops a sidecar .json manifest next to
# it. The resource server (Docker/resource_server/pa_server.py) reads those
# sidecars live, so there is nothing to commit, pull or restart afterwards.
#
# Options:
#   --name NAME     Published name without extension. Default: /etc/sdimagename
#                   read out of the image (falls back to the file's basename).
#   --title TEXT    Human title shown on the resources page. Default: derived.
#   --sd-size SIZE  Card size the image is built for.       Default: 32Gb
#   --tested-on X   Media the image was tested on.          Default: SD
#   --level N       zip compression level 0-9.              Default: 6
#   --out-dir DIR   Where to write the .zip.                Default: next to the image
#   --prune N       After publishing, keep only the N newest images on the server.
#   --dry-run       Do everything local, print what would be uploaded, upload nothing.
#   --force-zip     Re-create the .zip even if an up-to-date one exists.
#
# A .img.zip can be passed instead of a .img to re-publish something already
# compressed. Run as a normal user: the upload uses YOUR ssh keys. Reading
# /etc/sdimagename out of the image needs no root (debugfs reads the ext4 at an
# offset); if that fails the script falls back to a sudo loop-mount.
#
# Destination is overridable with the environment:
#   ETHOSCOPE_PUBLISH_HOST  ssh host            (default ctb.gilest.ro)
#   ETHOSCOPE_PUBLISH_DIR   remote directory    (default /srv/http/ethoscope/images)
#   ETHOSCOPE_PUBLISH_URL   public base URL     (default https://repo.ethoscope.lab.gilest.ro/images)

set -euo pipefail

# --- config -----------------------------------------------------------------
REMOTE_HOST="${ETHOSCOPE_PUBLISH_HOST:-ctb.gilest.ro}"
REMOTE_DIR="${ETHOSCOPE_PUBLISH_DIR:-/srv/http/ethoscope/images}"
BASE_URL="${ETHOSCOPE_PUBLISH_URL:-https://repo.ethoscope.lab.gilest.ro/images}"
RESOURCE_URL="${ETHOSCOPE_RESOURCE_URL:-https://ethoscope-resources.lab.gilest.ro}"

NAME=""
TITLE=""
SD_SIZE="32Gb"
TESTED_ON="SD"
LEVEL=6
OUT_DIR=""
PRUNE=0
DRY_RUN=0
FORCE_ZIP=0
IMG=""

usage() { sed -n '2,34p' "$0"; exit "${1:-0}"; }

while (( $# )); do
  case "$1" in
    --name)      NAME="$2"; shift 2 ;;
    --title)     TITLE="$2"; shift 2 ;;
    --sd-size)   SD_SIZE="$2"; shift 2 ;;
    --tested-on) TESTED_ON="$2"; shift 2 ;;
    --level)     LEVEL="$2"; shift 2 ;;
    --out-dir)   OUT_DIR="$2"; shift 2 ;;
    --prune)     PRUNE="$2"; shift 2 ;;
    --dry-run)   DRY_RUN=1; shift ;;
    --force-zip) FORCE_ZIP=1; shift ;;
    -h|--help)   usage 0 ;;
    -*)          echo "Unknown flag: $1" >&2; usage 1 ;;
    *)           IMG="$1"; shift ;;
  esac
done

[[ -n "$IMG" ]] || { echo "No image given." >&2; usage 1; }
[[ -f "$IMG" ]] || { echo "Image not found: $IMG" >&2; exit 1; }
IMG=$(realpath "$IMG")

for t in zip md5sum rsync ssh; do
  command -v "$t" >/dev/null || { echo "ERROR: '$t' is required but not installed" >&2; exit 1; }
done

if [[ $EUID -eq 0 && -n "${SUDO_USER:-}" ]]; then
  echo "WARNING: running as root — rsync/ssh will use root's keys, not ${SUDO_USER}'s." >&2
fi

SUDO=""
(( EUID != 0 )) && SUDO="sudo"

# --- helpers ----------------------------------------------------------------

# Read a file out of the image's rootfs (partition 2) without mounting it.
# e2fsprogs understands the "image?offset=N" syntax, so no root is needed.
read_from_image() {
  local path="$1" table ss start off
  command -v sfdisk >/dev/null && command -v debugfs >/dev/null || return 1
  table=$(sfdisk -d "$IMG" 2>/dev/null) || return 1
  ss=$(printf '%s\n' "$table" | awk -F': *' '/^sector-size:/{print $2}')
  [[ -n "$ss" ]] || ss=512
  # second "start=" line is partition 2, the rootfs
  start=$(printf '%s\n' "$table" \
          | awk -F'start=' '/start=/{n++; if (n==2) {split($2,a,","); gsub(/[^0-9]/,"",a[1]); print a[1]; exit}}')
  [[ -n "$start" ]] || return 1
  off=$(( start * ss ))
  debugfs -R "cat $path" "${IMG}?offset=${off}" 2>/dev/null
}

# Fallback: mount the rootfs read-only under sudo and cat the file.
read_from_image_mounted() {
  local path="$1" loop mnt out
  loop=$($SUDO losetup -fP --show "$IMG") || return 1
  mnt=$(mktemp -d /tmp/ethoscope-publish.XXXXXX)
  if $SUDO mount -o ro "${loop}p2" "$mnt" 2>/dev/null; then
    out=$($SUDO cat "$mnt$path" 2>/dev/null) || true
    $SUDO umount "$mnt"
  fi
  rmdir "$mnt"
  $SUDO losetup -d "$loop"
  [[ -n "${out:-}" ]] && printf '%s' "$out"
}

# "20260819_ethoscope000_pi3_pi4" -> "pi3 pi4"
models_from_name() {
  local n="$1" tail models=""
  tail=$(printf '%s' "$n" | grep -oiE '(_pi[0-9]+)+$' || true)
  for m in ${tail//_/ }; do models+="${m,,} "; done
  printf '%s' "${models% }"
}

# "pi3 pi4" -> "Pi 3 / Pi 4"
pretty_models() {
  local out=""
  for m in $1; do out+="Pi ${m#pi} / "; done
  printf '%s' "${out% / }"
}

# "20260819_ethoscope000_pi3_pi4" -> "19 Aug 2026" (today if there is no date prefix)
date_from_name() {
  local n="$1"
  if [[ "$n" =~ ^([0-9]{4})([0-9]{2})([0-9]{2}) ]]; then
    date -d "${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}" '+%-d %b %Y' 2>/dev/null && return
  fi
  date '+%-d %b %Y'
}

json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# --- work out the published name --------------------------------------------
IS_ZIP=0
[[ "$IMG" == *.zip ]] && IS_ZIP=1

if [[ -z "$NAME" ]]; then
  if (( IS_ZIP )); then
    NAME=$(basename "$IMG"); NAME=${NAME%.zip}; NAME=${NAME%.img}
  else
    echo "==> Reading /etc/sdimagename from the image"
    NAME=$(read_from_image /etc/sdimagename || true)
    if [[ -z "$NAME" ]]; then
      echo "    debugfs could not read it; falling back to a loop mount (needs sudo)"
      NAME=$(read_from_image_mounted /etc/sdimagename || true)
    fi
    NAME=${NAME//$'\n'/}
    if [[ -z "$NAME" ]]; then
      NAME=$(basename "$IMG"); NAME=${NAME%.img}
      echo "    /etc/sdimagename unreadable — using the file name: $NAME"
    fi
    NAME=${NAME%.img}
  fi
fi

MODELS=$(models_from_name "$NAME")
IMG_DATE=$(date_from_name "$NAME")
ZIP_NAME="${NAME}.img.zip"

if [[ -z "$TITLE" ]]; then
  # "20260819_ethoscope000_pi3_pi4" -> "Ethoscope000 for Pi 3 / Pi 4"
  base=$(printf '%s' "$NAME" | sed -E 's/^[0-9]{8}_//; s/(_[Pp][Ii][0-9]+)+$//')
  base="${base^}"
  if [[ -n "$MODELS" ]]; then
    TITLE="$base for $(pretty_models "$MODELS")"
  else
    TITLE="$base"
  fi
fi

echo "==> Publishing"
printf '    source:    %s\n' "$IMG"
printf '    name:      %s\n' "$NAME"
printf '    title:     %s\n' "$TITLE"
printf '    models:    %s\n' "${MODELS:-<none detected>}"
printf '    date:      %s\n' "$IMG_DATE"
printf '    target:    %s:%s\n' "$REMOTE_HOST" "$REMOTE_DIR"

# --- compress ---------------------------------------------------------------
if (( IS_ZIP )); then
  ZIP="$IMG"
else
  [[ -n "$OUT_DIR" ]] || OUT_DIR=$(dirname "$IMG")
  mkdir -p "$OUT_DIR"
  ZIP="$OUT_DIR/$ZIP_NAME"
  if [[ -f "$ZIP" && "$ZIP" -nt "$IMG" && $FORCE_ZIP -eq 0 ]]; then
    echo "==> Reusing existing archive (newer than the image): $ZIP"
  else
    echo "==> Compressing to $ZIP (zip -$LEVEL, this takes a while)"
    tmpd=$(mktemp -d /tmp/ethoscope-zip.XXXXXX)
    ln -s "$IMG" "$tmpd/${NAME}.img"
    rm -f "$ZIP"
    ( cd "$tmpd" && zip "-$LEVEL" -j "$ZIP" "${NAME}.img" )
    rm -rf "$tmpd"
  fi
fi

SIZE_BYTES=$(stat -c%s "$ZIP")
SIZE_H=$(numfmt --to=iec --format='%.1f' "$SIZE_BYTES")
echo "==> Archive: $ZIP ($SIZE_H, $SIZE_BYTES bytes)"

echo "==> md5sum (local)"
MD5=$(md5sum "$ZIP" | cut -d' ' -f1)
echo "    $MD5"

# --- sidecar manifest -------------------------------------------------------
MODELS_JSON=""
for m in $MODELS; do MODELS_JSON+="\"$m\", "; done
MODELS_JSON="[${MODELS_JSON%, }]"

SIDECAR="${ZIP}.json"
cat > "$SIDECAR" <<JSON
{
    "title": "$(json_escape "$TITLE")",
    "filename": "$ZIP_NAME",
    "url": "$BASE_URL/$ZIP_NAME",
    "date": "$IMG_DATE",
    "md5sum": "$MD5",
    "SDsize": "$(json_escape "$SD_SIZE")",
    "tested_on": "$(json_escape "$TESTED_ON")",
    "size": "$SIZE_H",
    "size_bytes": $SIZE_BYTES,
    "models": $MODELS_JSON,
    "published": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
}
JSON
echo "==> Manifest: $SIDECAR"
sed 's/^/    /' "$SIDECAR"

if (( DRY_RUN )); then
  echo "==> --dry-run: stopping before upload."
  echo "    would upload: $ZIP  ->  $REMOTE_HOST:$REMOTE_DIR/$ZIP_NAME"
  echo "    would publish at: $BASE_URL/$ZIP_NAME"
  exit 0
fi

# --- upload -----------------------------------------------------------------
echo "==> Uploading to $REMOTE_HOST:$REMOTE_DIR (resumable; safe to interrupt)"
ssh "$REMOTE_HOST" "mkdir -p '$REMOTE_DIR'"
# --partial-dir keeps interrupted transfers out of the published name, so the
# file only appears under its final name once it is complete.
rsync -h --info=progress2 --chmod=F644 --partial-dir=.rsync-partial \
      "$ZIP" "$REMOTE_HOST:$REMOTE_DIR/$ZIP_NAME"

echo "==> Verifying the upload (md5sum on $REMOTE_HOST)"
REMOTE_MD5=$(ssh "$REMOTE_HOST" "md5sum '$REMOTE_DIR/$ZIP_NAME'" | cut -d' ' -f1)
if [[ "$REMOTE_MD5" != "$MD5" ]]; then
  echo "ERROR: checksum mismatch — local $MD5, remote $REMOTE_MD5" >&2
  echo "       the manifest was NOT published, so nothing points at the bad file." >&2
  echo "       re-run to resume/repair the upload." >&2
  exit 3
fi
echo "    OK: $REMOTE_MD5"

# Publish the manifest last: until it lands, the image is invisible to the
# resource server even if the upload was interrupted halfway.
echo "==> Publishing the manifest"
rsync -h --chmod=F644 "$SIDECAR" "$REMOTE_HOST:$REMOTE_DIR/${ZIP_NAME}.json"

# --- prune ------------------------------------------------------------------
if (( PRUNE > 0 )); then
  echo "==> Pruning: keeping the $PRUNE newest images on $REMOTE_HOST"
  # Names start with YYYYMMDD, so a reverse lexicographic sort is chronological.
  mapfile -t OLD < <(ssh "$REMOTE_HOST" \
    "ls -1 '$REMOTE_DIR' 2>/dev/null | grep -E '\.img\.zip\$' | sort -r | tail -n +$((PRUNE+1))")
  if (( ${#OLD[@]} == 0 )); then
    echo "    nothing to remove"
  else
    for f in "${OLD[@]}"; do
      echo "    removing $f"
      ssh "$REMOTE_HOST" "rm -f '$REMOTE_DIR/$f' '$REMOTE_DIR/$f.json'"
    done
  fi
fi

# --- done -------------------------------------------------------------------
echo "==> Published."
printf '    download:  %s/%s\n' "$BASE_URL" "$ZIP_NAME"
printf '    md5sum:    %s\n' "$MD5"
for m in $MODELS; do
  printf '    redirect:  %s/latest_sd_image/%s\n' "$RESOURCE_URL" "$m"
done
printf '    listing:   %s/resources\n' "$RESOURCE_URL"
