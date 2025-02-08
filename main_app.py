import tkinter as tk
from tkinter import filedialog, messagebox
import csv
import ast
import os
import sys
import threading
import time
import platform
import json
import pygame

# For Windows Registry autoload (only used on Windows)
if platform.system().lower().startswith('win'):
    import winreg

# For system tray integration
import pystray
from PIL import Image, ImageDraw

# HID packages
import hid
import utils_hid

# --------------------------
# Global Constants & Config
# --------------------------
CONFIG_FILE = "driftguard_config.json"
DRAW_INTERVAL_MS = 16  # ~60 FPS

# Only DualSense and DualSense Edge
PS_SUPPORTED_DEVICES = {
    ("054C", "0CE6"): "Sony DualSense (PS5)",
    ("054C", "0DF2"): "Sony DualSense Edge",
}

# HID usage pages and IDs for gamepads/joysticks
GAMEPAD_USAGE_PAGE = 0x01  # Generic Desktop Controls
GAMEPAD_USAGE = 0x05       # Gamepad
JOYSTICK_USAGE = 0x04      # Joystick

# Color / UI config (Dark Mode)
COLOR_BG_DARK = "#2B2B2B"
COLOR_FRAME_DARK = "#3B3B3B"
COLOR_TEXT_LIGHT = "#FFFFFF"
COLOR_TEXT_DIM = "#CCCCCC"
COLOR_HIGHLIGHT = "#888888"
COLOR_CANVAS_BG = "#2A2A2A"
COLOR_LEFT_DOT = "#50FA7B"
COLOR_RIGHT_DOT = "#FF5555"
COLOR_BUTTON_BG = "#444444"
COLOR_BUTTON_ACTIVE = "#666666"
COLOR_CHECK_SELECT = "#444444"

# --------------------------
# Pygame Joystick Setup
# --------------------------
pygame.init()
pygame.joystick.init()

# --------------------------
# Global Variables
# --------------------------
tray_icon = None

joystick = None
joystick_axes = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
joystick_vid_pid = ("", "")
ps_controller_conn_type = ""
is_joystick_connected = False

joystick_thread = None
joystick_thread_running = False

root = None
terminal_text = None
analog_canvas = None
controller_status_label = None

autoload_checkbox_var = None          # Checkbutton: "Autoload on Windows Start"
start_minimized_var = None            # Checkbutton: "Start Minimized"
autoload_calibration_var = None       # Checkbutton: "Load Calibration on Startup"
startup_calibration_file_path_var = None  # StringVar for the file path

active_dev_path = None    # HID path of the active device
device_detect_fail_count = 0

# --------------------------
# Utility & Config
# --------------------------
def resource_path(relative_path):
    """Get absolute path to resource, for dev or PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def log_to_terminal(message):
    """Append a message to the terminal Text widget (or console)."""
    if terminal_text:
        terminal_text.insert(tk.END, message + "\n")
        terminal_text.see(tk.END)
    else:
        print("[Terminal not ready] " + message)

def load_settings():
    """Load config from JSON and set our global variables."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
            autoload_checkbox_var.set(data.get("autoload", False))
            start_minimized_var.set(data.get("start_minimized", False))
            autoload_calibration_var.set(data.get("autoload_calibration", False))
            # NEW: load user-specified startup calibration file
            default_path = "startup_calibration.csv"
            startup_calibration_file_path_var.set(
                data.get("startup_calibration_file", default_path)
            )
        except Exception as e:
            print(f"Failed to load config: {e}")
    else:
        # If no config file exists, use defaults
        startup_calibration_file_path_var.set("startup_calibration.csv")

def save_settings():
    """Save current settings to JSON."""
    data = {
        "autoload": autoload_checkbox_var.get(),
        "start_minimized": start_minimized_var.get(),
        "autoload_calibration": autoload_calibration_var.get(),
        "startup_calibration_file": startup_calibration_file_path_var.get(),
    }
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Failed to save config: {e}")

