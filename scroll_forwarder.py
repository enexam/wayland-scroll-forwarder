#!/usr/bin/env python3
import evdev
from evdev import InputDevice, ecodes
from Xlib import X, display, error
from Xlib.ext import xtest
import select
import sys
import os
import time
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)


class ScrollForwarder:
    def __init__(self, target_class):
        self.display = display.Display()
        self.root = self.display.screen().root
        self.target_class = target_class
        self.target_window = None

        if target_class:
            self.target_window = self.find_window_by_class(target_class)
            if self.target_window:
                logger.info(f"Found window: {hex(self.target_window.id)}")
            else:
                logger.warning(f"Window with class '{target_class}' not found. Will wait for it to appear...")

        self.devices = self.find_scroll_devices()
        if not self.devices:
            logger.error("No input device with scroll capability found. Exiting.")
            sys.exit(1)
        logger.info(f"Monitoring devices: {[d.name for d in self.devices]}")

    def find_scroll_devices(self):
        """Find all devices capable of scroll events"""
        devices = []
        for path in evdev.list_devices():
            try:
                device = InputDevice(path)
                caps = device.capabilities()
                if ecodes.EV_REL in caps:
                    rel_codes = caps[ecodes.EV_REL]
                    if ecodes.REL_WHEEL in rel_codes or ecodes.REL_HWHEEL in rel_codes:
                        devices.append(device)
            except (OSError, PermissionError):
                continue
        return devices

    def find_window_by_class(self, class_name):
        """Recursively find window by WM_CLASS"""
        def search_windows(window):
            try:
                wm_class = window.get_wm_class()
                if wm_class and any(class_name.lower() in c.lower() for c in wm_class):
                    return window
            except Exception:
                pass

            try:
                children = window.query_tree().children
                for child in children:
                    result = search_windows(child)
                    if result:
                        return result
            except Exception:
                pass

            return None

        return search_windows(self.root)

    def is_target_window_active(self):
        """Check if target window or its children are visible/active"""
        try:
            return self.target_window.get_attributes().map_state == X.IsViewable
        except Exception:
            return False

    def does_target_window_exist(self):
        """Return True if the target window still exists, even if minimized or out of focus."""
        if not self.target_window:
            return False
        try:
            # Raise = window gone
            _ = self.target_window.get_geometry()
            return True
        except error.XError:
            return False

    def inject_scroll_to_window(self, direction, value):
        """Inject scroll directly to the target window"""
        if not self.target_window:
            return

        if direction == ecodes.REL_WHEEL:
            button = 4 if value > 0 else 5
        elif direction == ecodes.REL_HWHEEL:
            button = 6 if value < 0 else 7
        else:
            return

        for _ in range(abs(value)):
            xtest.fake_input(self.display, X.ButtonPress, button)
            xtest.fake_input(self.display, X.ButtonRelease, button)
        self.display.sync()

    def run(self):
        """Main event loop with window-wait polling"""
        selector = select.poll()
        for device in self.devices:
            selector.register(device.fileno(), select.POLLIN)
        logger.info("Forwarder running. Press CTRL+C to stop.")

        try:
            while True:
                events = selector.poll(500)

                if not self.target_window and self.target_class:
                    self.target_window = self.find_window_by_class(self.target_class)
                    if self.target_window:
                        logger.info(f"Found window: {hex(self.target_window.id)}")

                # Graceful stop if window is gone
                if self.target_window and not self.does_target_window_exist():
                    logger.info("Target window closed. Exiting forwarder.")
                    break

                # Handle events
                for fd, _ in events:
                    device = next((d for d in self.devices if d.fileno() == fd), None)
                    if not device:
                        continue
                    try:
                        for event in device.read():
                            if event.type == ecodes.EV_REL and event.code in (ecodes.REL_WHEEL, ecodes.REL_HWHEEL):
                                if self.is_target_window_active():
                                    self.inject_scroll_to_window(event.code, event.value)
                    except (BlockingIOError, OSError):
                        continue
        except KeyboardInterrupt:
            logger.info("\nStopping forwarder...")
        finally:
            for device in self.devices:
                try:
                    device.close()
                except Exception:
                    pass



if __name__ == "__main__":
    if os.geteuid() != 0:
        logger.error("This script needs root access to read input events.")
        logger.error("Usage: sudo scroll_forwarder <window_class>")
        sys.exit(1)

    if len(sys.argv) < 2:
        logger.error("Run 'xprop WM_CLASS' and click on app to get the window class.")
        logger.error("Usage: sudo scroll_forwarder <window_class>")
        sys.exit(1)

    ScrollForwarder(sys.argv[1]).run()
