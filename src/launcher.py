from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# Windows constants

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
CREDUIWIN_GENERIC = 0x00000001
CRED_PACK_GENERIC_CREDENTIALS = 0x4
ERROR_NOT_FOUND = 1168
ERROR_CANCELLED = 1223

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_TERMINATE = 0x0001

MEM_COMMIT = 0x00001000
MEM_RESERVE = 0x00002000
MEM_RELEASE = 0x00008000
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READWRITE = 0x40

TH32CS_SNAPMODULE = 0x00000008
MAX_MODULE_NAME32 = 255
MAX_PATH_W = 260

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

WIZARD_CLASS = "Wizard Graphical Client"
TARGET_PREFIX = "SkyFall/account/"
DEFAULT_SERVER = "login.us.wizard101.com:12000"

# DLLs

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_credui = ctypes.WinDLL("credui", use_last_error=True)
_ole32 = ctypes.WinDLL("ole32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

# structures


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wt.DWORD), ("dwHighDateTime", wt.DWORD)]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wt.DWORD),
        ("Type", wt.DWORD),
        ("TargetName", wt.LPWSTR),
        ("Comment", wt.LPWSTR),
        ("LastWritten", FILETIME),
        ("CredentialBlobSize", wt.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wt.DWORD),
        ("AttributeCount", wt.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wt.LPWSTR),
        ("UserName", wt.LPWSTR),
    ]


class CREDUI_INFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hwndParent", wt.HWND),
        ("pszMessageText", wt.LPCWSTR),
        ("pszCaptionText", wt.LPCWSTR),
        ("hbmBanner", ctypes.c_void_p),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("th32ModuleID", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD),
        ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wt.DWORD),
        ("hModule", ctypes.c_void_p),
        ("szModule", ctypes.c_wchar * (MAX_MODULE_NAME32 + 1)),
        ("szExePath", ctypes.c_wchar * MAX_PATH_W),
    ]


# function prototypes (set restype/argtypes for 64-bit safety)

# kernel32
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.OpenProcess.restype = ctypes.c_void_p

_k32.CloseHandle.argtypes = [ctypes.c_void_p]
_k32.CloseHandle.restype = wt.BOOL

_k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_k32.TerminateProcess.restype = wt.BOOL

_k32.ReadProcessMemory.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
_k32.ReadProcessMemory.restype = wt.BOOL

_k32.WriteProcessMemory.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
_k32.WriteProcessMemory.restype = wt.BOOL

_k32.VirtualAllocEx.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    wt.DWORD,
    wt.DWORD,
]
_k32.VirtualAllocEx.restype = ctypes.c_void_p

_k32.VirtualFreeEx.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    wt.DWORD,
]
_k32.VirtualFreeEx.restype = wt.BOOL

_k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
_k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p

_k32.Module32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MODULEENTRY32W)]
_k32.Module32FirstW.restype = wt.BOOL

_k32.Module32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MODULEENTRY32W)]
_k32.Module32NextW.restype = wt.BOOL

# user32
_user32.GetClassNameW.argtypes = [ctypes.c_void_p, wt.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int

_user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.DWORD)]
_user32.GetWindowThreadProcessId.restype = wt.DWORD

_user32.IsWindow.argtypes = [ctypes.c_void_p]
_user32.IsWindow.restype = wt.BOOL

_user32.EnableWindow.argtypes = [ctypes.c_void_p, wt.BOOL]
_user32.EnableWindow.restype = wt.BOOL

_user32.GetForegroundWindow.argtypes = []
_user32.GetForegroundWindow.restype = ctypes.c_void_p

_WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, ctypes.c_void_p, ctypes.c_void_p)
_user32.EnumWindows.argtypes = [_WNDENUMPROC, ctypes.c_void_p]
_user32.EnumWindows.restype = wt.BOOL

# credui
_credui.CredUIPromptForWindowsCredentialsW.argtypes = [
    ctypes.POINTER(CREDUI_INFOW),
    wt.DWORD,
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(wt.BOOL),
    wt.DWORD,
]
_credui.CredUIPromptForWindowsCredentialsW.restype = wt.DWORD