def set_autoload(enabled):
    """Set or unset the Windows autostart registry key."""
    if not platform.system().lower().startswith('win'):
        log_to_terminal("Autoload is only supported on Windows.")
        return

    app_name = "Driftguard Calibration Utility"
    app_path = sys.argv[0]
    try:
        key = winreg.HKEY_CURRENT_USER
        subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(key, subkey, 0, winreg.KEY_SET_VALUE) as regkey:
            if enabled:
                winreg.SetValueEx(regkey, app_name, 0, winreg.REG_SZ, app_path)
                log_to_terminal("Autoload enabled.")
            else:
                try:
                    winreg.DeleteValue(regkey, app_name)
                    log_to_terminal("Autoload disabled.")
                except FileNotFoundError:
                    pass
    except Exception as e:
        messagebox.showerror("Error", f"Failed to set autoload: {e}")

def on_autoload_checkbox_change():
    set_autoload(autoload_checkbox_var.get())
    save_settings()

def on_start_minimized_checkbox_change():
    save_settings()

def on_autoload_calibration_checkbox_change():
    """User toggles 'Load Calibration on Startup'."""
    save_settings()

def on_startup_file_change(*args):
    """
    Called whenever user manually edits the startup file path Entry.
    Just saving config so it persists.
    """
    save_settings()

def on_browse_startup_file():
    """User clicked 'Browse' to pick a startup calibration CSV."""
    file_path = filedialog.askopenfilename(
        title="Select Startup Calibration CSV",
        filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
    )
    if file_path:
        startup_calibration_file_path_var.set(file_path)
        save_settings()

# --------------------------
# System Tray
# --------------------------
def create_tray_image():
    icon_path = resource_path("data/icon_drift_guard_main.ico")
    try:
        image = Image.open(icon_path)
        return image
    except Exception as e:
        print(f"Failed to load icon: {e}")
        fallback_img = Image.new('RGB', (64, 64), color="#444444")
        d = ImageDraw.Draw(fallback_img)
        d.text((8, 25), "DG", fill="white")
        return fallback_img

def on_tray_show(icon, item):
    icon.stop()
    root.after(0, root.deiconify)

def on_tray_exit(icon, item):
    icon.stop()
    root.after(0, really_quit_app)

def run_tray():
    global tray_icon
    image = create_tray_image()
    menu = pystray.Menu(
        pystray.MenuItem("Show", on_tray_show),
        pystray.MenuItem("Exit", on_tray_exit)
    )
    tray_icon = pystray.Icon("Driftguard", image, "Driftguard Calibration Utility", menu)
    tray_icon.run()

def hide_window_to_tray():
    root.withdraw()
    tray_thread = threading.Thread(target=run_tray, daemon=True)
    tray_thread.start()

# --------------------------
# Close / Quit
# --------------------------
def on_close():
    really_quit_app()

def really_quit_app():
    global joystick_thread_running

    joystick_thread_running = False
    if joystick_thread and joystick_thread.is_alive():
        joystick_thread.join(timeout=2.0)

    pygame.quit()

    if tray_icon:
        tray_icon.stop()

    root.quit()
    root.destroy()

def on_minimize(event):
    # If the user manually minimizes, go to tray
    if root.state() == "iconic":
        hide_window_to_tray()

# --------------------------
# Find / Filter Connected Joysticks
# --------------------------
def list_connected_gamepads():
    """
    Enumerate all HID devices that match the usage page for gamepads/joysticks,
    but only return those that are truly responsive (i.e., not ghost devices).
    Returns a list of (VID_hex, PID_hex, path).
    """
    connected_devices = []
    try:
        all_devices = hid.enumerate()
    except Exception as e:
        print(f"Error enumerating HID devices: {e}")
        return connected_devices

    for dev in all_devices:
        # Filter: usage_page=0x01 (generic desktop), usage=0x04 or 0x05
        if (dev["usage_page"] == GAMEPAD_USAGE_PAGE and
            dev["usage"] in (JOYSTICK_USAGE, GAMEPAD_USAGE)):

            dev_path = dev["path"]
            if utils_hid.is_device_responsive(dev_path):
                vid_hex = f"{dev['vendor_id']:04X}"
                pid_hex = f"{dev['product_id']:04X}"
                connected_devices.append((vid_hex, pid_hex, dev_path))

    print(f"Connected gamepads: {connected_devices}")
    return connected_devices

