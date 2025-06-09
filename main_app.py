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
import cProfile
import pstats

# For Windows Registry autoload (only used on Windows)
if platform.system().lower().startswith('win'):
    import winreg

# For system tray integration
import pystray
from PIL import Image, ImageDraw

# HID packages
# import hid # No longer directly needed here, utils_hid encapsulates it
import utils_hid # Optimized HID utility module

# --------------------------
# Global Constants & Config
# --------------------------
CONFIG_FILE = "driftguard_config.json"
DRAW_INTERVAL_MS = 16  # ~60 FPS (was 32)
PROFILING_ENABLED = False # Set to True to enable cProfile on launch

PS_SUPPORTED_DEVICES = {
    ("054C", "0DF2"): "Sony DualSense Edge",
    # Add other supported VIDs/PIDs here if necessary
}

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
joystick = None # Pygame joystick object
joystick_axes = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
joystick_vid_pid = ("", "") # VID/PID of the connected controller
ps_controller_conn_type = "" # (BT), (USB), (Unknown)
is_joystick_connected = False # Overall connection status
joystick_thread = None
joystick_thread_running = False
root = None
terminal_text = None
analog_canvas = None
controller_status_label = None
autoload_checkbox_var = None
start_minimized_var = None
autoload_calibration_var = None
startup_calibration_file_path_var = None
active_dev_path = None # HID device path for utils_hid
device_detect_fail_count = 0 # Counter for detection failures

# Logging specific globals
early_log_messages = [] # For messages before GUI is ready
gui_ready_and_valid = False # Flag to indicate GUI state for logging

# --------------------------
# Utility & Config
# --------------------------
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def log_to_terminal(message):
    global gui_ready_and_valid # Indicate we are using the global flag
    current_time = time.strftime("%H:%M:%S", time.localtime())
    full_message = f"[{current_time}] {message}"

    if gui_ready_and_valid and terminal_text and terminal_text.winfo_exists():
        # If there are early messages, print them first
        if early_log_messages:
            for msg in early_log_messages:
                terminal_text.insert(tk.END, msg + "\n")
            early_log_messages.clear() # Clear the queue
        
        terminal_text.insert(tk.END, full_message + "\n")
        terminal_text.see(tk.END)
    elif not gui_ready_and_valid: # GUI not initialized yet
        early_log_messages.append(full_message)
        print("[Early Log] " + full_message) # Also print to console as fallback
    else: # GUI was ready but now is not (e.g., during shutdown)
        print("[Shutdown Log] " + full_message)


def load_settings():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
            autoload_checkbox_var.set(data.get("autoload", False))
            start_minimized_var.set(data.get("start_minimized", False))
            autoload_calibration_var.set(data.get("autoload_calibration", False))
            default_path = "startup_calibration.csv"
            startup_calibration_file_path_var.set(data.get("startup_calibration_file", default_path))
            log_to_terminal("Settings loaded successfully.")
        except Exception as e:
            log_to_terminal(f"Failed to load config: {e}")
    else:
        startup_calibration_file_path_var.set("startup_calibration.csv")
        log_to_terminal("Config file not found, using default startup calibration path.")


def threaded_load_settings():
    threading.Thread(target=load_settings, daemon=True).start()

def save_settings():
    data = {
        "autoload": autoload_checkbox_var.get(),
        "start_minimized": start_minimized_var.get(),
        "autoload_calibration": autoload_calibration_var.get(),
        "startup_calibration_file": startup_calibration_file_path_var.get(),
    }
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        log_to_terminal("Settings saved.")
    except Exception as e:
        log_to_terminal(f"Failed to save config: {e}")

def threaded_save_settings():
    threading.Thread(target=save_settings, daemon=True).start()

def set_autoload(enabled):
    if not platform.system().lower().startswith('win'):
        log_to_terminal("Autoload is only supported on Windows.")
        return

    app_name = "Driftguard Calibration Utility"
    # Ensure app_path is the executable if bundled, otherwise the script
    if getattr(sys, 'frozen', False):
        app_path = sys.executable
    else:
        app_path = os.path.abspath(sys.argv[0])

    try:
        key = winreg.HKEY_CURRENT_USER
        subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(key, subkey, 0, winreg.KEY_ALL_ACCESS) as regkey: # KEY_ALL_ACCESS
            if enabled:
                winreg.SetValueEx(regkey, app_name, 0, winreg.REG_SZ, f'"{app_path}"') # Add quotes for paths with spaces
                log_to_terminal(f"Autoload enabled: {app_path}")
            else:
                try:
                    winreg.DeleteValue(regkey, app_name)
                    log_to_terminal("Autoload disabled.")
                except FileNotFoundError:
                    log_to_terminal("Autoload was not set, no action taken to disable.")
                    pass # Value doesn't exist, which is fine
    except Exception as e:
        messagebox.showerror("Error", f"Failed to set autoload: {e}")
        log_to_terminal(f"Error setting autoload: {e}")


def on_autoload_checkbox_change():
    set_autoload(autoload_checkbox_var.get())
    threaded_save_settings()

def on_start_minimized_checkbox_change():
    threaded_save_settings()

def on_autoload_calibration_checkbox_change():
    threaded_save_settings()

def on_startup_file_change(*args):
    threaded_save_settings()

def on_browse_startup_file():
    file_path = filedialog.askopenfilename(
        title="Select Startup Calibration CSV",
        filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
    )
    if file_path:
        startup_calibration_file_path_var.set(file_path)
        # threaded_save_settings() # This will be called by trace on startup_calibration_file_path_var

def create_tray_image():
    icon_path = resource_path("data/icon_drift_guard_main.ico")
    try:
        return Image.open(icon_path)
    except Exception as e:
        log_to_terminal(f"Failed to load icon: {e}. Using fallback.")
        fallback_img = Image.new('RGB', (64, 64), color="#444444")
        # Simple text drawing, consider using a specific font for better Pillow text rendering
        d = ImageDraw.Draw(fallback_img)
        try:
            from PIL import ImageFont
            font = ImageFont.truetype("arial.ttf", 30) # Example, ensure font is available
            d.text((10, 15), "DG", fill="white", font=font)
        except ImportError: # Fallback if specific font fails
            d.text((10, 20), "DG", fill="white") # Default font, size might not be controllable like this
        return fallback_img