_credui.CredUnPackAuthenticationBufferW.argtypes = [
    wt.DWORD,
    ctypes.c_void_p,
    wt.DWORD,
    wt.LPWSTR,
    ctypes.POINTER(wt.DWORD),
    wt.LPWSTR,
    ctypes.POINTER(wt.DWORD),
    wt.LPWSTR,
    ctypes.POINTER(wt.DWORD),
]
_credui.CredUnPackAuthenticationBufferW.restype = wt.BOOL

# ole32
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
_ole32.CoTaskMemFree.restype = None

# advapi32 - Credential Manager
_advapi32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wt.DWORD]
_advapi32.CredWriteW.restype = wt.BOOL

_advapi32.CredReadW.argtypes = [
    wt.LPCWSTR,
    wt.DWORD,
    wt.DWORD,
    ctypes.POINTER(ctypes.POINTER(CREDENTIALW)),
]
_advapi32.CredReadW.restype = wt.BOOL

_advapi32.CredDeleteW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD]
_advapi32.CredDeleteW.restype = wt.BOOL

_advapi32.CredEnumerateW.argtypes = [
    wt.LPCWSTR,
    wt.DWORD,
    ctypes.POINTER(wt.DWORD),
    ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(CREDENTIALW))),
]
_advapi32.CredEnumerateW.restype = wt.BOOL

_advapi32.CredFree.argtypes = [ctypes.c_void_p]
_advapi32.CredFree.restype = None

# metadata (JSON in %APPDATA%/SkyFall/account_metadata.json)


def _metadata_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA environment variable not set")
    d = Path(appdata) / "SkyFall"
    d.mkdir(parents=True, exist_ok=True)
    return d / "account_metadata.json"


def _load_meta() -> dict:
    p = _metadata_path()
    if not p.exists():
        return {"version": 1, "nicknames_order": [], "gid_map": {}}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Failed to read metadata: {e}")
    data.setdefault("version", 1)
    data.setdefault("nicknames_order", [])
    data.setdefault("gid_map", {})
    return data


def _save_meta(meta: dict) -> None:
    p = _metadata_path()
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except OSError as e:
        raise RuntimeError(f"Failed to write metadata: {e}")


# Credential storage (Windows Credential Manager via raw ctypes)
# uses ctypes (not pywin32) so the password blob is stored as raw UTF-8 bytes,
# matching the previous Rust extension's binary format. existing accounts
# saved by the Rust wizlaunch are read correctly


def _cred_target(nick: str) -> str:
    return f"{TARGET_PREFIX}{nick}"


def _cred_write(nick: str, username: str, password: str) -> None:
    target = _cred_target(nick)
    pwd_bytes = password.encode("utf-8")
    blob_arr = (
        (ctypes.c_ubyte * len(pwd_bytes)).from_buffer_copy(pwd_bytes)
        if pwd_bytes
        else None
    )

    cred = CREDENTIALW()
    cred.Flags = 0
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.Comment = None
    cred.CredentialBlobSize = len(pwd_bytes)
    cred.CredentialBlob = (
        ctypes.cast(blob_arr, ctypes.POINTER(ctypes.c_ubyte)) if blob_arr else None
    )
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.AttributeCount = 0
    cred.Attributes = None
    cred.TargetAlias = None
    cred.UserName = username

    if not _advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise RuntimeError(f"CredWriteW failed for '{nick}': {ctypes.get_last_error()}")
    # keep blob_arr alive until after the call
    del blob_arr


def _cred_read(nick: str) -> tuple[str, str]:
    target = _cred_target(nick)
    cred_pp = ctypes.POINTER(CREDENTIALW)()
    if not _advapi32.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(cred_pp)):
        raise RuntimeError(f"Credential not found: '{nick}'")
    try:
        cred = cred_pp.contents
        username = cred.UserName or ""
        size = cred.CredentialBlobSize
        if size > 0 and bool(cred.CredentialBlob):
            blob_arr = ctypes.cast(
                cred.CredentialBlob,
                ctypes.POINTER(ctypes.c_ubyte * size),
            ).contents
            password = bytes(blob_arr).decode("utf-8", errors="replace")
        else:
            password = ""
        return username, password
    finally:
        _advapi32.CredFree(cred_pp)


