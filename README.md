# Vaultboy

Vaultboy is a local macOS utility that syncs project-level Obsidian vaults between a repository docs folder and the iCloud Obsidian location used by Obsidian iOS.

The UI is a mobile-first React/Vite interface using shadcn-style components and Tailwind CSS.

It only syncs the configured docs vault folder. It does not sync the whole repo.

## Correct iCloud Location

On iPhone, the vault must live here:

```text
iCloud Drive/Obsidian/<vault-name>
```

On macOS, that same location is:

```text
$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/<vault-name>
```

Do not use a plain iCloud Drive folder. Use the Obsidian folder with the Obsidian app icon.

## Install Dependencies

The root launcher creates `.venv`, installs Python dependencies, installs UI dependencies, and starts the app automatically if needed:

```bash
./vaultboy
```

Manual install:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
cd vaultboy_ui
npm install
npm run build
```

## Run Locally

```bash
./vaultboy
```

By default this runs development mode with Vite hot reload and FastAPI auto reload.

Use the Vite URL for code reloads. The API port redirects `/` to Vite in dev mode.

Default web UI:

```text
http://127.0.0.1:5173
```

Vaultboy binds to `0.0.0.0` by default so it is reachable from other devices on your local network.

Config is stored at `~/.vaultboy/config.json`, state at `~/.vaultboy/state/<project-name>/manifest.json`, and logs at `~/.vaultboy/logs/vaultboy.log`.

## Development Mode

For UI hot reload and FastAPI auto reload, run:

```bash
./vaultboy
```

Open the Vite dev UI:

```text
http://127.0.0.1:5173
```

The API still runs at `http://127.0.0.1:4567`, and Vite proxies `/api` requests to it.

If you open `http://127.0.0.1:4567` in dev mode, Vaultboy redirects you to `http://127.0.0.1:5173` so UI changes hot reload correctly.

For production mode, build the UI and serve it from FastAPI:

```bash
./vaultboy --prod
```

Production UI runs at:

```text
http://127.0.0.1:4567
```

## Access From iPhone

For same-network access in dev mode, open `http://<your-mac-lan-ip>:5173`.

For production mode, open `http://<your-mac-lan-ip>:4567`.

With Tailscale, open `http://<mac-tailscale-name>:4567` or use your Mac's Tailscale IP.

Vaultboy has no authentication in the MVP, so only expose it on trusted networks.

## Add First Project

Open the web UI and fill in:

```text
Project name: example-project
Repo docs path: /Users/me/Projects/example-project/docs
iCloud vault path: /Users/me/Library/Mobile Documents/iCloud~md~obsidian/Documents/example-project
Enabled: on
```

The repo docs path must already exist. Vaultboy creates the iCloud vault path if it is missing.

## Sync Modes

Pull copies from iCloud Obsidian to repo docs. Push copies from repo docs to iCloud Obsidian. Safe sync pulls first, then pushes. Dry run reports planned work without copying files.

Deletes are propagated by default. Vaultboy deletes an unchanged counterpart when a previously synced file is removed from the other side. Changed files are not deleted automatically. Set `propagateDeletes` to `false` for a project to keep deleted counterparts as skipped files instead.

## Conflict Handling

Vaultboy stores a per-project manifest at `~/.vaultboy/state/<project-name>/manifest.json`.

If both repo and iCloud versions changed since the last sync, Vaultboy keeps both versions and creates a conflict copy instead of overwriting either side blindly.

Conflict files use this format:

```text
original-name.conflict-YYYYMMDD-HHMMSS.md
```

Conflicts are logged and surfaced in the UI.

## Launchd Agent

Install the login agent without sudo:

```bash
./scripts/install-launchd.sh
```

Uninstall it:

```bash
./scripts/uninstall-launchd.sh
```

The agent runs `./vaultboy --prod` and writes launchd stdout/stderr to `~/.vaultboy/logs/`.

## Why iOS Is Not Always-On

iOS does not behave like a guaranteed always-on file sync daemon. Background execution, battery policy, network state, and iCloud scheduling can delay file propagation. Let iCloud finish syncing to the Mac before expecting Vaultboy to pull the latest edits.

## Git Source Of Truth

Git remains the source of truth for `repo/docs`. Vaultboy moves notes between iCloud Obsidian and the repo docs vault, but it does not replace `git diff`, code review, or commits.

Recommended workflow:

1. Edit notes on iPhone using Obsidian.
2. Let iCloud sync to Mac.
3. Vaultboy pulls changes into `repo/docs`.
4. Review `git diff`.
5. Commit docs changes.
6. Vaultboy pushes `repo/docs` back to iCloud when needed.

## Ignored Paths

Vaultboy ignores `.git`, `node_modules`, build folders, `dist`, `.next`, `target`, `.venv`, `__pycache__`, `.DS_Store`, and volatile Obsidian workspace/cache/plugin state.

## Known Limitations

The MVP has no database, no authentication, no file watcher, and no native iOS app. It uses periodic sync plus manual sync actions.
