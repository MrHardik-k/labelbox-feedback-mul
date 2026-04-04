"""
Test script: Find a working method to control Claude CLI from Python on Windows.

Tests:
1. ConPTY with cmd.exe (simple echo test)
2. ConPTY with Claude CLI (if test 1 passes)
3. pywinpty (if installed)
4. subprocess + os.pipe approach
"""

import ctypes
import ctypes.wintypes
import threading
import subprocess
import time
import os
import sys

kernel32 = ctypes.windll.kernel32

# ============================================================
# Full argtypes for ALL Windows APIs we use
# ============================================================

PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
EXTENDED_STARTUPINFO_PRESENT = 0x00080000

# Pipe
kernel32.CreatePipe.restype = ctypes.c_bool
kernel32.CreatePipe.argtypes = [
    ctypes.POINTER(ctypes.c_void_p),  # pReadHandle
    ctypes.POINTER(ctypes.c_void_p),  # pWriteHandle
    ctypes.c_void_p,                  # lpSecAttrs
    ctypes.c_uint32,                  # nSize
]

# Handle
kernel32.CloseHandle.restype = ctypes.c_bool
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

# ReadFile / WriteFile
kernel32.ReadFile.restype = ctypes.c_bool
kernel32.ReadFile.argtypes = [
    ctypes.c_void_p,                  # hFile
    ctypes.c_void_p,                  # lpBuffer
    ctypes.c_uint32,                  # nBytesToRead
    ctypes.POINTER(ctypes.c_ulong),   # lpBytesRead
    ctypes.c_void_p,                  # lpOverlapped
]

kernel32.WriteFile.restype = ctypes.c_bool
kernel32.WriteFile.argtypes = [
    ctypes.c_void_p,                  # hFile
    ctypes.c_void_p,                  # lpBuffer
    ctypes.c_uint32,                  # nBytesToWrite
    ctypes.POINTER(ctypes.c_ulong),   # lpBytesWritten
    ctypes.c_void_p,                  # lpOverlapped
]

# ConPTY
kernel32.CreatePseudoConsole.restype = ctypes.c_long
kernel32.CreatePseudoConsole.argtypes = [
    ctypes.c_uint32,                   # COORD packed
    ctypes.c_void_p,                   # hInput
    ctypes.c_void_p,                   # hOutput
    ctypes.c_uint32,                   # dwFlags
    ctypes.POINTER(ctypes.c_void_p),   # phPC
]

kernel32.ClosePseudoConsole.restype = None
kernel32.ClosePseudoConsole.argtypes = [ctypes.c_void_p]

kernel32.InitializeProcThreadAttributeList.restype = ctypes.c_bool
kernel32.InitializeProcThreadAttributeList.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_size_t),
]

kernel32.UpdateProcThreadAttribute.restype = ctypes.c_bool
kernel32.UpdateProcThreadAttribute.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t,
    ctypes.c_void_p, ctypes.c_size_t,
    ctypes.c_void_p, ctypes.c_void_p,
]

# CreateProcessW
kernel32.CreateProcessW.restype = ctypes.c_bool
kernel32.CreateProcessW.argtypes = [
    ctypes.c_wchar_p,    # lpApplicationName
    ctypes.c_wchar_p,    # lpCommandLine
    ctypes.c_void_p,     # lpProcessAttributes
    ctypes.c_void_p,     # lpThreadAttributes
    ctypes.c_bool,       # bInheritHandles
    ctypes.c_uint32,     # dwCreationFlags
    ctypes.c_void_p,     # lpEnvironment
    ctypes.c_wchar_p,    # lpCurrentDirectory
    ctypes.c_void_p,     # lpStartupInfo
    ctypes.c_void_p,     # lpProcessInformation
]

kernel32.TerminateProcess.restype = ctypes.c_bool
kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]


# ============================================================
# Structures
# ============================================================

class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", ctypes.c_uint),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.c_bool),
    ]

class STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint),
        ("lpReserved", ctypes.c_void_p),
        ("lpDesktop", ctypes.c_void_p),
        ("lpTitle", ctypes.c_void_p),
        ("dwX", ctypes.c_uint),
        ("dwY", ctypes.c_uint),
        ("dwXSize", ctypes.c_uint),
        ("dwYSize", ctypes.c_uint),
        ("dwXCountChars", ctypes.c_uint),
        ("dwYCountChars", ctypes.c_uint),
        ("dwFillAttribute", ctypes.c_uint),
        ("dwFlags", ctypes.c_uint),
        ("wShowWindow", ctypes.c_ushort),
        ("cbReserved2", ctypes.c_ushort),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p),
        ("hStdError", ctypes.c_void_p),
    ]

class STARTUPINFOEX(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", STARTUPINFO),
        ("lpAttributeList", ctypes.c_void_p),
    ]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", ctypes.c_uint),
        ("dwThreadId", ctypes.c_uint),
    ]


# ============================================================
# ConPTY Test
# ============================================================

def test_conpty(command, label, cwd=None, timeout=15, send_text=None):
    """Test ConPTY with a given command. Returns True if output is received."""
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"Command: {command}")
    print(f"{'='*60}")

    output_data = []
    output_lock = threading.Lock()
    running = True

    def reader_thread(hOutput):
        nonlocal running
        buf = ctypes.create_string_buffer(4096)
        n = ctypes.c_ulong()
        while running:
            ok = kernel32.ReadFile(
                ctypes.c_void_p(hOutput),
                buf, ctypes.c_uint32(4096), ctypes.byref(n), None
            )
            if not ok or n.value == 0:
                err = kernel32.GetLastError()
                if err == 109:  # ERROR_BROKEN_PIPE
                    print(f"  [Reader] Pipe broken (process ended)")
                    break
                time.sleep(0.05)
                continue
            text = buf.raw[:n.value].decode('utf-8', errors='replace')
            with output_lock:
                output_data.append(text)
            print(f"  [Output] {repr(text[:200])}")

    # Create pipes
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    sa.bInheritHandle = True

    hInputRead = ctypes.c_void_p()
    hInputWrite = ctypes.c_void_p()
    hOutputRead = ctypes.c_void_p()
    hOutputWrite = ctypes.c_void_p()

    kernel32.CreatePipe(ctypes.byref(hInputRead), ctypes.byref(hInputWrite), ctypes.byref(sa), 0)
    kernel32.CreatePipe(ctypes.byref(hOutputRead), ctypes.byref(hOutputWrite), ctypes.byref(sa), 0)

    print(f"  Pipe handles: inR={hInputRead.value}, inW={hInputWrite.value}, outR={hOutputRead.value}, outW={hOutputWrite.value}")

    # Create pseudo console
    coord = ctypes.c_uint32((120 & 0xFFFF) | ((40 & 0xFFFF) << 16))
    hPty = ctypes.c_void_p()
    hr = kernel32.CreatePseudoConsole(
        coord,
        ctypes.c_void_p(hInputRead.value),
        ctypes.c_void_p(hOutputWrite.value),
        ctypes.c_uint32(0),
        ctypes.byref(hPty)
    )
    print(f"  CreatePseudoConsole: hr=0x{hr & 0xFFFFFFFF:08X}, hPty={hPty.value}")
    if hr != 0:
        print(f"  FAILED! Cannot create pseudo console.")
        return False

    # Init attribute list
    attr_size = ctypes.c_size_t()
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attr_size))
    attr_buf = (ctypes.c_byte * attr_size.value)()
    attr_list = ctypes.cast(attr_buf, ctypes.c_void_p)
    kernel32.InitializeProcThreadAttributeList(attr_list, 1, 0, ctypes.byref(attr_size))

    hPty_ref = ctypes.c_void_p(hPty.value)
    ok = kernel32.UpdateProcThreadAttribute(
        attr_list, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
        ctypes.byref(hPty_ref), ctypes.sizeof(ctypes.c_void_p),
        None, None
    )
    print(f"  UpdateProcThreadAttribute: ok={ok}")

    # Startup info
    si = STARTUPINFOEX()
    si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEX)
    si.lpAttributeList = attr_list

    pi = PROCESS_INFORMATION()

    # Create process
    cmd_buf = ctypes.create_unicode_buffer(command)
    cwd_str = cwd or os.getcwd()

    success = kernel32.CreateProcessW(
        None, cmd_buf,
        None, None,
        False, EXTENDED_STARTUPINFO_PRESENT,
        None, cwd_str,
        ctypes.byref(si), ctypes.byref(pi)
    )
    print(f"  CreateProcessW: success={success}, PID={pi.dwProcessId}")
    if not success:
        err = kernel32.GetLastError()
        print(f"  FAILED! Error={err}")
        return False

    # Close pipe ends owned by ConPTY
    kernel32.CloseHandle(hInputRead)
    kernel32.CloseHandle(hOutputWrite)

    # Start reader
    rt = threading.Thread(target=reader_thread, args=(hOutputRead.value,), daemon=True)
    rt.start()

    # Wait for initial output
    print(f"  Waiting {timeout}s for output...")
    for i in range(timeout):
        time.sleep(1)
        with output_lock:
            if output_data:
                print(f"  ✓ Got output after {i+1}s!")
                break
    else:
        print(f"  ✗ No output after {timeout}s")

    # Send text if requested
    if send_text and output_data:
        print(f"  Sending: {repr(send_text)}")
        data = (send_text + "\r\n").encode('utf-8')
        written = ctypes.c_ulong()
        ok = kernel32.WriteFile(
            ctypes.c_void_p(hInputWrite.value),
            data, ctypes.c_uint32(len(data)),
            ctypes.byref(written), None
        )
        print(f"  WriteFile: ok={ok}, written={written.value}")
        time.sleep(5)
        print(f"  Output after send:")
        with output_lock:
            for chunk in output_data[-5:]:
                print(f"    {repr(chunk[:200])}")

    # Cleanup
    running = False
    kernel32.TerminateProcess(ctypes.c_void_p(pi.hProcess), 1)
    kernel32.CloseHandle(ctypes.c_void_p(pi.hProcess))
    kernel32.CloseHandle(ctypes.c_void_p(pi.hThread))
    kernel32.CloseHandle(ctypes.c_void_p(hInputWrite.value))
    kernel32.CloseHandle(ctypes.c_void_p(hOutputRead.value))
    kernel32.ClosePseudoConsole(ctypes.c_void_p(hPty.value))
    rt.join(timeout=2)

    with output_lock:
        got_output = len(output_data) > 0

    print(f"\n  RESULT: {'PASS ✓' if got_output else 'FAIL ✗'}")
    return got_output