def _cred_delete(nick: str) -> None:
    target = _cred_target(nick)
    if not _advapi32.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
        raise RuntimeError(
            f"CredDeleteW failed for '{nick}': {ctypes.get_last_error()}"
        )


def _cred_list() -> list[str]:
    count = wt.DWORD(0)
    creds_ppp = ctypes.POINTER(ctypes.POINTER(CREDENTIALW))()
    filter_w = f"{TARGET_PREFIX}*"
    ok = _advapi32.CredEnumerateW(
        filter_w, 0, ctypes.byref(count), ctypes.byref(creds_ppp)
    )
    if not ok:
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return []
        raise RuntimeError(f"CredEnumerateW failed: {err}")
    try:
        out: list[str] = []
        for i in range(count.value):
            cred = creds_ppp[i].contents
            target = cred.TargetName or ""
            if target.startswith(TARGET_PREFIX):
                out.append(target[len(TARGET_PREFIX) :])
        return out
    finally:
        _advapi32.CredFree(creds_ppp)


def _cred_has(nick: str) -> bool:
    try:
        _cred_read(nick)
        return True
    except RuntimeError:
        return False


# CredUI dialog (OS-owned credential prompt)


def _prompt_credentials(caption: str, message: Optional[str] = None) -> tuple[str, str]:
    ui = CREDUI_INFOW()
    ui.cbSize = ctypes.sizeof(CREDUI_INFOW)
    ui.hwndParent = _user32.GetForegroundWindow()
    ui.pszMessageText = message
    ui.pszCaptionText = caption
    ui.hbmBanner = None

    auth_pkg = ctypes.c_ulong(0)
    out_buf = ctypes.c_void_p(0)
    out_buf_size = ctypes.c_ulong(0)

    rc = _credui.CredUIPromptForWindowsCredentialsW(
        ctypes.byref(ui),
        0,
        ctypes.byref(auth_pkg),
        None,
        0,
        ctypes.byref(out_buf),
        ctypes.byref(out_buf_size),
        None,
        CREDUIWIN_GENERIC,
    )
    if rc == ERROR_CANCELLED:
        raise RuntimeError("User cancelled credential dialog")
    if rc != 0:
        raise RuntimeError(f"CredUIPromptForWindowsCredentialsW returned {rc}")
    if not out_buf.value or out_buf_size.value == 0:
        raise RuntimeError("CredUI returned empty buffer")

    MAX_FIELD = 512
    user_buf = ctypes.create_unicode_buffer(MAX_FIELD)
    domain_buf = ctypes.create_unicode_buffer(MAX_FIELD)
    pass_buf = ctypes.create_unicode_buffer(MAX_FIELD)
    user_sz = wt.DWORD(MAX_FIELD)
    domain_sz = wt.DWORD(MAX_FIELD)
    pass_sz = wt.DWORD(MAX_FIELD)

    try:
        ok = _credui.CredUnPackAuthenticationBufferW(
            CRED_PACK_GENERIC_CREDENTIALS,
            out_buf,
            out_buf_size,
            user_buf,
            ctypes.byref(user_sz),
            domain_buf,
            ctypes.byref(domain_sz),
            pass_buf,
            ctypes.byref(pass_sz),
        )
        if not ok:
            raise RuntimeError(
                f"CredUnPackAuthenticationBufferW failed: {ctypes.get_last_error()}"
            )
        return user_buf.value, pass_buf.value
    finally:
        # best-effort wipe of password buffer
        ctypes.memset(pass_buf, 0, ctypes.sizeof(pass_buf))
        _ole32.CoTaskMemFree(out_buf)


# window / process utilities


def _get_wizard_handles() -> list[int]:
    handles: list[int] = []

    @_WNDENUMPROC
    def _cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(64)
        n = _user32.GetClassNameW(hwnd, buf, 64)
        if n > 0 and buf.value == WIZARD_CLASS:
            handles.append(hwnd)
        return True

    _user32.EnumWindows(_cb, None)
    return handles