def on_tray_show(icon, item):
    if tray_icon: # Check if tray_icon object exists
      icon.stop()
    if root:
      root.after(0, root.deiconify)

def on_tray_exit(icon, item):
    if tray_icon:
      icon.stop()
    if root:
      root.after(0, really_quit_app)

def run_tray_icon():
    global tray_icon
    image = create_tray_image()
    menu = pystray.Menu(
        pystray.MenuItem("Show", on_tray_show, default=True), # Make "Show" default on double click
        pystray.MenuItem("Exit", on_tray_exit)
    )
    tray_icon = pystray.Icon("Driftguard", image, "Driftguard Calibration Utility", menu)
    # log_to_terminal("System tray icon running.") # This might be too early for GUI log
    print("[Info] System tray icon thread starting.")
    tray_icon.run() # This is blocking, so it runs in its own thread.
    print("[Info] System tray icon thread finished.")


def hide_window_to_tray():
    if root:
      root.withdraw()
    # Start tray icon in a separate thread only if not already running or visible
    # This logic helps prevent multiple tray icons if hide_window_to_tray is called multiple times
    # A more robust check might involve checking if the tray_icon.run() thread is alive.
    if not tray_icon or not tray_icon.HAS_NOTIFICATION: # HAS_NOTIFICATION is a simple proxy for "is it active"
        log_to_terminal("Hiding window to system tray.")
        threading.Thread(target=run_tray_icon, daemon=True).start()
    else:
        log_to_terminal("Window hidden, tray icon already active or being activated.")


def on_close_window(): # Renamed from on_close to avoid conflict
    # Ask user if they want to minimize to tray or exit
    if messagebox.askyesno("Exit or Minimize?",
                           "Do you want to close DriftGuard or minimize it to the system tray?\n\n"
                           "Yes = Minimize to Tray\nNo = Exit Application",
                           icon='question'):
        hide_window_to_tray()
    else:
        really_quit_app()


def really_quit_app():
    global joystick_thread_running, root, tray_icon, gui_ready_and_valid # Add gui_ready_and_valid

    gui_ready_and_valid = False # GUI is being shut down, redirect logs to console

    log_to_terminal("Initiating application shutdown...")

    joystick_thread_running = False
    if joystick_thread and joystick_thread.is_alive():
        log_to_terminal("Waiting for joystick thread to terminate...")
        joystick_thread.join(timeout=1.0) # Wait for the thread to finish
        if joystick_thread.is_alive():
            log_to_terminal("Joystick thread did not terminate in time.")

    # Close any open HID devices managed by utils_hid
    utils_hid.close_all_hid_devices()
    log_to_terminal("All HID devices closed.")

    pygame.joystick.quit()
    pygame.quit()
    log_to_terminal("Pygame quit.")

    if tray_icon:
        log_to_terminal("Stopping tray icon...")
        try:
            tray_icon.stop()
        except Exception as e:
            log_to_terminal(f"Error stopping tray icon: {e}")
        tray_icon = None # Clear the reference
    
    if root:
        log_to_terminal("Destroying Tkinter root window...")
        try:
            # root.quit() # Stops mainloop, might already be stopped or stopping
            root.destroy() # Destroys window and widgets
            root = None # Clear the reference
            log_to_terminal("Tkinter root window destroyed.")
        except tk.TclError as e:
            log_to_terminal(f"Error during Tkinter cleanup (already destroyed?): {e}")
        except Exception as e:
            log_to_terminal(f"Unexpected error during Tkinter cleanup: {e}")
    
    log_to_terminal("Application shutdown complete.")
    # sys.exit(0) # Usually not needed, but can ensure exit if other non-daemon threads are running.


def on_minimize_window(event): # Renamed from on_minimize
    if root and root.state() == "iconic": # Iconic means minimized
        hide_window_to_tray()

def list_hid_gamepads(): # Renamed from list_connected_gamepads for clarity
    """Lists HID gamepads that are also responsive."""
    connected_devices = []
    try:
        # hid.enumerate() can be slow if called very frequently.
        # Consider rate-limiting its calls if performance issues arise here.
        all_devices = utils_hid.hid.enumerate() # Access hid via utils_hid if you re-export
        for dev_info in all_devices:
            # Check for gamepad/joystick usage page and usage
            if dev_info["usage_page"] == GAMEPAD_USAGE_PAGE and \
               dev_info["usage"] in (JOYSTICK_USAGE, GAMEPAD_USAGE):
                dev_path = dev_info["path"]
                # Check responsiveness before adding
                if utils_hid.is_device_responsive(dev_path, tries=1, delay=0.01): # Quick check
                    vid_hex = f"{dev_info['vendor_id']:04X}"
                    pid_hex = f"{dev_info['product_id']:04X}"
                    product_name = dev_info.get('product_string', 'Unknown Device')
                    connected_devices.append({'vid': vid_hex, 'pid': pid_hex, 'path': dev_path, 'name': product_name})
    except Exception as e:
        log_to_terminal(f"Error enumerating HID devices: {e}")
    return connected_devices

def find_supported_sony_controller_hid(): # Renamed for clarity
    """Finds the first supported Sony controller via HID and returns its info."""
    gamepads = list_hid_gamepads()
    for dev in gamepads:
        if (dev['vid'], dev['pid']) in PS_SUPPORTED_DEVICES:
            log_to_terminal(f"Supported Sony HID device found: {dev['name']} ({dev['vid']}:{dev['pid']}) at {dev['path']}")
            return dev # Returns dict: {'vid', 'pid', 'path', 'name'}
    return None

