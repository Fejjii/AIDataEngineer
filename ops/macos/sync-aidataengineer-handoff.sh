#!/usr/bin/env bash
# Content-aware iCloud sync for AIDataEngineer handoff documents.
#
# Copies ONLY HANDOFF.md and CHANGELOG_SESSION.md from the repository to the
# iCloud mirror. Never copies the repository, .git, secrets, source, virtualenvs,
# caches, or build output. Skips identical files so timestamps are not rewritten.
# Copies atomically (temp + rename), preserves source mtime, and verifies the
# destination by SHA256 + cmp. Returns nonzero on verification failure.
set -euo pipefail

SRC_DIR="/Users/hallo/Developer/AIDataEngineer"
DEST_DIR="/Users/hallo/Library/Mobile Documents/com~apple~CloudDocs/AI-Projects/AIDataEngineer"
FILES=("HANDOFF.md" "CHANGELOG_SESSION.md")

log()  { printf '[sync-aidataengineer] %s\n' "$*"; }
err()  { printf '[sync-aidataengineer][ERROR] %s\n' "$*" >&2; }

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    /usr/bin/openssl dgst -sha256 "$1" | awk '{print $NF}'
  fi
}

if [[ ! -d "$SRC_DIR" ]]; then
  err "source repository not found: $SRC_DIR"
  exit 1
fi

if ! mkdir -p "$DEST_DIR"; then
  err "cannot create destination directory: $DEST_DIR"
  exit 1
fi

status=0
copied=0
skipped=0

for name in "${FILES[@]}"; do
  src="$SRC_DIR/$name"
  dest="$DEST_DIR/$name"

  if [[ ! -f "$src" ]]; then
    err "source file missing, skipping: $src"
    status=1
    continue
  fi

  src_hash="$(sha256_of "$src")"

  if [[ -f "$dest" ]]; then
    dest_hash="$(sha256_of "$dest")"
    if [[ "$src_hash" == "$dest_hash" ]]; then
      log "unchanged, skip: $name"
      skipped=$((skipped + 1))
      continue
    fi
  fi

  tmp="$(mktemp "$DEST_DIR/.$name.XXXXXX")" || { err "mktemp failed for $name"; status=1; continue; }
  if ! cp -p "$src" "$tmp"; then
    err "copy failed: $src -> $tmp"
    rm -f "$tmp"
    status=1
    continue
  fi
  chmod 0644 "$tmp"
  touch -r "$src" "$tmp"

  if ! mv -f "$tmp" "$dest"; then
    err "atomic rename failed: $tmp -> $dest"
    rm -f "$tmp"
    status=1
    continue
  fi

  dest_hash="$(sha256_of "$dest")"
  if [[ "$src_hash" != "$dest_hash" ]]; then
    err "SHA256 mismatch after copy for $name (src=$src_hash dest=$dest_hash)"
    status=1
    continue
  fi
  if ! cmp -s "$src" "$dest"; then
    err "cmp mismatch after copy for $name"
    status=1
    continue
  fi

  log "synced + verified: $name ($src_hash)"
  copied=$((copied + 1))
done

log "done: copied=$copied skipped=$skipped"
if [[ "$status" -ne 0 ]]; then
  err "one or more files failed to sync/verify"
fi
exit "$status"