def _wait_for_new_handle(before: set[int], timeout_secs: int) -> int:
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        for h in _get_wizard_handles():
            if h not in before:
                return h
        time.sleep(0.5)
    raise RuntimeError("No new wizard window detected (launch timeout)")


def _enable_window(hwnd: int, enable: bool) -> None:
    _user32.EnableWindow(hwnd, 1 if enable else 0)


def _is_window_valid(hwnd: int) -> bool:
    return bool(_user32.IsWindow(hwnd))


def _get_pid_from_hwnd(hwnd: int) -> int:
    pid = wt.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _kill_process_by_handle(hwnd: int) -> bool:
    pid = _get_pid_from_hwnd(hwnd)
    if pid == 0:
        return False
    handle = _k32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        raise RuntimeError(f"OpenProcess failed: {ctypes.get_last_error()}")
    try:
        return bool(_k32.TerminateProcess(handle, 1))
    finally:
        _k32.CloseHandle(handle)


# game launch


def _launch_game(game_path: str, login_server: str) -> None:
    bin_dir = Path(game_path) / "Bin"
    exe = bin_dir / "WizardGraphicalClient.exe"
    if not exe.exists():
        raise RuntimeError(f"Executable not found: {exe}")
    host, sep, port = login_server.rpartition(":")
    if not sep or not host or not port:
        raise RuntimeError(f"Invalid login server '{login_server}', expected host:port")
    try:
        subprocess.Popen(
            [str(exe), "-L", host, port, "-FRAMERATECAP:240"],
            cwd=str(bin_dir),
            close_fds=True,
        )
    except OSError as e:
        raise RuntimeError(f"Failed to launch game: {e}")


# login injection

# pattern to locate the game's internal command dispatcher
# matches: mov r9b,1 / xor r8d,r8d / lea rdx,[rbp-59h] / mov rcx,[rip+??]
_LOGIN_PATTERN = bytes(
    [
        0x41,
        0xB1,
        0x01,
        0x45,
        0x33,
        0xC0,
        0x48,
        0x8D,
        0x55,
        0xA7,
        0x48,
        0x8B,
        0x0D,
    ]
)

# RootWindowHook injection point: 7? | 48 8B 01 | 7? | FF 50 70 84
_HOOK_PATTERN: list[Optional[int]] = [
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    0x48,
    0x8B,
    0x01,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    0xFF,
    0x50,
    0x70,
    0x84,
]
_HOOK_INSTR_LEN = 7


def _scan_exact(data: bytes, pattern: bytes) -> Optional[int]:
    idx = data.find(pattern)
    return idx if idx != -1 else None


def _scan_wild(data: bytes, pattern: list) -> Optional[int]:
    plen = len(pattern)
    end = len(data) - plen
    # use first concrete byte to skip ahead quickly
    first_concrete_idx = next((i for i, p in enumerate(pattern) if p is not None), 0)
    first_byte = pattern[first_concrete_idx]
    i = 0
    while i <= end:
        # quick filter on first concrete byte
        if data[i + first_concrete_idx] != first_byte:
            i += 1
            continue
        match = True
        for j, p in enumerate(pattern):
            if p is not None and data[i + j] != p:
                match = False
                break
        if match:
            return i
        i += 1
    return None