def find_supported_sony_controller():
    """
    1) Get the list of currently connected, responsive gamepads.
    2) Filter so we only keep the ones in PS_SUPPORTED_DEVICES.
    3) Return the first match as (vid, pid, path) or None if none found.
    """
    candidates = list_connected_gamepads()
    for vid_hex, pid_hex, dev_path in candidates:
        if (vid_hex, pid_hex) in PS_SUPPORTED_DEVICES:
            return (vid_hex, pid_hex, dev_path)
    return None

def find_device_path(vid_pid):
    """Return the HID device path for the given (vid, pid) tuple, if found."""
    vid, pid = vid_pid
    try:
        all_devices = hid.enumerate()
        for dev in all_devices:
            vid_hex = f"{dev['vendor_id']:04X}"
            pid_hex = f"{dev['product_id']:04X}"
            if (vid_hex, pid_hex) == (vid, pid):
                return dev["path"]
    except Exception as e:
        print(f"Error enumerating for path: {e}")
    return None

def check_sony_usb_bt_if_applicable(dev_path, pid_hex):
    """
    For DualSense or DualSense Edge:
    Attempt to read a feature report to determine USB vs BT.
    Sets 'ps_controller_conn_type' global accordingly.
    """
    global ps_controller_conn_type
    if joystick_vid_pid in PS_SUPPORTED_DEVICES:
        dev_path = find_device_path(joystick_vid_pid)
        if not dev_path:
            ps_controller_conn_type = ""
            return

        try:
            data = utils_hid.hid_get_feature_report(dev_path, 0x83, 64)
            if data and len(data) > 61:
                # If the sum of bytes [60] + [61] > 0 => BT
                if data[60] + data[61] > 0:
                    ps_controller_conn_type = "(BT)"
                else:
                    ps_controller_conn_type = "(USB)"
            else:
                ps_controller_conn_type = "(Unknown)"
        except Exception:
            ps_controller_conn_type = "(Unknown)"
    else:
        ps_controller_conn_type = ""

# --------------------------
# Joystick Background Thread
# --------------------------
def joystick_background_loop():
    """
    Repeatedly checks if there's a supported Sony controller connected.
    If we find one, init it with Pygame, read axes, etc.
    If it's disconnected, we reset and look again.
    """
    global joystick, joystick_axes, is_joystick_connected
    global joystick_thread_running, device_detect_fail_count
    global joystick_vid_pid, active_dev_path

    fps = 1.0 / 60.0

    while joystick_thread_running:
        time.sleep(fps)
        pygame.event.pump()

        count = pygame.joystick.get_count()

        # CASE A: No active joystick yet, but Pygame sees at least one
        if count > 0 and not is_joystick_connected:
            result = find_supported_sony_controller()
            if result:
                vid_hex, pid_hex, dev_path = result
                joystick_vid_pid = (vid_hex, pid_hex)
                active_dev_path = dev_path

                # USB vs BT check
                check_sony_usb_bt_if_applicable(dev_path, pid_hex)

                # Mark as connected
                is_joystick_connected = True
                device_detect_fail_count = 0

                try:
                    joystick_obj = pygame.joystick.Joystick(0)
                    joystick_obj.init()
                    joystick = joystick_obj
                except pygame.error as e:
                    log_to_terminal(f"Error initializing joystick: {e}")
                    is_joystick_connected = False
            else:
                device_detect_fail_count += 1
                if device_detect_fail_count >= 3:
                    device_detect_fail_count = 0

        elif count == 0 and is_joystick_connected:
            is_joystick_connected = False
            device_detect_fail_count = 0

        # CASE C: Read axes if we do have a joystick
        if joystick and is_joystick_connected:
            try:
                axes_count = joystick.get_numaxes()
                lx, ly, rx, ry, lt, rt = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
                if axes_count >= 2:
                    lx = joystick.get_axis(0)
                    ly = joystick.get_axis(1)
                if axes_count >= 4:
                    rx = joystick.get_axis(2)
                    ry = joystick.get_axis(3)
                if axes_count >= 6:
                    lt = joystick.get_axis(4)
                    rt = joystick.get_axis(5)

                joystick_axes = (lx, ly, rx, ry, lt, rt)
            except pygame.error as e:
                log_to_terminal(f"Error reading joystick: {e}")
                joystick = None
                is_joystick_connected = False

