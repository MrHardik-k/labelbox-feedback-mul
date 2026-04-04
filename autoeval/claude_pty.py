"""
ClaudePTY - Controls Claude Code via a visible console window.
Uses subprocess.CREATE_NEW_CONSOLE to give Claude a real terminal,
pyautogui clipboard paste to send commands, and file-based monitoring for output.
"""

import subprocess
import threading
import time
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CLAUDE_INIT_WAIT, EVAL_FILE_POLL_INTERVAL

import pyautogui
import ctypes
import ctypes.wintypes


# Windows API for window management
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Disable pyautogui failsafe (mouse corner abort) for automation
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05


def get_all_visible_windows():
    """Get all visible top-level window handles with their titles and class names."""
    windows = []

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            # Get class name
            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            # Get title
            title_len = user32.GetWindowTextLengthW(hwnd)
            title_buf = ctypes.create_unicode_buffer(max(title_len + 1, 1))
            user32.GetWindowTextW(hwnd, title_buf, title_len + 1)
            if title_buf.value:  # Only windows with titles
                windows.append((hwnd, title_buf.value, class_buf.value))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return windows


# Terminal window class names (any of these indicate a terminal)
TERMINAL_CLASSES = {
    "ConsoleWindowClass",           # Legacy conhost.exe
    "CASCADIA_HOSTING_WINDOW_CLASS",  # Windows Terminal
    "PseudoConsoleWindow",          # Newer ConPTY
    "mintty",                       # Git Bash
    "VirtualConsoleClass",          # ConEmu
}


def bring_window_to_front(hwnd):
    """Bring a window to the foreground."""
    SW_RESTORE = 9
    SW_SHOW = 5
    user32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.2)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    # Double-check it's focused
    foreground = user32.GetForegroundWindow()
    if foreground != hwnd:
        # Try Alt trick to allow SetForegroundWindow
        pyautogui.press('alt')
        time.sleep(0.1)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)


def find_chrome_hwnd():
    """Find the main Chrome browser window handle."""
    windows = get_all_visible_windows()
    for hwnd, title, cls in windows:
        if cls == "Chrome_WidgetWin_1" and title and title != "":
            return hwnd
    return None


def minimize_window(hwnd):
    """Minimize a window so it doesn't stay in front."""
    SW_MINIMIZE = 6
    user32.ShowWindow(hwnd, SW_MINIMIZE)


def bring_chrome_to_front():
    """Bring Chrome browser window back to the foreground."""
    chrome_hwnd = find_chrome_hwnd()
    if chrome_hwnd:
        bring_window_to_front(chrome_hwnd)
    else:
        print("[Chrome] WARNING: Chrome window not found, cannot restore focus")


# ============================================================
# Claude Controller
# ============================================================

def create_subprocess_pty(cwd=None):
    """Create and start a Claude controller."""
    ctrl = ClaudeController(str(cwd) if cwd else os.getcwd())
    ctrl.start()
    return ctrl