class _RemoteProcess:
    def __init__(self, pid: int):
        access = (
            PROCESS_VM_OPERATION
            | PROCESS_VM_READ
            | PROCESS_VM_WRITE
            | PROCESS_QUERY_INFORMATION
        )
        self._handle = _k32.OpenProcess(access, False, pid)
        if not self._handle:
            raise RuntimeError(f"OpenProcess({pid}) failed: {ctypes.get_last_error()}")

    def close(self) -> None:
        if self._handle:
            _k32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def read(self, addr: int, size: int) -> bytes:
        buf = (ctypes.c_ubyte * size)()
        nread = ctypes.c_size_t(0)
        ok = _k32.ReadProcessMemory(
            self._handle,
            ctypes.c_void_p(addr),
            buf,
            size,
            ctypes.byref(nread),
        )
        if not ok:
            raise RuntimeError(
                f"ReadProcessMemory @ {addr:#x} failed: {ctypes.get_last_error()}"
            )
        return bytes(buf[: nread.value])

    def write(self, addr: int, data: bytes) -> None:
        size = len(data)
        buf = (ctypes.c_ubyte * size).from_buffer_copy(data)
        nwritten = ctypes.c_size_t(0)
        ok = _k32.WriteProcessMemory(
            self._handle,
            ctypes.c_void_p(addr),
            buf,
            size,
            ctypes.byref(nwritten),
        )
        if not ok:
            raise RuntimeError(
                f"WriteProcessMemory @ {addr:#x} failed: {ctypes.get_last_error()}"
            )

    def alloc(self, size: int, executable: bool = False) -> int:
        protect = PAGE_EXECUTE_READWRITE if executable else PAGE_READWRITE
        ptr = _k32.VirtualAllocEx(
            self._handle,
            None,
            size,
            MEM_COMMIT | MEM_RESERVE,
            protect,
        )
        if not ptr:
            raise RuntimeError(f"VirtualAllocEx failed: {ctypes.get_last_error()}")
        return ptr

    def alloc_near(self, near: int, size: int) -> int:
        granularity = 0x10000
        max_range = 0x7FFF_0000
        offset = granularity
        while offset < max_range:
            for sign in (1, -1):
                candidate = near + sign * offset
                if candidate <= 0:
                    continue
                candidate &= ~(granularity - 1)
                ptr = _k32.VirtualAllocEx(
                    self._handle,
                    ctypes.c_void_p(candidate),
                    size,
                    MEM_COMMIT | MEM_RESERVE,
                    PAGE_EXECUTE_READWRITE,
                )
                if ptr:
                    return ptr
            offset += granularity
        raise RuntimeError("Failed to allocate executable memory within jump range")

    def free(self, addr: int) -> None:
        _k32.VirtualFreeEx(self._handle, ctypes.c_void_p(addr), 0, MEM_RELEASE)


def _find_module(pid: int, name: str) -> tuple[int, int]:
    name_lower = name.lower()
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid)
    if not snap or snap == INVALID_HANDLE_VALUE:
        raise RuntimeError(
            f"CreateToolhelp32Snapshot failed: {ctypes.get_last_error()}"
        )
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
        if _k32.Module32FirstW(snap, ctypes.byref(entry)):
            while True:
                if entry.szModule.lower() == name_lower:
                    return entry.modBaseAddr, entry.modBaseSize
                if not _k32.Module32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        _k32.CloseHandle(snap)
    raise RuntimeError(f"Module '{name}' not found in process {pid}")


def _build_string_struct(data_addr: int, length: int) -> bytes:
    ss = bytearray(32)
    struct.pack_into("<Q", ss, 0, data_addr)
    struct.pack_into("<Q", ss, 16, length)
    struct.pack_into("<Q", ss, 24, length)
    return bytes(ss)


def _build_login_bytecode(
    block_addr: int,
    flag_addr: int,
    string_struct_addr: int,
    dat_addr: int,
    func_addr: int,
    orig_instr: bytes,
    ret_addr: int,
) -> bytes:
    bc = bytearray()

    # check flag
    bc += b"\x50"  # push rax
    bc += b"\x48\xb8" + struct.pack("<Q", flag_addr)  # mov rax, flag_addr
    bc += b"\x80\x38\x01"  # cmp byte [rax], 1
    bc += b"\x58"  # pop rax
    bc += b"\x0f\x85"  # jne rel32 (placeholder)
    skip_fixup = len(bc)
    bc += b"\x00\x00\x00\x00"

    # login body (only when flag == 1)
    bc += b"\x50\x51\x52\x41\x50\x41\x51\x41\x52\x41\x53"  # push rax,rcx,rdx,r8,r9,r10,r11
    bc += b"\x48\x83\xec\x28"  # sub rsp, 0x28
    bc += b"\x41\xb1\x01"  # mov r9b, 1
    bc += b"\x45\x33\xc0"  # xor r8d, r8d
    bc += b"\x48\xba" + struct.pack("<Q", string_struct_addr)  # mov rdx, &str_struct
    bc += b"\x48\xb8" + struct.pack("<Q", dat_addr)  # mov rax, &dat
    bc += b"\x48\x8b\x08"  # mov rcx, [rax]
    bc += b"\x48\xb8" + struct.pack("<Q", func_addr)  # mov rax, func
    bc += b"\xff\xd0"  # call rax
    bc += b"\x48\xb8" + struct.pack("<Q", flag_addr)  # mov rax, &flag
    bc += b"\xc6\x00\x00"  # mov byte [rax], 0
    bc += b"\x48\x83\xc4\x28"  # add rsp, 0x28
    bc += b"\x41\x5b\x41\x5a\x41\x59\x41\x58\x5a\x59\x58"  # pop r11..rax

    # patch jne offset
    skip_target = len(bc)
    skip_offset = skip_target - skip_fixup - 4
    bc[skip_fixup : skip_fixup + 4] = struct.pack("<i", skip_offset)

    # original instruction
    bc += orig_instr

    # jump back
    bc += b"\xe9"
    jmp_from = block_addr + len(bc) + 4
    jmp_offset = ret_addr - jmp_from
    bc += struct.pack("<i", jmp_offset)

    return bytes(bc)