def check_sony_controller_connection_type(dev_path_to_check): # Renamed & takes path
    global ps_controller_conn_type
    if not dev_path_to_check:
        ps_controller_conn_type = ""
        return

    # This assumes the device is already opened via open_hid_device if calls are frequent
    # The report 0x83 might be specific to DualSense Edge or certain firmware.
    # For DualSense, 0x04 (or 0xA3 for extended reports) might be more common for BT state.
    # This part needs careful validation against actual device behavior.
    try:
        # DualSense Edge specific report for connection type (example)
        # Report ID 0x83, expecting at least 62 bytes for connection status at byte 60, 61.
        # This is an example, actual report structure needs verification.
        data = utils_hid.hid_get_feature_report(dev_path_to_check, 0x83, 64)

        if data and len(data) > 61:
            # This specific check (data[60] + data[61] > 0 for BT) needs verification for DualSense Edge
            # It might be from a specific SDK or reverse engineering.
            if data[60] + data[61] > 0: # Example condition for BT
                ps_controller_conn_type = "(BT)"
            else:
                ps_controller_conn_type = "(USB)"
        else:
            # print(f"Debug: Report 0x83 data for conn type: {bytes(data).hex() if data else 'None'}")
            ps_controller_conn_type = "(Unknown)" # If report is not as expected
    except Exception as e:
        # log_to_terminal(f"Error checking PS controller connection type via HID: {e}")
        ps_controller_conn_type = "(Error)" # If HID call fails


def joystick_background_loop():
    global joystick, joystick_axes, is_joystick_connected
    global joystick_thread_running, device_detect_fail_count
    global joystick_vid_pid, active_dev_path, ps_controller_conn_type

    polling_interval = 1.0 / 120.0  # Target ~120 FPS for axis updates
    last_hid_check_time = 0
    hid_check_interval = 2.0 # Seconds, how often to run list_hid_gamepads if not connected

    while joystick_thread_running:
        loop_start_time = time.perf_counter()
        pygame.event.pump() # Essential for Pygame internal state

        if not is_joystick_connected:
            # Try to find and connect to a joystick
            if time.perf_counter() - last_hid_check_time > hid_check_interval:
                last_hid_check_time = time.perf_counter()
                supported_hid_device = find_supported_sony_controller_hid()

                if supported_hid_device:
                    active_dev_path_candidate = supported_hid_device['path']
                    candidate_vid_pid = (supported_hid_device['vid'], supported_hid_device['pid'])
                    
                    # Attempt to open the HID device first
                    if utils_hid.open_hid_device(active_dev_path_candidate):
                        active_dev_path = active_dev_path_candidate
                        joystick_vid_pid = candidate_vid_pid

                        # Now try to initialize the corresponding Pygame joystick
                        pygame.joystick.quit() # Reset Pygame joysticks
                        pygame.joystick.init() # Re-initialize
                        
                        found_pygame_joystick = False
                        for i in range(pygame.joystick.get_count()):
                            try:
                                temp_joystick = pygame.joystick.Joystick(i)
                                temp_joystick.init()
                                # Simplistic check: name contains "DualSense" or "Wireless Controller"
                                # Or check if Pygame GUID contains VID/PID (platform dependent)
                                pygame_joystick_name = temp_joystick.get_name().lower()
                                # pygame_guid = temp_joystick.get_guid() # May need parsing

                                if "edge" in pygame_joystick_name or \
                                   (joystick_vid_pid[0].lower() in pygame_joystick_name and \
                                    joystick_vid_pid[1].lower() in pygame_joystick_name): # Basic name check
                                    joystick = temp_joystick
                                    log_to_terminal(f"Pygame joystick '{joystick.get_name()}' (Index {i}) matched and initialized.")
                                    found_pygame_joystick = True
                                    break
                                else:
                                    temp_joystick.quit() # Quit if not the one
                            except pygame.error as e:
                                log_to_terminal(f"Error initializing Pygame joystick at index {i}: {e}")
                        
                        if found_pygame_joystick:
                            is_joystick_connected = True
                            device_detect_fail_count = 0
                            check_sony_controller_connection_type(active_dev_path) # Check connection type
                            log_to_terminal(f"Controller '{joystick.get_name()}' {ps_controller_conn_type} connected. VID/PID: {joystick_vid_pid[0]}:{joystick_vid_pid[1]}. Path: {active_dev_path}")
                        else:
                            log_to_terminal("Supported HID device found, but failed to match/initialize a Pygame joystick.")
                            utils_hid.close_hid_device(active_dev_path) # Close HID if Pygame part failed
                            active_dev_path = None
                            joystick_vid_pid = ("", "")
                    else:
                        log_to_terminal(f"Found supported HID device {supported_hid_device['name']} but failed to open its path: {active_dev_path_candidate}")
                        active_dev_path = None # Ensure it's None
                else: # No supported HID device found
                    device_detect_fail_count +=1
                    if device_detect_fail_count % 15 == 1: # Log less frequently (e.g. every 30s if interval is 2s)
                         log_to_terminal(f"No supported controller detected (attempt {device_detect_fail_count}). Ensure it's connected.")
        else: # is_joystick_connected is True
            if not joystick or not active_dev_path or not utils_hid.is_device_responsive(active_dev_path, tries=1, delay=0.01):
                log_to_terminal(f"Controller '{joystick.get_name() if joystick else 'N/A'}' disconnected or unresponsive.")
                if active_dev_path:
                    utils_hid.close_hid_device(active_dev_path)
                if joystick:
                    joystick.quit()
                is_joystick_connected = False
                joystick = None
                active_dev_path = None
                joystick_vid_pid = ("", "")
                ps_controller_conn_type = ""
                joystick_axes = (0.0,) * 6 # Reset axes
                continue # Skip to next loop iteration to attempt reconnection

            try:
                axes_count = joystick.get_numaxes()
                lx = joystick.get_axis(0) if axes_count >= 1 else 0.0
                ly = joystick.get_axis(1) if axes_count >= 2 else 0.0
                rx = joystick.get_axis(2) if axes_count >= 3 else 0.0 
                ry = joystick.get_axis(3) if axes_count >= 4 else 0.0
                lt = joystick.get_axis(4) if axes_count >= 5 else 0.0 
                rt = joystick.get_axis(5) if axes_count >= 6 else 0.0 
                joystick_axes = (lx, ly, rx, ry, lt, rt)
            except pygame.error as e:
                log_to_terminal(f"Error reading joystick axes: {e}. Marking as disconnected.")
                if active_dev_path: utils_hid.close_hid_device(active_dev_path)
                if joystick: joystick.quit()
                is_joystick_connected = False
                joystick = None
                active_dev_path = None
                joystick_axes = (0.0,) * 6

        # Precise sleep
        elapsed_time = time.perf_counter() - loop_start_time
        sleep_duration = polling_interval - elapsed_time
        if sleep_duration > 0:
            time.sleep(sleep_duration)

