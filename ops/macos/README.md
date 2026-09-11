# macOS iCloud handoff sync

Development operating system only. Copies `HANDOFF.md` and `CHANGELOG_SESSION.md`
from `~/Developer/AIDataEngineer` to iCloud. Never copies `.git`, secrets, or source.

## Live install (this Mac)

```bash
install -m 0755 ops/macos/sync-aidataengineer-handoff.sh ~/.local/bin/sync-aidataengineer-handoff.sh
cp ops/macos/com.sofien.aidataengineer-handoff-sync.plist.example \
  ~/Library/LaunchAgents/com.sofien.aidataengineer-handoff-sync.plist
plutil -lint ~/Library/LaunchAgents/com.sofien.aidataengineer-handoff-sync.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.sofien.aidataengineer-handoff-sync.plist
```

If `launchctl bootstrap` is denied, load the agent from Terminal.app in an Aqua
session. Do not use sudo.

## Manual sync

```bash
~/.local/bin/sync-aidataengineer-handoff.sh
```

Destination:

`~/Library/Mobile Documents/com~apple~CloudDocs/AI-Projects/AIDataEngineer/`