def _login_to_instance(hwnd: int, username: str, password: str) -> None:
    pid = _get_pid_from_hwnd(hwnd)
    if pid == 0:
        raise RuntimeError("Could not get PID from window handle")

    with _RemoteProcess(pid) as proc:
        mod_base, mod_size = _find_module(pid, "WizardGraphicalClient.exe")
        module_mem = proc.read(mod_base, mod_size)

        login_offset = _scan_exact(module_mem, _LOGIN_PATTERN)
        if login_offset is None:
            raise RuntimeError(
                "LOGIN_PATTERN not found — game version may have changed"
            )
        login_addr = mod_base + login_offset

        # resolve `dat` and `func` via RIP-relative offsets
        #   m+13: 4-byte disp for `mov rcx,[rip+disp]`  → dat  = m+17 + disp
        #   m+18: 4-byte disp for `call rip+disp`        → func = m+22 + disp
        t = proc.read(login_addr + 13, 9)
        dat_disp = struct.unpack_from("<i", t, 0)[0]
        func_disp = struct.unpack_from("<i", t, 5)[0]
        dat_addr = login_addr + 17 + dat_disp
        func_addr = login_addr + 22 + func_disp

        hook_offset = _scan_wild(module_mem, _HOOK_PATTERN)
        if hook_offset is None:
            raise RuntimeError("HOOK_PATTERN not found — game version may have changed")
        hook_addr = mod_base + hook_offset
        ret_addr = hook_addr + _HOOK_INSTR_LEN

        orig_instr = proc.read(hook_addr, _HOOK_INSTR_LEN)

        cmd = f"login {username} {password}"
        cmd_utf8 = cmd.encode("utf-8")  # byte length (matches Rust String::len)
        cmd_bytes = cmd_utf8 + b"\x00"  # null-terminated for in-memory string

        str_data_addr = proc.alloc(len(cmd_bytes), executable=False)
        str_struct_addr = proc.alloc(32, executable=False)
        flag_addr = proc.alloc(8, executable=False)
        block_addr = proc.alloc_near(hook_addr, 512)

        allocs = [str_data_addr, str_struct_addr, flag_addr, block_addr]
        hook_patched = False

        def cleanup() -> None:
            if hook_patched:
                try:
                    proc.write(hook_addr, orig_instr)
                except Exception:
                    pass
            for a in allocs:
                try:
                    proc.free(a)
                except Exception:
                    pass

        try:
            proc.write(str_data_addr, cmd_bytes)
            proc.write(
                str_struct_addr, _build_string_struct(str_data_addr, len(cmd_utf8))
            )
            proc.write(flag_addr, b"\x00" * 8)

            bytecode = _build_login_bytecode(
                block_addr,
                flag_addr,
                str_struct_addr,
                dat_addr,
                func_addr,
                orig_instr,
                ret_addr,
            )
            proc.write(block_addr, bytecode)

            # arm the flag (bytecode will run when game thread hits the hook)
            proc.write(flag_addr, b"\x01")

            # patch hook site: E9 <rel32 to block> + 2 NOPs (fills 7 bytes)
            jmp_offset = block_addr - (hook_addr + 5)
            jmp_bytes = b"\xe9" + struct.pack("<i", jmp_offset) + b"\x90\x90"
            proc.write(hook_addr, jmp_bytes)
            hook_patched = True

            # poll until bytecode clears the flag
            deadline = time.monotonic() + 10.0
            while True:
                time.sleep(0.05)
                if proc.read(flag_addr, 1)[0] == 0x00:
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        "Timed out waiting for login bytecode to execute"
                    )
        finally:
            cleanup()


