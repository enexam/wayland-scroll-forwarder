# wayland-scroll-forwarder

This script fixes scroll wheel when using apps designed for X11 on Wayland.

## Installation

### Dependencies

Install dependencies `libXtst`, `python-evdev`, `python-xlib`

Ubuntu / Debian (apt):

```bash
sudo apt install python3-evdev python3-xlib libxtst6
```

Arch / EndeavourOS (pacman):

```bash
sudo pacman -S python-evdev python-xlib libxtst
```

Fedora (dnf):

```bash
sudo dnf install python3-evdev python3-xlib libXtst
```

### Wayland Scroll Forwarder

Install `wayland_scroll_forwarder`

```bash
sudo curl -sL https://raw.githubusercontent.com/enexam/wayland-scroll-forwarder/main/scroll_forwarder.py -o /usr/local/bin/wayland_scroll_forwarder && sudo chmod +x /usr/local/bin/wayland_scroll_forwarder
```

### First use

Start the X11 app. Example: GeForce Now

```bash
flatpak run com.nvidia.geforcenow
```

DO NOT LAUNCH A GAME (or the subprocess needing the fix) YET.

Get the window class name. In another terminal:

```bash
xprop WM_CLASS
```

Then click inside the app window. It returns the window class (last string).

```bash
WM_CLASS(STRING) = "GeForceNOW", "GeForceNOW"
```

Start the python script in sudo with the window class.

```bash
sudo wayland_scroll_forwarder GeForceNOW
```

The scroll forwarder will stop when closing your app (such as GFN).
You can also press CTRL+C in the terminal running the scroll forwarder to stop it.

### Create alias for your apps

After testing your app with the scroll forwarder, you can create an alias with the specific class. This will make a single command start both your app and the scroll forwarder.

Example with GeForce Now (replace app name and class name as needed)

```bash
echo "alias geforce-now='sudo wayland_scroll_forwarder GeForceNOW & flatpak run com.nvidia.geforcenow'" >> ~/.bashrc && source ~/.bashrc
```

Now you can launch the app with scroll fix by simply typing in a terminal the alias:

```bash
geforce-now
```

## Multiplayer

Not tested against anti-cheat softwares. USE AT YOUR OWN RISK.

## Troubleshooting

Please [report issues](https://github.com/enexam/wayland-scroll-forwarder/issues/new) you are facing.

### Common issues

Well... I don't know yet.