def start_joystick_thread():
    global joystick_thread, joystick_thread_running
    if joystick_thread and joystick_thread.is_alive():
        log_to_terminal("Joystick thread already running.")
        return
    joystick_thread_running = True
    joystick_thread = threading.Thread(target=joystick_background_loop, daemon=True)
    joystick_thread.start()
    log_to_terminal("Joystick monitoring thread started.")

def get_controller_serial(): # Renamed from get_serial
    if not is_joystick_connected or not active_dev_path:
        log_to_terminal("Get Serial: Controller not connected or no active HID path.")
        return "Controller not connected."
    if joystick_vid_pid not in PS_SUPPORTED_DEVICES: # Check against known VID/PID
        log_to_terminal("Get Serial: Not a supported Sony controller for this feature.")
        return "Not available (Unsupported Device)"

    try:
        set_success = utils_hid.hid_set_feature_report(active_dev_path, 0x80, [0x01, 0x13, 0x01])
        if not set_success:
            log_to_terminal("Get Serial: Failed to send request for serial.")
            return "Serial request failed."

        time.sleep(0.05) # Small delay

        serial_list = utils_hid.hid_get_feature_report(active_dev_path, 0x81, 64)
        if not serial_list:
            log_to_terminal("Get Serial: No response or empty data for serial.")
            return "Serial not found (no data)."

        if serial_list[0] != 0x81: # Validate report ID
             log_to_terminal(f"Get Serial: Expected report ID 0x81, got {serial_list[0]}.")
             return "Serial not found (wrong report)."
        
        full_report_hex = bytes(serial_list).hex()
        # Original slicing [8:42] means hex chars from index 8 up to (but not including) 42.
        # This corresponds to byte indices 4 through 20 ( (8/2) to (42/2 - 1) ).
        # So, 17 bytes: data_bytes[4], data_bytes[5], ..., data_bytes[20].
        serial_hex_segment = full_report_hex[8:42] 

        if serial_hex_segment:
            try:
                # Ensure the segment length is even for bytes.fromhex
                if len(serial_hex_segment) % 2 != 0:
                    log_to_terminal(f"Get Serial: Extracted hex segment has odd length: '{serial_hex_segment}'")
                    return "Serial not found (hex format error)."

                decoded_serial = bytes.fromhex(serial_hex_segment).decode("ascii", errors="ignore").strip().upper()
                if decoded_serial:
                    log_to_terminal(f"Serial Number: {decoded_serial}")
                    return decoded_serial
                else:
                    log_to_terminal("Get Serial: Decoded serial is empty.")
                    return "Serial not found (empty)."
            except ValueError as e:
                log_to_terminal(f"Get Serial: Error decoding serial hex '{serial_hex_segment}': {e}")
                return "Serial not found (decode error)."
        else:
            log_to_terminal("Get Serial: Extracted serial hex segment is empty.")
            return "Serial not found (no segment)."
    except Exception as e:
        log_to_terminal(f"Error obtaining Serial: {e}")
        return f"Error obtaining Serial: {type(e).__name__}"


def get_calibration_data_from_ds(): # Renamed
    if not is_joystick_connected or not active_dev_path:
        log_to_terminal("Get Calib: Controller not connected.")
        return None 
    if joystick_vid_pid not in PS_SUPPORTED_DEVICES:
        log_to_terminal("Get Calib: Not a supported Sony controller for this feature.")
        return None

    try:
        set_payload = [0x0C, 0x04, 0x00] # Request for calibration data
        set_success = utils_hid.hid_set_feature_report(active_dev_path, 0x80, set_payload)
        if not set_success:
            log_to_terminal("Get Calib: Failed to send request for calibration data.")
            return None

        time.sleep(0.05) # Small delay

        calib_report = utils_hid.hid_get_feature_report(active_dev_path, 0x81, 64) 
        if not calib_report:
            log_to_terminal("Get Calib: No response or empty data for calibration.")
            return None
        
        if calib_report[0] != 0x81: 
            log_to_terminal(f"Get Calib: Expected report ID 0x81, got {calib_report[0]}.")
            return None

        # Original code used: calibration_data = list(raw_bytes[4:])
        # where raw_bytes was from bytes.fromhex(calib_hex[0:64]).
        # This means it used bytes 4 through 31 of the *full report*.
        # calib_report is already a list of integers (bytes).
        if len(calib_report) >= 32: 
            calibration_payload = list(calib_report[4:32]) # Bytes 4 to 31 of the full report.
            log_to_terminal(f"Raw calibration payload (bytes 4-31 of report): {calibration_payload}")
            return calibration_payload
        else:
            log_to_terminal(f"Get Calib: Report too short ({len(calib_report)} bytes, expected >=32).")
            return None

    except Exception as e:
        log_to_terminal(f"Error obtaining calibration data: {e}")
        return None

def read_calibration_from_controller():
    controller_name_str = "No Controller"
    if joystick and is_joystick_connected:
        controller_name_str = joystick.get_name()
        if ps_controller_conn_type:
            controller_name_str += f" {ps_controller_conn_type}"

    serial_str = get_controller_serial() 

    calibration_byte_list = get_calibration_data_from_ds()

    if calibration_byte_list is None:
        log_to_terminal("Failed to read calibration data from controller for CSV.")
        return serial_str, [], controller_name_str # Return empty list for data if failed

    log_to_terminal(f"Successfully read calibration data for CSV: {calibration_byte_list}")
    return serial_str, calibration_byte_list, controller_name_str