class ClaudeController:
    """Controls Claude Code via a visible console window + pyautogui."""

    def __init__(self, cwd):
        self.cwd = cwd
        self.process = None
        self.hwnd = None
        self.running = False
        self._output = []
        self._lock = threading.Lock()

    def start(self):
        """Launch Claude Code in a new visible console window."""
        cli_js = r"C:\Users\Admin\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\cli.js"
        git_bash = r"D:\All Apps\Git\Git\bin\bash.exe"

        if not os.path.exists(cli_js):
            raise FileNotFoundError(f"Claude CLI not found: {cli_js}")

        env = os.environ.copy()
        if os.path.exists(git_bash):
            env["CLAUDE_CODE_GIT_BASH_PATH"] = git_bash

        # Snapshot existing window handles BEFORE launching
        existing_hwnds = set(hwnd for hwnd, _, _ in get_all_visible_windows())
        print(f"[Claude] Existing windows: {len(existing_hwnds)}")

        # Launch Claude in a NEW visible console window
        self.process = subprocess.Popen(
            ["node", cli_js, "--model=opus", "--thinking=enabled", "--dangerously-skip-permissions"],
            cwd=self.cwd,
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        self.running = True
        print(f"[Claude] Launched in new console (PID: {self.process.pid})")

        # Find the NEW window (one that didn't exist before)
        print("[Claude] Waiting for new terminal window...")
        for i in range(60):
            time.sleep(1)
            current_windows = get_all_visible_windows()
            new_windows = [(h, t, c) for h, t, c in current_windows if h not in existing_hwnds]

            if new_windows:
                # Prefer known terminal classes
                terminal_wins = [(h, t, c) for h, t, c in new_windows if c in TERMINAL_CLASSES]
                if terminal_wins:
                    self.hwnd = terminal_wins[0][0]
                    print(f"[Claude] Found terminal window after {i+1}s: '{terminal_wins[0][1]}' (class={terminal_wins[0][2]}, hwnd={self.hwnd})")
                else:
                    # Use first new window
                    self.hwnd = new_windows[0][0]
                    print(f"[Claude] Found new window after {i+1}s: '{new_windows[0][1]}' (class={new_windows[0][2]}, hwnd={self.hwnd})")
                # Immediately minimize the Claude window and restore Chrome
                minimize_window(self.hwnd)
                bring_chrome_to_front()
                break

            if i % 10 == 9:
                print(f"[Claude] Still waiting for new window... ({i+1}s)")
                print(f"  All windows: {len(current_windows)}, new: {len(new_windows)}")

        if not self.hwnd:
            print("[Claude] WARNING: Could not find new window")
            all_wins = get_all_visible_windows()
            for hwnd, title, cls in all_wins[:10]:
                print(f"  Window: hwnd={hwnd}, class={cls}, title='{title[:60]}'")
            return True

        # Wait for Claude to fully initialize its REPL
        print(f"[Claude] Waiting {CLAUDE_INIT_WAIT}s for Claude REPL to initialize...")
        time.sleep(CLAUDE_INIT_WAIT)
        print(f"[Claude] Ready (PID: {self.process.pid}, hwnd={self.hwnd})")
        return True

    def send(self, text):
        """Send a command to Claude using clipboard paste (always reliable)."""
        self.send_with_pyautogui(text)

    def send_with_pyautogui(self, text):
        """Send command using pyautogui clipboard paste."""
        if not self.hwnd:
            print("[Claude] ERROR: No window handle")
            return

        print(f"[Claude -> Window] Typing: {text[:100]}...")

        # Bring Claude's console window to front
        bring_window_to_front(self.hwnd)
        time.sleep(0.5)

        # Use clipboard paste for reliability (handles any characters)
        try:
            proc = subprocess.run(
                ['clip'],
                input=text.encode('utf-8'),
                check=True,
                timeout=5
            )
        except Exception as e:
            print(f"[Claude] Clipboard error: {e}, trying direct type...")
            pyautogui.typewrite(text, interval=0.02)
            pyautogui.press('enter')
            return

        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.3)
        pyautogui.press('enter')
        time.sleep(0.3)
        print(f"[Claude -> Window] Done ({len(text)} chars)")

        # Minimize Claude and bring Chrome back to front
        minimize_window(self.hwnd)
        bring_chrome_to_front()

    def clear_output(self):
        """Clear the output buffer."""
        with self._lock:
            self._output.clear()

    def wait_for(self, pattern, timeout=300):
        """Wait for completion by monitoring evaluation output files.
        Since we can't read the console output directly, we check
        if the expected output files have been created with content.
        """
        print(f"[Claude] Waiting for pattern: {pattern} (timeout={timeout}s)")

        output_dir = os.path.join(self.cwd, "output")

        # Map step patterns to their expected output files
        file_map = {
            "RULES LOADED": None,
            "EVAL DONE": "both_agent_compare.txt",
            "CLOSE_PREF DONE": "close_preference_reason.txt",
        }

        target_file = file_map.get(pattern)

        start = time.time()
        check = 0
        while time.time() - start < timeout:
            check += 1

            # Check if process is still running
            if self.process and self.process.poll() is not None:
                print(f"[Claude] Process exited with code {self.process.returncode}")
                return False

            # For RULES LOADED, just wait a fixed time (no file to check)
            if pattern == "RULES LOADED":
                time.sleep(min(30, timeout))
                return True

            # For step completions, check if the output file has content
            if target_file:
                fpath = os.path.join(output_dir, target_file)
                if os.path.exists(fpath):
                    try:
                        size = os.path.getsize(fpath)
                        if size > 10:
                            elapsed = time.time() - start
                            print(f"[Claude] {target_file} ready ({size} bytes, {elapsed:.0f}s)")
                            return True
                    except OSError:
                        pass

            if check % 6 == 0:
                elapsed = (time.time() - start) / 60
                print(f"  ... still waiting ({elapsed:.1f} min)")

            time.sleep(EVAL_FILE_POLL_INTERVAL)

        print(f"[Claude] Timeout waiting for: {pattern}")
        return False

    def is_running(self):
        if self.process:
            return self.process.poll() is None
        return False

    def stop(self):
        """Stop Claude."""
        self.running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=10)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            print("[Claude] Stopped")