# --------------------------
# Start Joystick Thread
# --------------------------
def start_joystick_thread():
    global joystick_thread, joystick_thread_running
    joystick_thread_running = True
    joystick_thread = threading.Thread(target=joystick_background_loop, daemon=True)
    joystick_thread.start()

# --------------------------
# Calibration / Serial
# --------------------------
def get_serial(controller_name):
    if not is_joystick_connected:
        return "Controller not connected."

    if "DualSense" in controller_name:
        try:
            if active_dev_path:
                utils_hid.hid_set_feature_report(active_dev_path, 0x80, [0x01, 0x13, 0x01])
                serial_list = utils_hid.hid_get_feature_report(active_dev_path, 0x81, 64)
                if not serial_list:
                    return "Serial not found."

                serial_bytes = bytes(serial_list)
                serial_hex = serial_bytes.hex()[8:42]

                if serial_hex:
                    try:
                        serial_decoded = bytes.fromhex(serial_hex).decode("ascii", errors="ignore")
                        return serial_decoded.strip().upper()
                    except Exception as e:
                        print(f"Failed to decode Serial: {e}")
                        return "Failed to decode Serial."
                else:
                    return "Serial not found."
            else:
                return "Device path not found."
        except Exception as e:
            return f"Error obtaining Serial: {e}"
    else:
        return "Not available"

def get_calibration_from_ds(controller_name):
    if not is_joystick_connected:
        return "Controller not connected."

    if "DualSense" in controller_name:
        try:
            if active_dev_path:
                utils_hid.hid_set_feature_report(active_dev_path, 0x80, [0x0C, 0x04, 0x00])
                calib_list = utils_hid.hid_get_feature_report(active_dev_path, 0x81, 64)
                if not calib_list:
                    return "Calib not found."

                serial_bytes = bytes(calib_list)
                calib_hex = serial_bytes.hex()[0:64]

                if calib_hex:
                    try:
                        return calib_hex.upper()
                    except Exception as e:
                        print(f"Failed to decode calib: {e}")
                        return "Failed to decode calib."
                else:
                    return "Calib not found."
            else:
                return "Device path not found."
        except Exception as e:
            return f"Error obtaining calibration: {e}"
    else:
        return "Not available"

def read_calibration_from_controller():
    if joystick and is_joystick_connected:
        controller_name = joystick.get_name()
    else:
        controller_name = "No Controller Detected"

    serial_number = get_serial(controller_name)
    calibration_hex = get_calibration_from_ds(controller_name)

    calibration_data = []
    if isinstance(calibration_hex, str) and len(calibration_hex) > 0:
        try:
            raw_bytes = bytes.fromhex(calibration_hex)
            raw_bytes = raw_bytes[4:]  # skip first 4 bytes if needed
            calibration_data = list(raw_bytes)
        except ValueError:
            calibration_data = []
    
    return serial_number, calibration_data, controller_name

def apply_calibration_to_controller(calibration_data):
    if not is_joystick_connected or not active_dev_path:
        messagebox.showerror("Error", "No device connected or active device path not found.")
        return
    try:
        if ps_controller_conn_type != "(BT)":
            try:
                report_id = 0x80
                payload = [0x0C, 0x01] + calibration_data
                utils_hid.hid_set_feature_report(active_dev_path, report_id, payload)
                log_to_terminal("Calibration data applied successfully.")
            except Exception as e:
                log_to_terminal(f"Error applying calibration data: {e}")
        else:
            log_to_terminal("Calibration not supported when using Bluetooth.")
    except Exception as e:
        log_to_terminal(f"Error applying calibration data: {e}")