def apply_calibration_to_controller(calibration_data_list): 
    if not is_joystick_connected or not active_dev_path:
        messagebox.showerror("Error", "No device connected or active device path not found.")
        log_to_terminal("Apply Calib: No device connected.")
        return False
    if ps_controller_conn_type == "(BT)":
        log_to_terminal("Calibration writing not supported when using Bluetooth.")
        messagebox.showwarning("Bluetooth Mode", "Calibration writing is not supported over Bluetooth.")
        return False
    if not isinstance(calibration_data_list, list):
        log_to_terminal(f"Apply Calib: Invalid data format (expected list, got {type(calibration_data_list)}).")
        messagebox.showerror("Error", "Invalid calibration data format.")
        return False

    try:
        report_id = 0x80
        # Ensure calibration_data_list contains only integers (bytes)
        payload = [0x0C, 0x01] + [int(b) for b in calibration_data_list]

        log_to_terminal(f"Applying calibration data (len {len(calibration_data_list)}): {payload}") # Log full payload
        success = utils_hid.hid_set_feature_report(active_dev_path, report_id, payload)
        if success:
            log_to_terminal("Calibration data applied successfully to controller.")
            messagebox.showinfo("Success", "Calibration data applied successfully!")
            return True
        else:
            log_to_terminal("Failed to apply calibration data to controller (set_feature_report failed).")
            messagebox.showerror("Error", "Failed to apply calibration (HID write error).")
            return False
    except Exception as e:
        log_to_terminal(f"Error applying calibration data: {e}")
        messagebox.showerror("Error", f"Exception applying calibration:\n{e}")
        return False

def load_calibration_and_apply(): 
    file_path = filedialog.askopenfilename(
        title="Select Calibration CSV File",
        filetypes=[("CSV Files", "*.csv")]
    )
    if file_path:
        load_calibration_from_file(file_path, apply_to_controller=True)

def load_calibration_from_file(file_path, apply_to_controller=False):
    log_to_terminal(f"Loading calibration from: {file_path}")
    try:
        with open(file_path, newline='') as csvfile:
            reader = csv.reader(csvfile)
            header = next(reader) 
            if not header or header[0].lower() != "serial number": 
                raise ValueError("CSV file does not appear to be a valid calibration file (header mismatch).")
            
            data_row = next(reader)
            serial_number = data_row[0]
            controller_name = data_row[1] if len(data_row) > 1 else "Unknown"
            calibration_data_str = data_row[2] if len(data_row) > 2 else data_row[1] # Fallback

            try:
                calibration_data_list = ast.literal_eval(calibration_data_str)
                if not isinstance(calibration_data_list, list):
                    raise ValueError("Parsed calibration data is not a list.")
            except (ValueError, SyntaxError) as e:
                log_to_terminal(f"Error parsing calibration data from CSV: {e} - Data was: '{calibration_data_str}'")
                messagebox.showerror("Error", f"Invalid calibration data format in CSV:\n{e}")
                return

            log_to_terminal(
                f"Loaded Calibration from '{os.path.basename(file_path)}':\n"
                f"  Serial: {serial_number}\n"
                f"  Controller: {controller_name}\n"
                f"  Data (first 10 bytes): {calibration_data_list[:10]}..."
            )
            if apply_to_controller:
                apply_calibration_to_controller(calibration_data_list)
            else:
                log_to_terminal("Calibration data loaded but not applied (apply_to_controller=False).")

    except StopIteration:
        log_to_terminal(f"Calibration file '{file_path}' is empty or has no data rows.")
        messagebox.showerror("Error", f"Calibration file is empty or improperly formatted:\n{os.path.basename(file_path)}")
    except Exception as e:
        log_to_terminal(f"Failed to load calibration file '{file_path}': {e}")
        messagebox.showerror("Error", f"Failed to load calibration file:\n{e}")


def save_calibration_to_file(): 
    serial_number_str, calibration_data_list, controller_name_str = read_calibration_from_controller()

    if not calibration_data_list : 
        messagebox.showwarning("Save Calibration", "No calibration data read from controller to save.")
        log_to_terminal("Save Calib: No data from controller.")
        return

    calibration_str_for_csv = str(calibration_data_list)

    default_filename = "controller_calibration.csv"
    if controller_name_str != "No Controller" and serial_number_str not in ["Controller not connected.", "Serial not found (no data).", "Serial not found (wrong report).", "Serial not found (empty).", "Serial not found (decode error).", "Serial not found (no segment).", "Serial request failed."]: # More robust check
        try:
            safe_controller_name = "".join(c if c.isalnum() else "_" for c in controller_name_str.split(" ")[0]) 
            safe_serial = "".join(c if c.isalnum() else "_" for c in serial_number_str)
            default_filename = f"{safe_controller_name}_{safe_serial}_calib.csv"
        except Exception as e:
            log_to_terminal(f"Error creating default filename: {e}")


    file_path = filedialog.asksaveasfilename(
        title="Save Calibration CSV File",
        defaultextension=".csv",
        filetypes=[("CSV Files", "*.csv")],
        initialfile=default_filename
    )
    if not file_path:
        log_to_terminal("Save calibration cancelled by user.")
        return
    try:
        with open(file_path, mode="w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Serial Number", "Controller Name", "Calibration Data (List of Bytes as String)"])
            writer.writerow([serial_number_str, controller_name_str, calibration_str_for_csv])
        messagebox.showinfo("Success", f"Calibration saved successfully to:\n{os.path.basename(file_path)}")
        log_to_terminal(f"Calibration saved to {file_path}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to save calibration file:\n{e}")
        log_to_terminal(f"Error saving calibration: {e}")

def auto_load_calibration_on_startup():
    if autoload_calibration_var.get() and startup_calibration_file_path_var.get():
        startup_path = startup_calibration_file_path_var.get()
        log_to_terminal(f"Autoload Calibration enabled. Attempting to load: {startup_path}")
        if os.path.exists(startup_path):
            def delayed_load():
                # Wait until joystick is actually connected before trying to apply
                for _ in range(10): # Try for up to 10 seconds (5 * 200ms)
                    if is_joystick_connected and active_dev_path:
                        log_to_terminal(f"Autoload: Controller connected. Applying calibration from {startup_path}")
                        load_calibration_from_file(startup_path, apply_to_controller=True)
                        return
                    time.sleep(0.2) # Check every 200ms
                log_to_terminal("Autoload: Controller not connected after waiting. Will not apply calibration automatically.")

            # This schedules delayed_load to run after some time, giving joystick_background_loop a chance
            if root and root.winfo_exists(): # Ensure root is still valid
                root.after(1000, delayed_load) # Initial delay of 1s before starting checks
            else:
                threading.Thread(target=delayed_load).start() # Fallback if root is gone (e.g. headless mode someday)

        else:
            log_to_terminal(f"Startup calibration file not found: {startup_path}")
            if gui_ready_and_valid: # Only show messagebox if GUI is up
                 messagebox.showwarning("Autoload Calibration", f"Startup calibration file not found:\n{startup_path}")


