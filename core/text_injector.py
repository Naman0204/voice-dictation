"""
core/text_injector.py
Type text into whatever window currently has keyboard focus — for dictation into
apps with no native voice input (Discord, Gmail, …). Primary path is Win32
SendInput with KEYEVENTF_UNICODE (fast, reliable in Electron/browsers, full
unicode incl. emoji via surrogate pairs). Clipboard + Ctrl+V is the fallback.
All ctypes calls declare argtypes so nothing is truncated on 64-bit.
"""
import ctypes
import sys
import time
from ctypes import wintypes

ULONG_PTR = ctypes.c_size_t
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1
VK_BACK = 0x08
VK_CONTROL = 0x11
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class _MOUSEINPUT(ctypes.Structure):
    # Present ONLY so the union is sized by its largest member, making INPUT the
    # required 40 bytes on x64. SendInput silently drops events if cbSize is wrong.
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_user32 = None
if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
    _user32.SendInput.restype = wintypes.UINT
    _user32.GetForegroundWindow.restype = ctypes.c_void_p


def foreground_window():
    return _user32.GetForegroundWindow() if _user32 else None


def _utf16_units(ch):
    b = ch.encode("utf-16-le")
    return [int.from_bytes(b[i:i + 2], "little") for i in range(0, len(b), 2)]


def _key_unicode(unit, keyup):
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if keyup else 0)
    return _INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=_KEYBDINPUT(0, unit, flags, 0, 0)))


def _key_vk(vk, keyup):
    flags = KEYEVENTF_KEYUP if keyup else 0
    return _INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=_KEYBDINPUT(vk, 0, flags, 0, 0)))


def unicode_inputs(text):
    """Build (testable) the list of INPUT events that would type `text`."""
    inputs = []
    for ch in text:
        for unit in _utf16_units(ch):
            inputs.append(_key_unicode(unit, False))
            inputs.append(_key_unicode(unit, True))
    return inputs


def _send(inputs):
    if not inputs or _user32 is None:
        return 0
    arr = (_INPUT * len(inputs))(*inputs)
    return _user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))


def type_text(text, per_char_delay=0.0):
    """Type `text` into the focused window. Returns chars typed. (Char-by-char so
    a small jitter can be added; emoji handled via surrogate pairs.)"""
    if _user32 is None or not text:
        return 0
    if per_char_delay:
        for ch in text:
            _send(unicode_inputs(ch))
            time.sleep(per_char_delay)
    else:
        _send(unicode_inputs(text))
    return len(text)


def backspace(n):
    """Send n Backspaces (used to erase the stray trigger characters)."""
    if _user32 is None or n <= 0:
        return
    ev = []
    for _ in range(int(n)):
        ev.append(_key_vk(VK_BACK, False))
        ev.append(_key_vk(VK_BACK, True))
    _send(ev)


# ── clipboard paste fallback ─────────────────────────────────────────────────
def _set_clipboard(text):
    k32, u32 = ctypes.windll.kernel32, _user32
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    u32.SetClipboardData.restype = ctypes.c_void_p
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        data = (text + "\0").encode("utf-16-le")
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        ptr = k32.GlobalLock(h)
        ctypes.memmove(ptr, data, len(data))
        k32.GlobalUnlock(h)
        u32.SetClipboardData(CF_UNICODETEXT, h)
        return True
    finally:
        u32.CloseClipboard()


def paste_text(text):
    """Fallback: set the clipboard and send Ctrl+V. Does not restore the previous
    clipboard (documented tradeoff)."""
    if _user32 is None or not text:
        return False
    if not _set_clipboard(text):
        return False
    _send([_key_vk(VK_CONTROL, False), _key_vk(ord("V"), False),
           _key_vk(ord("V"), True), _key_vk(VK_CONTROL, True)])
    return True


def insert(text, method="type"):
    """Insert text by the configured method, with the other as fallback."""
    text = text or ""
    if not text:
        return True
    if method == "paste":
        return paste_text(text) or bool(type_text(text))
    return bool(type_text(text)) or paste_text(text)
