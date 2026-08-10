# Hardened Wayland Scroll Forwarder

This is a security-focused fork of
[`enexam/wayland-scroll-forwarder`](https://github.com/enexam/wayland-scroll-forwarder).
It forwards wheel events from one explicitly selected physical device only while
an exact X11/Xwayland `WM_CLASS` is focused.

## Security changes

- Requires an explicit input-device path; it never reads every input device.
- Permanently drops root and supplementary groups immediately after opening that device.
- Refuses direct root execution; privileged fallback must come from a desktop user via `sudo`.
- Requires an exact, case-insensitive `WM_CLASS` match.
- Checks `_NET_ACTIVE_WINDOW`; a merely visible target receives nothing.
- De-duplicates paired legacy/high-resolution wheel events.
- Caps synthetic events from a single input report.
- Downloads or executes no remote content and creates no persistence.

The safest configuration is to give the logged-in user read access to one stable
mouse event device and run the forwarder without `sudo`. The sudo fallback still
drops privileges, but opening the device through a privileged Python process has
a larger attack surface than a device ACL.

## Dependencies

- Python 3
- `python-evdev`
- `python-xlib`
- `libXtst`

Fedora/Bazzite currently provides the required Python modules on the host. Other
distributions can use their native packages listed by the upstream project.

## Usage

Discover the mouse event device:

```bash
sudo ./scroll_forwarder.py --list-devices
```

Prefer a stable `/dev/input/by-id/...-event-mouse` path from the output. Then run:

```bash
sudo --preserve-env=DISPLAY,XAUTHORITY ./scroll_forwarder.py \
  --device /dev/input/by-id/YOUR-MOUSE-event-mouse GeForceNOW
```

The script opens only that device, drops to `SUDO_UID`, and then connects to X11.
It waits for GFN, forwards only while GFN is focused, and exits after the target
window closes.

For completely unprivileged operation, grant the active desktop user a device ACL
(temporary until reconnect/reboot):

```bash
sudo setfacl -m "u:$USER:r" /dev/input/by-id/YOUR-MOUSE-event-mouse
./scroll_forwarder.py --device /dev/input/by-id/YOUR-MOUSE-event-mouse GeForceNOW
```

Do not grant access to keyboard event devices or add the user broadly to the
`input` group.

## Tests

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scroll_forwarder.py
```

## Limitations

XTest synthesizes wheel buttons into Xwayland globally. Focus checking minimizes
misdelivery but cannot make XTest a true per-window injection API. The program
does not grab or suppress the original device, so an application that starts
receiving native wheel events may see duplicates; stop the forwarder after an
upstream fix.

This workaround is not endorsed by NVIDIA and has not been evaluated against
individual games' anti-cheat systems.