# ============================================================
# pywinpty Test
# ============================================================

def test_pywinpty(command, label, cwd=None, timeout=15, send_text=None):
    """Test using pywinpty package."""
    print(f"\n{'='*60}")
    print(f"TEST: {label} (pywinpty)")
    print(f"{'='*60}")
    try:
        import winpty
        print(f"  pywinpty version: {winpty.__version__ if hasattr(winpty, '__version__') else 'unknown'}")
    except ImportError:
        print("  pywinpty NOT installed. Install with: pip install pywinpty")
        return False

    try:
        # Try newer API first
        if hasattr(winpty, 'PTY'):
            pty = winpty.PTY(120, 40)
            pty.spawn(command)
            print(f"  Spawned via winpty.PTY")

            print(f"  Waiting {timeout}s for output...")
            output = ""
            for i in range(timeout * 10):
                time.sleep(0.1)
                try:
                    data = pty.read(timeout=100)
                    if data:
                        output += data
                        print(f"  [Output] {repr(data[:200])}")
                except Exception:
                    pass
                if output:
                    print(f"  ✓ Got output!")
                    break

            if send_text and output:
                print(f"  Sending: {repr(send_text)}")
                pty.write(send_text + "\r\n")
                time.sleep(5)
                try:
                    data = pty.read(timeout=5000)
                    if data:
                        print(f"  [Response] {repr(data[:300])}")
                except Exception:
                    pass

            print(f"  RESULT: {'PASS ✓' if output else 'FAIL ✗'}")
            return bool(output)

        # Try PtyProcess API
        elif hasattr(winpty, 'PtyProcess'):
            proc = winpty.PtyProcess.spawn(command, cwd=cwd)
            print(f"  Spawned via PtyProcess")

            output = ""
            for i in range(timeout * 10):
                time.sleep(0.1)
                if proc.read_nonblocking(1024):
                    data = proc.read_nonblocking(4096)
                    output += data
                    print(f"  [Output] {repr(data[:200])}")
                    break

            print(f"  RESULT: {'PASS ✓' if output else 'FAIL ✗'}")
            return bool(output)

        else:
            print("  Unknown pywinpty API")
            return False

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    # Dynamically find Claude CLI
    import shutil as _shutil
    cli_js = _shutil.which("claude")
    if cli_js:
        npm_dir = os.path.dirname(cli_js)
        cli_js = os.path.join(npm_dir, "node_modules", "@anthropic-ai", "claude-code", "cli.js")
    if not cli_js or not os.path.exists(cli_js):
        raise FileNotFoundError(
            "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
        )

    EVAL_DIR = str(os.path.join(os.path.dirname(os.path.dirname(__file__)), "evaluation"))

    print("=" * 60)
    print("Claude PTY Control - Test Suite")
    print("=" * 60)
    print(f"eval dir: {EVAL_DIR}")
    print(f"cli.js: {cli_js}")
    print(f"cli.js exists: {os.path.exists(cli_js)}")

    results = {}

    # Test 1: ConPTY with simple cmd.exe echo
    results["conpty_echo"] = test_conpty(
        "cmd.exe /c echo HELLO_CONPTY && timeout /t 3",
        "ConPTY basic test (cmd.exe echo)",
        timeout=10
    )

    # Test 2: ConPTY with interactive cmd.exe
    if results["conpty_echo"]:
        results["conpty_cmd"] = test_conpty(
            "cmd.exe",
            "ConPTY interactive cmd.exe",
            timeout=10,
            send_text="echo PTY_WORKS"
        )
    else:
        results["conpty_cmd"] = False
        print("\n  Skipping interactive cmd.exe test (basic test failed)")

    # Test 3: ConPTY with Claude
    if results.get("conpty_cmd"):
        claude_cmd = f'cmd.exe /c node "{cli_js}" --model=opus --thinking=enabled'
        results["conpty_claude"] = test_conpty(
            claude_cmd,
            "ConPTY with Claude CLI",
            cwd=EVAL_DIR,
            timeout=30,
            send_text="Hello"
        )
    else:
        results["conpty_claude"] = False
        print("\n  Skipping Claude ConPTY test (cmd.exe test failed)")

    # Test 4: pywinpty with echo
    results["pywinpty_echo"] = test_pywinpty(
        "cmd.exe /c echo HELLO_WINPTY",
        "pywinpty basic test",
        timeout=10
    )

    # Test 5: pywinpty with Claude
    if results.get("pywinpty_echo"):
        claude_cmd = f'cmd.exe /c node "{cli_js}" --model=opus --thinking=enabled'
        results["pywinpty_claude"] = test_pywinpty(
            claude_cmd,
            "pywinpty with Claude CLI",
            cwd=EVAL_DIR,
            timeout=30,
            send_text="Hello"
        )

    # Summary
    print(f"\n\n{'='*60}")
    print("RESULTS SUMMARY")
    print(f"{'='*60}")
    for test, passed in results.items():
        status = "PASS ✓" if passed else "FAIL ✗"
        print(f"  {test:25s} : {status}")

    # Recommendation
    print(f"\n{'='*60}")
    print("RECOMMENDATION")
    print(f"{'='*60}")
    if results.get("conpty_claude"):
        print("  → Use ConPTY (all tests passed)")
    elif results.get("pywinpty_claude"):
        print("  → Use pywinpty (ConPTY failed, pywinpty works)")
    elif results.get("conpty_echo"):
        print("  → ConPTY works for basic commands but not Claude")
        print("  → Try: pip install pywinpty")
    elif results.get("pywinpty_echo"):
        print("  → pywinpty works for basic commands but not Claude")
    else:
        print("  → Neither ConPTY nor pywinpty works on this system")
        print("  → Fallback: use subprocess with CREATE_NEW_CONSOLE + pyautogui")