def update_controller_status_display(): 
    status_text = "Connected Controller:\n"
    if is_joystick_connected and joystick:
        name = joystick.get_name()
        if joystick_vid_pid in PS_SUPPORTED_DEVICES and ps_controller_conn_type:
            name += f" {ps_controller_conn_type}"
        status_text += name
        status_text += f"\nVID:PID: {joystick_vid_pid[0]}:{joystick_vid_pid[1]}"
    else:
        status_text += "None"
    
    if controller_status_label and controller_status_label.winfo_exists():
        controller_status_label.config(text=status_text)
    
    if root and root.winfo_exists(): 
        root.after(1000, update_controller_status_display) 

def draw_analog_sticks_on_canvas(): 
    if not analog_canvas or not root or not analog_canvas.winfo_exists() or not root.winfo_exists():
        return
        
    analog_canvas.delete("all")
    canvas_width = analog_canvas.winfo_width()
    canvas_height = analog_canvas.winfo_height()

    if canvas_width < 50 or canvas_height < 50 : 
        if root and root.winfo_exists(): root.after(DRAW_INTERVAL_MS, draw_analog_sticks_on_canvas)
        return

    if joystick and is_joystick_connected:
        lx, ly, rx, ry, lt, rt = joystick_axes 
        
        radius = min(canvas_width, canvas_height) // 5 
        stick_area_width = canvas_width // 2

        left_center_x = stick_area_width // 2
        left_center_y = canvas_height // 2
        
        right_center_x = stick_area_width + (canvas_width - stick_area_width) // 2
        right_center_y = canvas_height // 2

        analog_canvas.create_oval(left_center_x - radius, left_center_y - radius,
                                  left_center_x + radius, left_center_y + radius,
                                  outline=COLOR_HIGHLIGHT, width=2)
        analog_canvas.create_line(left_center_x, left_center_y - radius,
                                  left_center_x, left_center_y + radius,
                                  fill=COLOR_HIGHLIGHT, width=1, dash=(4, 4))
        analog_canvas.create_line(left_center_x - radius, left_center_y,
                                  left_center_x + radius, left_center_y,
                                  fill=COLOR_HIGHLIGHT, width=1, dash=(4, 4))
        analog_canvas.create_oval(right_center_x - radius, right_center_y - radius,
                                  right_center_x + radius, right_center_y + radius,
                                  outline=COLOR_HIGHLIGHT, width=2)
        analog_canvas.create_line(right_center_x, right_center_y - radius,
                                  right_center_x, right_center_y + radius,
                                  fill=COLOR_HIGHLIGHT, width=1, dash=(4, 4))
        analog_canvas.create_line(right_center_x - radius, right_center_y,
                                  right_center_x + radius, right_center_y,
                                  fill=COLOR_HIGHLIGHT, width=1, dash=(4, 4))

        dot_radius = 8 
        l_dot_x = left_center_x + lx * radius
        l_dot_y = left_center_y + ly * radius
        analog_canvas.create_oval(l_dot_x - dot_radius, l_dot_y - dot_radius,
                                  l_dot_x + dot_radius, l_dot_y + dot_radius,
                                  fill=COLOR_LEFT_DOT, outline=COLOR_BG_DARK)
        r_dot_x = right_center_x + rx * radius
        r_dot_y = right_center_y + ry * radius
        analog_canvas.create_oval(r_dot_x - dot_radius, r_dot_y - dot_radius,
                                  r_dot_x + dot_radius, r_dot_y + dot_radius,
                                  fill=COLOR_RIGHT_DOT, outline=COLOR_BG_DARK)
                                  
        trigger_bar_width = radius * 1.5
        trigger_bar_height = 10
        trigger_y_pos = canvas_height - trigger_bar_height - 10 

        lt_normalized = (lt + 1) / 2
        analog_canvas.create_rectangle(left_center_x - trigger_bar_width/2, trigger_y_pos,
                                       left_center_x - trigger_bar_width/2 + trigger_bar_width * lt_normalized, trigger_y_pos + trigger_bar_height,
                                       fill=COLOR_LEFT_DOT, outline=COLOR_HIGHLIGHT)
        analog_canvas.create_rectangle(left_center_x - trigger_bar_width/2, trigger_y_pos,
                                       left_center_x + trigger_bar_width/2, trigger_y_pos + trigger_bar_height,
                                       outline=COLOR_HIGHLIGHT) 

        rt_normalized = (rt + 1) / 2
        analog_canvas.create_rectangle(right_center_x - trigger_bar_width/2, trigger_y_pos,
                                       right_center_x - trigger_bar_width/2 + trigger_bar_width * rt_normalized, trigger_y_pos + trigger_bar_height,
                                       fill=COLOR_RIGHT_DOT, outline=COLOR_HIGHLIGHT)
        analog_canvas.create_rectangle(right_center_x - trigger_bar_width/2, trigger_y_pos,
                                       right_center_x + trigger_bar_width/2, trigger_y_pos + trigger_bar_height,
                                       outline=COLOR_HIGHLIGHT) 

    else:
        analog_canvas.create_text(canvas_width / 2,
                                  canvas_height / 2,
                                  text="No Supported Joystick Connected\nor Detected",
                                  fill=COLOR_TEXT_DIM,
                                  font=("Arial", 14),
                                  justify="center")
    if root and root.winfo_exists(): 
      root.after(DRAW_INTERVAL_MS, draw_analog_sticks_on_canvas)

