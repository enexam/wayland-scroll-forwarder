#!/usr/bin/env python3
"""Forward physical wheel events to a focused Xwayland window.

Only an explicitly selected input device is opened.  When started through sudo,
the device is opened first and all supplementary groups and root privileges are
dropped before connecting to X11 or entering the event loop.
"""

from __future__ import annotations

import argparse
import logging
import os
import pwd
import select
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

import evdev
from evdev import InputDevice, ecodes
from Xlib import X, display, error
from Xlib.ext import xtest


LOG = logging.getLogger("wayland-scroll-forwarder")
HI_RES_UNITS_PER_STEP = 120
MAX_STEPS_PER_REPORT = 32


@dataclass
class AxisFrame:
    legacy: int = 0
    hi_res: int = 0
    saw_legacy: bool = False
    saw_hi_res: bool = False


class WheelNormalizer:
    """Normalize legacy and high-resolution wheel events without duplication."""

    def __init__(self) -> None:
        self._remainder = {"vertical": 0, "horizontal": 0}

    def steps(self, axis: str, frame: AxisFrame) -> int:
        # Kernels commonly emit both event types for the same wheel movement.
        # Prefer legacy events when present so the movement is not doubled.
        if frame.saw_legacy:
            return frame.legacy
        if not frame.saw_hi_res:
            return 0

        total = self._remainder[axis] + frame.hi_res
        magnitude = abs(total) // HI_RES_UNITS_PER_STEP
        steps = magnitude if total >= 0 else -magnitude
        self._remainder[axis] = total - steps * HI_RES_UNITS_PER_STEP
        return steps


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Forward wheel events from one input device to a focused X11/Xwayland window."
    )
    parser.add_argument("window_class", nargs="?", help="exact WM_CLASS value (for GFN: GeForceNOW)")
    parser.add_argument("--device", metavar="PATH", help="one /dev/input/eventN or /dev/input/by-id path")
    parser.add_argument("--list-devices", action="store_true", help="list wheel-capable readable devices and exit")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def list_devices() -> int:
    found = False
    for path in sorted(evdev.list_devices()):
        try:
            device = InputDevice(path)
            rel = device.capabilities().get(ecodes.EV_REL, [])
            wheel_codes = {
                ecodes.REL_WHEEL,
                ecodes.REL_HWHEEL,
                getattr(ecodes, "REL_WHEEL_HI_RES", -1),
                getattr(ecodes, "REL_HWHEEL_HI_RES", -1),
            }
            if wheel_codes.intersection(rel):
                found = True
                stable = stable_device_links(Path(path))
                suffix = f" ({', '.join(stable)})" if stable else ""
                print(f"{path}: {device.name}{suffix}")
            device.close()
        except (OSError, PermissionError) as exc:
            LOG.debug("Cannot inspect %s: %s", path, exc)
    if not found:
        LOG.error("No readable wheel device found. Run with sudo only for device discovery.")
        return 1
    return 0


def stable_device_links(event_path: Path) -> list[str]:
    links: list[str] = []
    for directory in (Path("/dev/input/by-id"), Path("/dev/input/by-path")):
        try:
            for candidate in directory.iterdir():
                try:
                    if candidate.resolve() == event_path.resolve():
                        links.append(str(candidate))
                except OSError:
                    continue
        except OSError:
            continue
    return links


def validate_device_path(path: str) -> Path:
    requested = Path(path)
    try:
        resolved = requested.resolve(strict=True)
        mode = resolved.stat().st_mode
    except OSError as exc:
        raise ValueError(f"cannot access input device {requested}: {exc}") from exc
    if resolved.parent != Path("/dev/input") or not resolved.name.startswith("event"):
        raise ValueError("device must resolve to /dev/input/eventN")
    if not stat.S_ISCHR(mode):
        raise ValueError(f"{resolved} is not a character device")
    return requested


def open_wheel_device(path: Path) -> InputDevice:
    device = InputDevice(str(path))
    rel = device.capabilities().get(ecodes.EV_REL, [])
    supported = {
        ecodes.REL_WHEEL,
        ecodes.REL_HWHEEL,
        getattr(ecodes, "REL_WHEEL_HI_RES", -1),
        getattr(ecodes, "REL_HWHEEL_HI_RES", -1),
    }
    if not supported.intersection(rel):
        device.close()
        raise ValueError(f"{path} ({device.name}) does not advertise wheel events")
    return device


def drop_sudo_privileges() -> None:
    """Permanently become the invoking user after the input fd is open."""
    if os.geteuid() != 0:
        return
    uid_text = os.environ.get("SUDO_UID")
    gid_text = os.environ.get("SUDO_GID")
    if not uid_text or not gid_text:
        raise PermissionError("refusing to run as direct root; invoke with sudo from a desktop user")

    uid, gid = int(uid_text), int(gid_text)
    account = pwd.getpwuid(uid)
    os.environ["HOME"] = account.pw_dir
    os.environ["USER"] = account.pw_name
    os.environ["LOGNAME"] = account.pw_name
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    if os.geteuid() == 0:
        raise PermissionError("failed to drop root privileges")
    LOG.info("Dropped privileges to %s (uid %d)", account.pw_name, uid)