def load_calibration():
    file_path = filedialog.askopenfilename(
        title="Select Calibration CSV File",
        filetypes=[("CSV Files", "*.csv")]
    )
    if not file_path:
        return
    load_calibration_from_file(file_path)

def load_calibration_from_file(file_path):
    try:
        with open(file_path, newline='') as csvfile:
            reader = csv.reader(csvfile)
            header = next(reader)
            data = next(reader)
            serial_number = data[0]
            if len(data) >= 3:
                controller_name = data[1]
                calibration_str = data[2]
            elif len(data) == 2:
                controller_name = "Unknown"
                calibration_str = data[1]
            else:
                raise ValueError("CSV file format is incorrect.")

            calibration_data = ast.literal_eval(calibration_str)

            log_to_terminal(
                f"Loaded Calibration:\n"
                f"Serial Number: {serial_number}\n"
                f"Controller: {controller_name}\n"
                f"Calibration Data: {calibration_data}\n"
            )
            apply_calibration_to_controller(calibration_data)

    except Exception as e:
        messagebox.showerror("Error", f"Failed to load calibration file:\n{e}")

def save_calibration():
    serial_number, calibration_data, controller_name = read_calibration_from_controller()
    calibration_str = str(calibration_data)
    file_path = filedialog.asksaveasfilename(
        title="Save Calibration CSV File",
        defaultextension=".csv",
        filetypes=[("CSV Files", "*.csv")]
    )
    if not file_path:
        return
    try:
        with open(file_path, mode="w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Serial Number", "Controller", "Calibration Data"])
            writer.writerow([serial_number, controller_name, calibration_str])
        messagebox.showinfo("Success", "Calibration saved successfully!")
        log_to_terminal("Calibration saved successfully!")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to save calibration file:\n{e}")

# --------------------------
# Autoload Calibration on Startup
# --------------------------
def auto_load_calibration_on_startup():
    """
    If autoload_calibration_var is True, load from the user-specified path
    in 'startup_calibration_file_path_var'.
    """
    if autoload_calibration_var.get():
        log_to_terminal("Autoload Calibration is enabled. Attempting to load startup calibration...")
        startup_path = startup_calibration_file_path_var.get()
        if os.path.exists(startup_path):
            load_calibration_from_file(startup_path)
        else:
            log_to_terminal(f"Startup calibration file not found: {startup_path}")

# --------------------------
# Controller Status (GUI label)
# --------------------------
def update_controller_status():
    if is_joystick_connected:
        name = joystick.get_name() if joystick else "Unknown"
        # If recognized Sony device => add USB/BT info
        if joystick_vid_pid in PS_SUPPORTED_DEVICES and ps_controller_conn_type:
            name += f" {ps_controller_conn_type}"
        controller_status_label.config(text=f"Connected Controller:\n{name}")
    else:
        controller_status_label.config(text="Connected Controller:\nNone")
    root.after(1000, update_controller_status)

