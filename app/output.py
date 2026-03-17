"""Text injection utilities for Windows."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import time


logger = logging.getLogger(__name__)

_CLIPBOARD_RESTORE_DELAY_SECONDS = 0.08

user32 = ctypes.WinDLL("user32", use_last_error=True)
SendInput = user32.SendInput
GetMessageExtraInfo = user32.GetMessageExtraInfo

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_CONTROL = 0x11
VK_V = 0x56


if hasattr(wintypes, "ULONG_PTR"):
    ULONG_PTR = wintypes.ULONG_PTR  # type: ignore[attr-defined]
else:  # Fallback for Python builds lacking ULONG_PTR in wintypes
    if ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_uint64):
        ULONG_PTR = ctypes.c_uint64
    else:
        ULONG_PTR = ctypes.c_uint32


class KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [
        ("ki", KeyboardInput),
        ("mi", MouseInput),
        ("hi", HardwareInput),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", InputUnion)]


SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
SendInput.restype = wintypes.UINT
GetMessageExtraInfo.argtypes = ()
GetMessageExtraInfo.restype = ULONG_PTR


def _send_inputs(*items: INPUT) -> bool:
    if not items:
        return True

    input_array_type = INPUT * len(items)
    inputs = input_array_type(*items)
    sent = SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        last_error = ctypes.get_last_error()
        logger.warning(
            "SendInput 发送失败，sent=%s expected=%s last_error=%s",
            sent,
            len(inputs),
            last_error,
        )
        return False
    return True


def _iter_utf16_code_units(char: str) -> list[int]:
    encoded = char.encode("utf-16-le")
    return [int.from_bytes(encoded[index : index + 2], "little") for index in range(0, len(encoded), 2)]


def _emit_unicode_char(char: str) -> bool:
    events: list[INPUT] = []
    for code_unit in _iter_utf16_code_units(char):
        extra_info = GetMessageExtraInfo()
        events.append(
            INPUT(
                type=INPUT_KEYBOARD,
                union=InputUnion(
                    ki=KeyboardInput(
                        wVk=0,
                        wScan=code_unit,
                        dwFlags=KEYEVENTF_UNICODE,
                        time=0,
                        dwExtraInfo=extra_info,
                    )
                ),
            )
        )
        events.append(
            INPUT(
                type=INPUT_KEYBOARD,
                union=InputUnion(
                    ki=KeyboardInput(
                        wVk=0,
                        wScan=code_unit,
                        dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                        time=0,
                        dwExtraInfo=extra_info,
                    )
                ),
            )
        )

    if not _send_inputs(*events):
        logger.warning("SendInput 发送字符失败，char=%s", char)
        return False
    return True


def type_text(text: str, append_newline: bool = False, method: str = "auto") -> None:
    if not text:
        return

    payload = text + ("\r\n" if append_newline else "")
    logger.debug("注入文本: %s", payload)

    method = (method or "auto").lower()
    if method == "type":
        order = ["type", "clipboard", "unicode"]
    elif method == "clipboard":
        order = ["clipboard", "unicode", "type"]
    elif method == "unicode":
        order = ["unicode", "clipboard", "type"]
    else:
        # Prefer direct Unicode injection first. Ctrl+V can be silently ignored by
        # some targets while still looking successful from our side.
        order = ["unicode", "clipboard", "type"]

    for mode in order:
        if mode == "type" and _type_with_keyboard(payload):
            logger.info("文本注入成功: mode=type length=%s", len(payload))
            return
        if mode == "clipboard" and _try_clipboard_injection(payload):
            logger.info("文本注入成功: mode=clipboard length=%s", len(payload))
            return
        if mode == "unicode" and _type_with_unicode(payload):
            logger.info("文本注入成功: mode=unicode length=%s", len(payload))
            return

    logger.error("所有文本注入方式均失败: %s", payload)


def _type_with_keyboard(payload: str) -> bool:
    try:
        import keyboard

        keyboard.write(payload, delay=0)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyboard.write 失败: %s", exc)
        return False


def _type_with_unicode(payload: str) -> bool:
    success = True
    for char in payload:
        if not _emit_unicode_char(char):
            success = False
            break
    return success


def _try_clipboard_injection(payload: str) -> bool:
    try:
        import pyperclip
    except ImportError:
        return False

    try:
        prev_clip = pyperclip.paste()
    except Exception:
        prev_clip = None

    try:
        pyperclip.copy(payload)
        success = _emit_ctrl_v()
    except Exception as exc:  # noqa: BLE001
        logger.debug("剪贴板注入失败，退回逐字符输入: %s", exc)
        success = False
    finally:
        if prev_clip is not None:
            try:
                time.sleep(_CLIPBOARD_RESTORE_DELAY_SECONDS)
                pyperclip.copy(prev_clip)
            except Exception:
                pass

    return success


def _emit_ctrl_v() -> bool:
    inputs = (
        INPUT(
            type=INPUT_KEYBOARD,
            union=InputUnion(
                ki=KeyboardInput(
                    wVk=VK_CONTROL,
                    wScan=0,
                    dwFlags=0,
                    time=0,
                    dwExtraInfo=GetMessageExtraInfo(),
                )
            ),
        ),
        INPUT(
            type=INPUT_KEYBOARD,
            union=InputUnion(
                ki=KeyboardInput(
                    wVk=VK_V,
                    wScan=0,
                    dwFlags=0,
                    time=0,
                    dwExtraInfo=GetMessageExtraInfo(),
                )
            ),
        ),
        INPUT(
            type=INPUT_KEYBOARD,
            union=InputUnion(
                ki=KeyboardInput(
                    wVk=VK_V,
                    wScan=0,
                    dwFlags=KEYEVENTF_KEYUP,
                    time=0,
                    dwExtraInfo=GetMessageExtraInfo(),
                )
            ),
        ),
        INPUT(
            type=INPUT_KEYBOARD,
            union=InputUnion(
                ki=KeyboardInput(
                    wVk=VK_CONTROL,
                    wScan=0,
                    dwFlags=KEYEVENTF_KEYUP,
                    time=0,
                    dwExtraInfo=GetMessageExtraInfo(),
                )
            ),
        ),
    )
    if not _send_inputs(*inputs):
        logger.warning("SendInput Ctrl+V 失败")
        # 尝试一次退避后再次发送
        if not _send_inputs(*inputs):
            logger.warning("SendInput Ctrl+V 第二次重试失败")
            return False

    return True