# public API (mirrors libs/wizlaunch/wizlaunch.pyi)

__version__ = "0.2.0-py"


def prompt_save_account(nickname: str) -> None:
    username, password = _prompt_credentials(nickname)
    save_account(nickname, username, password)


def save_account(nickname: str, username: str, password: str) -> None:
    _cred_write(nickname, username, password)
    meta = _load_meta()
    if nickname not in meta["nicknames_order"]:
        meta["nicknames_order"].append(nickname)
        _save_meta(meta)


def delete_account(nickname: str) -> None:
    _cred_delete(nickname)
    meta = _load_meta()
    meta["nicknames_order"] = [n for n in meta["nicknames_order"] if n != nickname]
    meta["gid_map"].pop(nickname, None)
    _save_meta(meta)


def list_accounts() -> list[str]:
    cred_nicks = _cred_list()
    meta = _load_meta()
    order = meta.get("nicknames_order", [])
    if not order:
        return cred_nicks
    seen: set[str] = set()
    result: list[str] = []
    for n in order:
        if n in cred_nicks and n not in seen:
            result.append(n)
            seen.add(n)
    for n in cred_nicks:
        if n not in seen:
            result.append(n)
            seen.add(n)
    return result


def reorder_accounts(ordered: list[str]) -> None:
    meta = _load_meta()
    meta["nicknames_order"] = list(ordered)
    _save_meta(meta)


def has_account(nickname: str) -> bool:
    return _cred_has(nickname)


def update_player_gid(nickname: str, gid: int) -> None:
    meta = _load_meta()
    meta["gid_map"][nickname] = int(gid)
    _save_meta(meta)


def get_player_gid(nickname: str) -> Optional[int]:
    meta = _load_meta()
    val = meta["gid_map"].get(nickname)
    return int(val) if val is not None else None


def get_nickname_by_gid(gid: int) -> Optional[str]:
    meta = _load_meta()
    for nick, stored in meta["gid_map"].items():
        if int(stored) == int(gid):
            return nick
    return None


def launch_instance(
    nickname: str,
    game_path: str,
    login_server: Optional[str] = None,
    timeout_secs: int = 30,
) -> int:
    server = login_server or DEFAULT_SERVER
    before = set(_get_wizard_handles())
    _launch_game(game_path, server)
    handle = _wait_for_new_handle(before, timeout_secs)
    _enable_window(handle, False)
    try:
        time.sleep(2)
        username, password = _cred_read(nickname)
        _login_to_instance(handle, username, password)
    finally:
        _enable_window(handle, True)
    return handle


def launch_instances(
    nicknames: list[str],
    game_path: str,
    login_server: Optional[str] = None,
    timeout_secs: int = 30,
) -> dict[str, int]:
    server = login_server or DEFAULT_SERVER
    known = set(_get_wizard_handles())
    results: dict[str, int] = {}
    for nickname in nicknames:
        try:
            _launch_game(game_path, server)
            handle = _wait_for_new_handle(known, timeout_secs)
        except RuntimeError as e:
            print(f"Failed to launch '{nickname}': {e}", file=sys.stderr)
            continue
        known.add(handle)
        _enable_window(handle, False)
        try:
            time.sleep(2)
            username, password = _cred_read(nickname)
            _login_to_instance(handle, username, password)
            results[nickname] = handle
        except RuntimeError as e:
            print(f"Failed to log in '{nickname}': {e}", file=sys.stderr)
        finally:
            _enable_window(handle, True)
    return results


def kill_instance(handle: int) -> bool:
    return _kill_process_by_handle(handle)


def get_wizard_handles() -> list[int]:
    return _get_wizard_handles()