def main():
    global root, terminal_text, analog_canvas, controller_status_label
    global autoload_checkbox_var, start_minimized_var, autoload_calibration_var, startup_calibration_file_path_var
    global joystick_thread_running, gui_ready_and_valid 

    root = tk.Tk()
    root.withdraw() 
    root.title("DriftGuard Calibration Utility (Ransa Remake for 8k polling rate)") # Consider adding version
    root.configure(bg=COLOR_BG_DARK)
    root.protocol("WM_DELETE_WINDOW", on_close_window) 
    root.bind("<Unmap>", on_minimize_window) 

    window_width, window_height = 850, 650 
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    cx, cy = max(0, int((sw - window_width) / 2)), max(0, int((sh - window_height) / 2))
    root.geometry(f"{window_width}x{window_height}+{cx}+{cy}")
    root.minsize(window_width - 100, window_height - 100) # Allow more shrinking
    root.resizable(True, True) 

    icon_path = resource_path("data/icon_drift_guard_main.ico")
    try:
        root.iconbitmap(icon_path)
    except Exception as e:
        print(f"[Icon Error] Icon not loaded: {e}") 

    root.grid_rowconfigure(2, weight=1) # Main content area (row 2 for instructions,analog,terminal)
    root.grid_columnconfigure(0, weight=1)

    autoload_checkbox_var = tk.BooleanVar()
    start_minimized_var = tk.BooleanVar()
    autoload_calibration_var = tk.BooleanVar()
    startup_calibration_file_path_var = tk.StringVar()
    startup_calibration_file_path_var.trace_add("write", on_startup_file_change)

    threaded_load_settings() 

    button_frame = tk.Frame(root, bg=COLOR_BG_DARK)
    button_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10,5)) 
    button_inner_frame = tk.Frame(button_frame, bg=COLOR_BG_DARK)
    button_inner_frame.pack(anchor="center") 

    load_button = tk.Button(
        button_inner_frame, text="Load Calibration from CSV",
        width=25, command=load_calibration_and_apply, 
        bg=COLOR_BUTTON_BG, fg=COLOR_TEXT_LIGHT,
        activebackground=COLOR_BUTTON_ACTIVE,
        activeforeground=COLOR_TEXT_LIGHT, bd=1, relief="raised", padx=5, pady=2
    )
    load_button.pack(side="left", padx=10)

    save_button = tk.Button(
        button_inner_frame, text="Save Current Calibration to CSV",
        width=30, command=save_calibration_to_file, 
        bg=COLOR_BUTTON_BG, fg=COLOR_TEXT_LIGHT,
        activebackground=COLOR_BUTTON_ACTIVE,
        activeforeground=COLOR_TEXT_LIGHT, bd=1, relief="raised", padx=5, pady=2
    )
    save_button.pack(side="left", padx=10)

    ctrl_status_frame = tk.Frame(root, bg=COLOR_BG_DARK)
    ctrl_status_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
    controller_status_label = tk.Label(
        ctrl_status_frame, text="Connected Controller:\nNone", anchor="center", justify="center",
        bg=COLOR_BG_DARK, fg=COLOR_TEXT_LIGHT, font=("Arial", 10)
    )
    controller_status_label.pack(padx=5, pady=5, expand=True)

    main_content_frame = tk.Frame(root, bg=COLOR_BG_DARK)
    main_content_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)
    main_content_frame.grid_columnconfigure(0, weight=1, minsize=280) 
    main_content_frame.grid_columnconfigure(1, weight=2, minsize=300) 
    main_content_frame.grid_columnconfigure(2, weight=2, minsize=250) 
    main_content_frame.grid_rowconfigure(0, weight=1)

    instructions_frame = tk.Frame(main_content_frame, bd=1, relief="sunken", bg=COLOR_FRAME_DARK)
    instructions_frame.grid(row=0, column=0, sticky="nsew", padx=(0,5), pady=5)
    instructions_frame.grid_propagate(False)
    instructions_text_widget = tk.Text(
        instructions_frame, wrap="word", bg=COLOR_FRAME_DARK, fg=COLOR_TEXT_LIGHT,
        font=("Arial", 9), relief="flat", bd=0, highlightthickness=0, padx=5, pady=5
    )
    instructions_text_widget.insert(tk.END,
        "Instructions:\n"
        "Ensure your controller (DualSense/Edge) is calibrated via external tools first if needed (e.g., Steam Big Picture, DS4Windows, or online gamepad testers for basic checks).\n\n"
        "1. 'Save Current Calibration to CSV': Reads the current stick calibration values from the connected USB controller and saves them to a CSV file.\n"
        "2. 'Load Calibration from CSV': Loads calibration data from a previously saved CSV file and writes it to the connected USB controller.\n"
        "3. Center panel: Visualizes analog stick and trigger movements.\n"
        "4. Right panel: Logs application activity and errors.\n"
        "5. Compatibility: Primarily for Sony DualSense / DualSense Edge controllers over USB for writing calibration. Reading may work for other devices shown by Pygame.\n"
        "6. Settings: Configure 'Autoload on Windows Start', 'Start Minimized', and 'Load Calibration on Startup' using the checkboxes and file path below.\n"
        "7. Startup File: Specify the CSV file to automatically load and apply if 'Load Calibration on Startup' is checked."
    )
    instructions_text_widget.config(state="disabled") 
    instructions_text_widget.pack(fill="both", expand=True, padx=5, pady=5)

    analog_frame = tk.Frame(main_content_frame, bd=1, relief="sunken", bg=COLOR_FRAME_DARK)
    analog_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
    analog_frame.grid_propagate(False)
    analog_canvas = tk.Canvas(analog_frame, bg=COLOR_CANVAS_BG, highlightthickness=0)
    analog_canvas.pack(fill="both", expand=True, padx=5, pady=5)

    terminal_frame = tk.Frame(main_content_frame, bd=1, relief="sunken", bg=COLOR_FRAME_DARK)
    terminal_frame.grid(row=0, column=2, sticky="nsew", padx=(5,0), pady=5)
    terminal_frame.grid_propagate(False)
    terminal_text = tk.Text(
        terminal_frame, bg="#1E1E1E", fg=COLOR_TEXT_LIGHT, insertbackground=COLOR_TEXT_LIGHT,
        bd=0, highlightthickness=0, wrap="word", font=("Consolas", 9) 
    )
    terminal_text.pack(side="left", fill="both", expand=True, padx=5, pady=5)
    term_scroll = tk.Scrollbar(terminal_frame, command=terminal_text.yview, bg=COLOR_FRAME_DARK, relief="flat", troughcolor=COLOR_BG_DARK)
    term_scroll.pack(side="right", fill="y")
    terminal_text.config(yscrollcommand=term_scroll.set)
    
    # --- GUI Layout End, Signal GUI is Ready ---
    gui_ready_and_valid = True 

    # Flush any early log messages now that the terminal is ready
    if early_log_messages:
        for msg in early_log_messages:
            if terminal_text and terminal_text.winfo_exists():
                 terminal_text.insert(tk.END, msg + "\n")
        if terminal_text and terminal_text.winfo_exists():
            terminal_text.see(tk.END) 
        early_log_messages.clear()

    log_to_terminal("Application GUI initialized.") 


    bottom_frame = tk.Frame(root, bg=COLOR_BG_DARK) # This should be before main_content_frame for layout if it's at row 3
    bottom_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=5) # Check row index relative to main_content_frame
    bottom_frame.grid_columnconfigure(0, weight=1) 
    bottom_frame.grid_columnconfigure(1, weight=1) 
    bottom_frame.grid_columnconfigure(2, weight=1) 

    autoload_checkbox = tk.Checkbutton(
        bottom_frame, text="Autoload on Windows Start", variable=autoload_checkbox_var,
        command=on_autoload_checkbox_change, bg=COLOR_BG_DARK, fg=COLOR_TEXT_LIGHT,
        activebackground=COLOR_BG_DARK, activeforeground=COLOR_TEXT_LIGHT, selectcolor=COLOR_CHECK_SELECT, anchor='w'
    )
    autoload_checkbox.grid(row=0, column=0, padx=5, pady=2, sticky='w')

    start_minimized_checkbox = tk.Checkbutton(
        bottom_frame, text="Start Minimized to Tray", variable=start_minimized_var,
        command=on_start_minimized_checkbox_change, bg=COLOR_BG_DARK, fg=COLOR_TEXT_LIGHT,
        activebackground=COLOR_BG_DARK, activeforeground=COLOR_TEXT_LIGHT, selectcolor=COLOR_CHECK_SELECT, anchor='w'
    )
    start_minimized_checkbox.grid(row=0, column=1, padx=5, pady=2, sticky='w')

    autoload_calibration_checkbox = tk.Checkbutton(
        bottom_frame, text="Load Calibration on App Startup", variable=autoload_calibration_var,
        command=on_autoload_calibration_checkbox_change, bg=COLOR_BG_DARK, fg=COLOR_TEXT_LIGHT,
        activebackground=COLOR_BG_DARK, activeforeground=COLOR_TEXT_LIGHT, selectcolor=COLOR_CHECK_SELECT, anchor='w'
    )
    autoload_calibration_checkbox.grid(row=0, column=2, padx=5, pady=2, sticky='w')

    file_select_frame = tk.Frame(root, bg=COLOR_BG_DARK)
    file_select_frame.grid(row=4, column=0, sticky="ew", padx=10, pady=(2,10)) # Row 4
    startup_file_label = tk.Label(file_select_frame, text="Startup Calibration File:", bg=COLOR_BG_DARK, fg=COLOR_TEXT_LIGHT)
    startup_file_label.pack(side="left", padx=(0,5))
    startup_file_entry = tk.Entry(
        file_select_frame, textvariable=startup_calibration_file_path_var, width=60, 
        bg=COLOR_FRAME_DARK, fg=COLOR_TEXT_LIGHT, insertbackground=COLOR_TEXT_LIGHT, relief="sunken", bd=1
    )
    startup_file_entry.pack(side="left", padx=5, fill="x", expand=True)
    browse_button = tk.Button(
        file_select_frame, text="Browse...", command=on_browse_startup_file,
        bg=COLOR_BUTTON_BG, fg=COLOR_TEXT_LIGHT, activebackground=COLOR_BUTTON_ACTIVE,
        activeforeground=COLOR_TEXT_LIGHT, bd=1, relief="raised"
    )
    browse_button.pack(side="left", padx=5)
    

    profiler = None
    if PROFILING_ENABLED:
        profiler = cProfile.Profile()
        profiler.enable()
        log_to_terminal("Profiling enabled.")

    start_joystick_thread() 

    if root and root.winfo_exists(): # Ensure root is valid before scheduling .after calls
        root.after(500, update_controller_status_display) 
        root.after(DRAW_INTERVAL_MS, draw_analog_sticks_on_canvas) 

        if start_minimized_var.get():
            log_to_terminal("Starting minimized as per settings.")
            root.after(10, lambda: hide_window_to_tray())
        else:
            root.deiconify() 
            root.lift()
            root.focus_force()
            log_to_terminal("Application window shown.")
        
        root.after(2000, auto_load_calibration_on_startup) # Reduced initial delay (was 3000)
    else: # Should not happen if root is created properly
        print("[Error] Root window not valid before mainloop start.")
        return # Exit if root isn't there

    try:
        root.mainloop()
    finally:
        gui_ready_and_valid = False 

        log_to_terminal("Mainloop exited.") 
        if PROFILING_ENABLED and profiler: 
            profiler.disable() 
            log_to_terminal("Profiling disabled.") 
            stats = pstats.Stats(profiler).sort_stats('cumulative') 
            stats.print_stats(30) 
            profile_file = "profile_output.prof" 
            try:
                stats.dump_stats(profile_file) 
                log_to_terminal(f"Profiling stats saved to {profile_file}") 
            except Exception as e:
                log_to_terminal(f"Error saving profile stats: {e}") 
        
        joystick_thread_running = False 
        if joystick_thread and joystick_thread.is_alive(): 
             log_to_terminal("Ensuring joystick thread shutdown from main finally block...") 
             joystick_thread.join(timeout=0.5) 
        log_to_terminal("Ensuring HID devices closed from main finally block...") 
        utils_hid.close_all_hid_devices() 

if __name__ == "__main__":
    if PROFILING_ENABLED:
        print("Starting DriftGuard with profiling...")
    else:
        print("Starting DriftGuard normally...")
    main()
    print("DriftGuard has shut down.")
