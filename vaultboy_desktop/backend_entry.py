"""PyInstaller entry point for the bundled Vaultboy backend sidecar."""
import os
import sys
import threading

from vaultboy_app.app.main import run


def _exit_when_parent_dies() -> None:
    """Exit when stdin reaches EOF, i.e. the desktop app that spawned us is gone.

    The PyInstaller onefile bootloader is a separate parent process; killing it
    (which is what Tauri's child.kill() does) leaves this process orphaned, so
    the sidecar watches the stdin pipe from the desktop app instead. This also
    covers the desktop app being force-killed.
    """
    try:
        sys.stdin.buffer.read()
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)


if __name__ == "__main__":
    if os.environ.get("VAULTBOY_SIDECAR") == "1":
        threading.Thread(target=_exit_when_parent_dies, daemon=True).start()
    run()