# --------------------------
# Analog Stick Drawing
# --------------------------
def draw_analog_sticks():
    analog_canvas.delete("all")
    if joystick and is_joystick_connected:
        left_x, left_y, right_x, right_y, _, _ = joystick_axes
        w = analog_canvas.winfo_width()
        h = analog_canvas.winfo_height()
        if w < 10:
            w = 300
        if h < 10:
            h = 200

        left_center = (w // 4, h // 2)
        right_center = (3 * w // 4, h // 2)
        radius = min(w, h) // 6

        # Left circle
        x0_l = left_center[0] - radius
        y0_l = left_center[1] - radius
        x1_l = left_center[0] + radius
        y1_l = left_center[1] + radius
        analog_canvas.create_oval(x0_l, y0_l, x1_l, y1_l,
                                  outline=COLOR_HIGHLIGHT, width=2)
        analog_canvas.create_line(left_center[0], y0_l, left_center[0], y1_l,
                                  fill=COLOR_HIGHLIGHT, width=1)
        analog_canvas.create_line(x0_l, left_center[1], x1_l, left_center[1],
                                  fill=COLOR_HIGHLIGHT, width=1)

        # Right circle
        x0_r = right_center[0] - radius
        y0_r = right_center[1] - radius
        x1_r = right_center[0] + radius
        y1_r = right_center[1] + radius
        analog_canvas.create_oval(x0_r, y0_r, x1_r, y1_r,
                                  outline=COLOR_HIGHLIGHT, width=2)
        analog_canvas.create_line(right_center[0], y0_r, right_center[0], y1_r,
                                  fill=COLOR_HIGHLIGHT, width=1)
        analog_canvas.create_line(x0_r, right_center[1], x1_r, right_center[1],
                                  fill=COLOR_HIGHLIGHT, width=1)

        # Dot positions
        left_dot_x = left_center[0] + (left_x * radius)
        left_dot_y = left_center[1] + (left_y * radius)
        right_dot_x = right_center[0] + (right_x * radius)
        right_dot_y = right_center[1] + (right_y * radius)

        dot_size = 6
        # Left stick dot
        analog_canvas.create_oval(
            left_dot_x - dot_size/2, left_dot_y - dot_size/2,
            left_dot_x + dot_size/2, left_dot_y + dot_size/2,
            fill=COLOR_LEFT_DOT, outline=""
        )
        # Right stick dot
        analog_canvas.create_oval(
            right_dot_x - dot_size/2, right_dot_y - dot_size/2,
            right_dot_x + dot_size/2, right_dot_y + dot_size/2,
            fill=COLOR_RIGHT_DOT, outline=""
        )
    else:
        analog_canvas.create_text(
            analog_canvas.winfo_width() / 2,
            analog_canvas.winfo_height() / 2,
            text="No Joystick Connected",
            fill=COLOR_TEXT_DIM,
            font=("Arial", 14)
        )
    root.after(DRAW_INTERVAL_MS, draw_analog_sticks)

# --------------------------
# Main GUI Application
# --------------------------
def main():
    global root
    global terminal_text, analog_canvas, controller_status_label
    global autoload_checkbox_var, start_minimized_var
    global autoload_calibration_var, startup_calibration_file_path_var

    root = tk.Tk()
    root.withdraw()
    root.title("DriftGuard Calibration Utility")
    root.configure(bg=COLOR_BG_DARK)
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.bind("<Unmap>", on_minimize)

    # Center on screen
    window_width = 800
    window_height = 600
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    cx = int((sw - window_width) / 2)
    cy = int((sh - window_height) / 2)
    root.geometry(f"{window_width}x{window_height}+{cx}+{cy}")
    root.minsize(800, 600)
    root.resizable(False, False)

    # Optionally set icon
    icon_path = resource_path("data/icon_drift_guard_main.ico")
    try:
        root.iconbitmap(icon_path)
    except Exception as e:
        print(f"Icon not loaded: {e}")

    root.grid_rowconfigure(3, weight=1)
    root.grid_columnconfigure(0, weight=1)

    # Initialize variables
    autoload_checkbox_var = tk.BooleanVar(value=False)
    start_minimized_var = tk.BooleanVar(value=False)
    autoload_calibration_var = tk.BooleanVar(value=False)
    startup_calibration_file_path_var = tk.StringVar()  # new
    # We will read from config in load_settings()

    # Link changes in startup_calibration_file_path_var to auto-save
    startup_calibration_file_path_var.trace_add("write", on_startup_file_change)

    load_settings()

    # 1) Buttons Row
    button_frame = tk.Frame(root, bg=COLOR_BG_DARK)
    button_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
    button_inner_frame = tk.Frame(button_frame, bg=COLOR_BG_DARK)
    button_inner_frame.pack(anchor="center")

    load_button = tk.Button(
        button_inner_frame, text="Load Calibration",
        width=20, command=load_calibration,
        bg=COLOR_BUTTON_BG, fg=COLOR_TEXT_LIGHT,
        activebackground=COLOR_BUTTON_ACTIVE,
        activeforeground=COLOR_TEXT_LIGHT, bd=1
    )
    load_button.pack(side="left", padx=5)

    save_button = tk.Button(
        button_inner_frame, text="Save Calibration",
        width=20, command=save_calibration,
        bg=COLOR_BUTTON_BG, fg=COLOR_TEXT_LIGHT,
        activebackground=COLOR_BUTTON_ACTIVE,
        activeforeground=COLOR_TEXT_LIGHT, bd=1
    )
    save_button.pack(side="left", padx=5)

    # 2) Controller Status
    ctrl_status_frame = tk.Frame(root, bg=COLOR_BG_DARK)
    ctrl_status_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)

    controller_status_label = tk.Label(
        ctrl_status_frame,
        text="Connected Controller:\nNone",
        anchor="center",
        justify="center",
        bg=COLOR_BG_DARK,
        fg=COLOR_TEXT_LIGHT
    )
    controller_status_label.pack(padx=5, pady=5, expand=True)

    # 3) Main Content
    main_content_frame = tk.Frame(root, bg=COLOR_BG_DARK)
    main_content_frame.grid(row=3, column=0, sticky="nsew", padx=5, pady=5)
    main_content_frame.grid_columnconfigure(0, weight=1, minsize=250)
    main_content_frame.grid_columnconfigure(1, weight=1, minsize=250)
    main_content_frame.grid_columnconfigure(2, weight=1, minsize=250)

    # Left: Instructions
    instructions_frame = tk.Frame(main_content_frame, bd=2, relief="sunken",
                                  width=250, bg=COLOR_FRAME_DARK)
    instructions_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
    instructions_frame.grid_propagate(False)

    instructions_text = (
        "Instructions:\n"
        "Calibrate your controller first using:\n"
        " - DriftGuard: Gamepad Maintenance Tool (Steam)\n"
        " - DualShock Calibration GUI website:\n"
        "   https://dualshock-tools.github.io/\n"
        "\n"
        "1. 'Save Calibration' => save current data to CSV.\n"
        "2. 'Load Calibration' => load and apply a saved CSV.\n"
        "3. The center panel shows analog stick movement.\n"
        "4. The right panel is a terminal log.\n"
        "5. Works only with DualSense / DualSense Edge.\n"
        "6. You can set 'Load Calibration on Startup' and 'Autoload on Windows Start'.\n"
        "7. Use the text field below to specify your startup calibration file."
    )
    instructions_label = tk.Label(
        instructions_frame,
        text=instructions_text,
        justify="left",
        anchor="nw",
        bg=COLOR_FRAME_DARK,
        fg=COLOR_TEXT_LIGHT,
        wraplength=240  # or some appropriate pixel width
    )
    instructions_label.pack(fill="both", expand=True, padx=5, pady=5)

    # Center: Analog
    analog_frame = tk.Frame(main_content_frame, bd=2, relief="sunken",
                            width=250, bg=COLOR_FRAME_DARK)
    analog_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
    analog_frame.grid_propagate(False)

    global analog_canvas
    analog_canvas = tk.Canvas(
        analog_frame, bg=COLOR_CANVAS_BG,
        highlightthickness=0
    )
    analog_canvas.pack(fill="both", expand=True, padx=5, pady=5)

    # Right: Terminal
    terminal_frame = tk.Frame(main_content_frame, bd=2, relief="sunken",
                              width=250, bg=COLOR_FRAME_DARK)
    terminal_frame.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)
    terminal_frame.grid_propagate(False)

    global terminal_text
    terminal_text = tk.Text(
        terminal_frame, bg="#1E1E1E", fg=COLOR_TEXT_LIGHT,
        insertbackground=COLOR_TEXT_LIGHT,
        bd=0, highlightthickness=0
    )
    terminal_text.pack(side="left", fill="both", expand=True)

    term_scroll = tk.Scrollbar(terminal_frame, command=terminal_text.yview,
                               bg=COLOR_FRAME_DARK)
    term_scroll.pack(side="right", fill="y")
    terminal_text.config(yscrollcommand=term_scroll.set)

    # 4) Bottom Frame - Checkboxes + Startup File
    bottom_frame = tk.Frame(root, bg=COLOR_BG_DARK)
    bottom_frame.grid(row=4, column=0, sticky="ew", padx=5, pady=5)

    autoload_checkbox = tk.Checkbutton(
        bottom_frame,
        text="Autoload on Windows Start",
        variable=autoload_checkbox_var,
        command=on_autoload_checkbox_change,
        bg=COLOR_BG_DARK,
        fg=COLOR_TEXT_LIGHT,
        activebackground=COLOR_BG_DARK,
        activeforeground=COLOR_TEXT_LIGHT,
        selectcolor=COLOR_CHECK_SELECT
    )
    autoload_checkbox.pack(side="left", padx=5, pady=5)

    start_minimized_checkbox = tk.Checkbutton(
        bottom_frame,
        text="Start Minimized",
        variable=start_minimized_var,
        command=on_start_minimized_checkbox_change,
        bg=COLOR_BG_DARK,
        fg=COLOR_TEXT_LIGHT,
        activebackground=COLOR_BG_DARK,
        activeforeground=COLOR_TEXT_LIGHT,
        selectcolor=COLOR_CHECK_SELECT
    )
    start_minimized_checkbox.pack(side="left", padx=5, pady=5)

    autoload_calibration_checkbox = tk.Checkbutton(
        bottom_frame,
        text="Load Calibration on Startup",
        variable=autoload_calibration_var,
        command=on_autoload_calibration_checkbox_change,
        bg=COLOR_BG_DARK,
        fg=COLOR_TEXT_LIGHT,
        activebackground=COLOR_BG_DARK,
        activeforeground=COLOR_TEXT_LIGHT,
        selectcolor=COLOR_CHECK_SELECT
    )
    autoload_calibration_checkbox.pack(side="left", padx=5, pady=5)

    # Additional row for the startup calibration file path
    file_select_frame = tk.Frame(root, bg=COLOR_BG_DARK)
    file_select_frame.grid(row=5, column=0, sticky="ew", padx=5, pady=5)

    startup_file_label = tk.Label(
        file_select_frame,
        text="Startup Calibration File:",
        bg=COLOR_BG_DARK,
        fg=COLOR_TEXT_LIGHT
    )
    startup_file_label.pack(side="left", padx=5)

    startup_file_entry = tk.Entry(
        file_select_frame,
        textvariable=startup_calibration_file_path_var,
        width=50,
        bg=COLOR_FRAME_DARK,
        fg=COLOR_TEXT_LIGHT,
        insertbackground=COLOR_TEXT_LIGHT
    )
    startup_file_entry.pack(side="left", padx=5, fill="x", expand=True)

    browse_button = tk.Button(
        file_select_frame,
        text="Browse...",
        command=on_browse_startup_file,
        bg=COLOR_BUTTON_BG,
        fg=COLOR_TEXT_LIGHT,
        activebackground=COLOR_BUTTON_ACTIVE,
        activeforeground=COLOR_TEXT_LIGHT,
        bd=1
    )
    browse_button.pack(side="left", padx=5)

    # Periodic GUI updates
    root.after(1000, update_controller_status)
    root.after(DRAW_INTERVAL_MS, draw_analog_sticks)

    # Start joystick thread
    start_joystick_thread()

    # Start minimized?
    if start_minimized_var.get():
        hide_window_to_tray()
    else:
        root.deiconify()

    # If user wants to autoload calibration on startup
    # (Give it a short delay so Pygame/joystick init has time)
    root.after(2000, auto_load_calibration_on_startup)

    root.mainloop()

# --------------------------
# Entry Point
# --------------------------
if __name__ == "__main__":
    main()