class ScrollForwarder:
    def __init__(self, target_class: str, device: InputDevice) -> None:
        self.target_class = target_class.casefold()
        self.device = device
        self.normalizer = WheelNormalizer()
        self.display = display.Display()
        self.root = self.display.screen().root
        self.target_window = None
        self._find_and_log_target()

    def _window_matches(self, window) -> bool:
        try:
            values = window.get_wm_class() or ()
            return any(value.casefold() == self.target_class for value in values)
        except (error.XError, AttributeError):
            return False

    def find_window(self):
        pending = [self.root]
        while pending:
            window = pending.pop()
            if self._window_matches(window):
                return window
            try:
                pending.extend(window.query_tree().children)
            except error.XError:
                continue
        return None

    def _find_and_log_target(self, *, waiting_message: bool = True) -> None:
        self.target_window = self.find_window()
        if self.target_window:
            LOG.info("Found target window 0x%x", self.target_window.id)
        elif waiting_message:
            LOG.info("Waiting for WM_CLASS %r", self.target_class)

    def target_exists(self) -> bool:
        if not self.target_window:
            return False
        try:
            self.target_window.get_geometry()
            return True
        except error.XError:
            return False

    def active_window(self):
        atom = self.display.intern_atom("_NET_ACTIVE_WINDOW")
        try:
            prop = self.root.get_full_property(atom, X.AnyPropertyType)
            if not prop or not len(prop.value):
                return None
            return self.display.create_resource_object("window", int(prop.value[0]))
        except error.XError:
            return None

    @staticmethod
    def is_same_or_descendant(window, ancestor) -> bool:
        current = window
        for _ in range(64):
            if not current:
                return False
            if current.id == ancestor.id:
                return True
            try:
                parent = current.query_tree().parent
            except error.XError:
                return False
            if not parent or parent.id == current.id:
                return False
            current = parent
        return False

    def target_is_focused(self) -> bool:
        active = self.active_window()
        return bool(
            self.target_window
            and active
            and (
                self.is_same_or_descendant(active, self.target_window)
                or self.is_same_or_descendant(self.target_window, active)
            )
        )

    def inject_steps(self, axis: str, steps: int) -> None:
        steps = max(-MAX_STEPS_PER_REPORT, min(MAX_STEPS_PER_REPORT, steps))
        if axis == "vertical":
            button = 4 if steps > 0 else 5
        else:
            button = 6 if steps < 0 else 7
        for _ in range(abs(steps)):
            xtest.fake_input(self.display, X.ButtonPress, button)
            xtest.fake_input(self.display, X.ButtonRelease, button)
        self.display.sync()

    def process_report(self, report: list) -> None:
        frames = {"vertical": AxisFrame(), "horizontal": AxisFrame()}
        mappings = {
            ecodes.REL_WHEEL: ("vertical", "legacy"),
            ecodes.REL_HWHEEL: ("horizontal", "legacy"),
            getattr(ecodes, "REL_WHEEL_HI_RES", -1): ("vertical", "hi_res"),
            getattr(ecodes, "REL_HWHEEL_HI_RES", -1): ("horizontal", "hi_res"),
        }
        for event in report:
            if event.type != ecodes.EV_REL or event.code not in mappings:
                continue
            axis, kind = mappings[event.code]
            frame = frames[axis]
            if kind == "legacy":
                frame.legacy += event.value
                frame.saw_legacy = True
            else:
                frame.hi_res += event.value
                frame.saw_hi_res = True

        if not any(frame.saw_legacy or frame.saw_hi_res for frame in frames.values()):
            return
        if not self.target_is_focused():
            return
        for axis, frame in frames.items():
            steps = self.normalizer.steps(axis, frame)
            if steps:
                LOG.debug("Forwarding %s wheel steps: %d", axis, steps)
                self.inject_steps(axis, steps)

    def run(self) -> int:
        poller = select.poll()
        poller.register(self.device.fileno(), select.POLLIN | select.POLLERR | select.POLLHUP)
        report: list = []
        had_target = self.target_window is not None
        LOG.info("Monitoring only %s (%s); press Ctrl+C to stop", self.device.path, self.device.name)
        try:
            while True:
                for _, flags in poller.poll(500):
                    if flags & (select.POLLERR | select.POLLHUP):
                        LOG.error("Input device disconnected")
                        return 1
                    try:
                        events = self.device.read()
                    except BlockingIOError:
                        continue
                    for event in events:
                        if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
                            self.process_report(report)
                            report.clear()
                        else:
                            report.append(event)

                if self.target_window and not self.target_exists():
                    LOG.info("Target window closed")
                    self.target_window = None
                    if had_target:
                        return 0
                elif not self.target_window:
                    self._find_and_log_target(waiting_message=False)
                    had_target = had_target or self.target_window is not None
        except KeyboardInterrupt:
            LOG.info("Stopping")
            return 0
        finally:
            self.device.close()
            self.display.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        format="%(levelname)s: %(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )
    if args.list_devices:
        return list_devices()
    if not args.window_class or not args.device:
        LOG.error("WINDOW_CLASS and --device are required (use --list-devices first)")
        return 2

    try:
        path = validate_device_path(args.device)
        device = open_wheel_device(path)
        drop_sudo_privileges()
        return ScrollForwarder(args.window_class, device).run()
    except (ValueError, PermissionError, OSError, error.DisplayError) as exc:
        LOG.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
