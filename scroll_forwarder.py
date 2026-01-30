#!/bin/env python3
import evdev
from evdev import InputDevice, ecodes
from Xlib import X, display
from Xlib.ext import xtest
import select
import sys
import os
import time
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(format = '%(levelname)s:%(message)s', level=logging.INFO)

class ScrollForwarder:
    def __init__(self, target_window_id = None, target_class = None):
        self.display = display.Display()
        self.root = self.display.screen().root
        self.target_window_id = target_window_id
        self.target_class = target_class
        self.target_window = None

        # Find the target window
        if target_window_id:
            self.target_window = self.display.create_resource_object('window', target_window_id)
            logger.info(f"Targeting window ID: {hex(target_window_id)}")
        elif target_class:
            self.target_window = self.find_window_by_class(target_class)
            if self.target_window:
                logger.info(f"Found window: {hex(self.target_window.id)}")
            else:
                logger.error(f"Window with class '{target_class}' not found.")
                logger.error(f"Start your app first, then run this script.")
                sys.exit(1)

        # Find mouse/touchpad devices
        self.devices = self.find_scroll_devices()
        if not self.devices:
            logger.error("No device found")
            sys.exit(1)
        logger.info(f"Monitoring devices: {[d.name for d in self.devices]}")

    def find_scroll_devices(self):
        """Find all devices capable of scroll events"""
        devices = []
        for path in evdev.list_devices():
            try:
                device = InputDevice(path)
                caps = device.capabilities()
                # Check for relative scroll wheel (REL_WHEEL, REL_HWHEEL)
                if ecodes.EV_REL in caps:
                    if ecodes.REL_WHEEL in caps[ecodes.EV_REL] or ecodes.REL_HWHEEL in caps[ecodes.EV_REL]:
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
            except:
                pass

            try:
                children = window.query_tree().children
                for child in children:
                    result = search_windows(child)
                    if result:
                        return result
            except:
                pass

            return None

        return search_windows(self.root)

    def is_target_window_active(self):
        """Check if target window or its children are visible/active"""
        if not self.target_window:
            return False

        try:
            # Check if window is mapped (visible)
            attrs = self.target_window.get_attributes()
            return attrs.map_state == X.IsViewable
        except:
            return False

    def inject_scroll_to_window(self, direction, value):
        """Inject scroll directly to the target window"""
        if not self.target_window:
            return

        # Map direction to X11 buttons: 4=up, 5=down, 6=left, 7=right
        if direction == ecodes.REL_WHEEL:
            button = 4 if value > 0 else 5 # Scroll up/down
        elif direction == ecodes.REL_HWHEEL:
            button = 6 if value < 0 else 7
        else:
            return

        # Get pointer position relative to target window
        try:
            pointer = self.target_window.query_pointer()
            x, y = pointer.win_x, pointer.win_y
        except:
            x, y = 100, 100

        # Inject button press/release for each scroll notch
        for _ in range(abs(value)):
            # Send ButtonPress with coordinates
            event = xtest.fake_input(self.display, X.ButtonPress, button)
            event = xtest.fake_input(self.display, X.ButtonRelease, button)
        self.display.sync()

    def run(self):
        """Main event loop"""
        # Create selector for efficient polling
        selector = select.poll()
        for device in self.devices:
            selector.register(device.fileno(), select.POLLIN)
        logger.info("Forwarder running. Press CTRL+C to stop.")

        try:
            while True:
                # Wait for events (blocking, low CPU usage)
                events = selector.poll()
                for fd, _ in events:
                    # Find which device triggered
                    device = next(d for d in self.devices if d.fileno() == fd)
                    # Read event
                    for event in device.read():
                        if event.type == ecodes.EV_REL:
                            if event.code in (ecodes.REL_WHEEL, ecodes.REL_HWHEEL):
                                # Always forward if target window is active / visible
                                if self.is_target_window_active():
                                    # Inject to target app
                                    self.inject_scroll_to_window(event.code, event.value)
        except KeyboardInterrupt:
            logger.info("\nStopping forwarder...")
        finally:
            for device in self.devices:
                device.close()

if __name__ == "__main__":
    if os.geteuid() != 0:
        logger.error("This script needs root access to read input events.")
        sys.exit(1)
    if len(sys.argv) < 2:
        logger.error("Usage: sudo python3 scroll_forwarder.py --window-id <hex_id> or sudo python3 scroll_forwarder.py <window_class>")
        logger.error("Run xprop WM_CLASS and click on app")
        sys.exit(1)

    if sys.argv[1] == "--window-id":
        if len(sys.argv) < 3:
            logger.error("Provide window ID.")
            sys.exit(1)
        forwarder = ScrollForwarder(target_window_id=int(sys.argv[2], 16))
    else:
        forwarder = ScrollForwarder(target_class=sys.argv[1])

    forwarder.run()
