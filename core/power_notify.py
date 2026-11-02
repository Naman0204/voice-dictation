"""
core/power_notify.py
Windows power-state notifications. Registers PowerRegisterSuspendResumeNotification
with a callback so we're told when the system is about to SLEEP/HIBERNATE — and
can finalize an in-progress recording before the machine suspends (the callback
runs synchronously during the suspend sequence, so work done here completes
before sleep). All defensive; no-ops on non-Windows or if registration fails.
"""
import ctypes
import sys
from ctypes import wintypes

PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
_DEVICE_NOTIFY_CALLBACK = 2
_ERROR_SUCCESS = 0

# ULONG CALLBACK(PVOID Context, ULONG Type, PVOID Setting)
_CALLBACK = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p,
                               wintypes.ULONG, ctypes.c_void_p)


class _SubscribeParams(ctypes.Structure):
    _fields_ = [("Callback", _CALLBACK), ("Context", ctypes.c_void_p)]


class PowerNotifier:
    def __init__(self, on_suspend=None, on_resume=None):
        self._on_suspend = on_suspend
        self._on_resume = on_resume
        self._handle = ctypes.c_void_p()
        self._cb = _CALLBACK(self._dispatch)          # keep ref alive
        self._params = _SubscribeParams(self._cb, None)
        self._registered = False

    def is_registered(self) -> bool:
        return self._registered

    def _dispatch(self, context, ctype, setting):
        try:
            if ctype == PBT_APMSUSPEND and self._on_suspend:
                self._on_suspend()
            elif ctype in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC) and self._on_resume:
                self._on_resume()
        except Exception as e:
            print(f"[power] dispatch error: {e}")
        return _ERROR_SUCCESS

    def register(self):
        if sys.platform != "win32" or self._registered:
            return
        try:
            res = ctypes.windll.powrprof.PowerRegisterSuspendResumeNotification(
                _DEVICE_NOTIFY_CALLBACK,
                ctypes.byref(self._params),
                ctypes.byref(self._handle))
            self._registered = (res == _ERROR_SUCCESS)
        except Exception as e:
            print(f"[power] register failed: {e}")
            self._registered = False

    def unregister(self):
        if not self._registered:
            return
        try:
            ctypes.windll.powrprof.PowerUnregisterSuspendResumeNotification(self._handle)
        except Exception:
            pass
        self._registered = False
