import hid
import time

# Dictionary to store opened device handles {dev_path: device_object}
_open_devices = {}

def open_hid_device(dev_path):
    """
    Opens a HID device if not already open and caches the handle.
    Returns the device handle or None if opening fails.
    """
    if dev_path in _open_devices and _open_devices[dev_path]:
        # Optionally, add a check here to see if the cached device is still valid
        # For now, assume it is if it's in the dictionary.
        return _open_devices[dev_path]
    try:
        device = hid.device()
        device.open_path(dev_path)
        device.set_nonblocking(1)  # Set non-blocking once after opening
        _open_devices[dev_path] = device
        print(f"[HID] Device opened and cached: {dev_path}")
        return device
    except Exception as e:
        print(f"[HID ERROR] Error opening device {dev_path}: {e}")
        if dev_path in _open_devices: # Clean up if entry exists but is invalid
            del _open_devices[dev_path]
        return None

def close_hid_device(dev_path):
    """Closes a specific HID device and removes it from the cache."""
    if dev_path in _open_devices and _open_devices[dev_path]:
        try:
            _open_devices[dev_path].close()
            print(f"[HID] Device closed: {dev_path}")
        except Exception as e:
            print(f"[HID ERROR] Error closing device {dev_path}: {e}")
        del _open_devices[dev_path]
    elif dev_path not in _open_devices:
        print(f"[HID WARNING] Device path not found in cache for closing: {dev_path}")


def close_all_hid_devices():
    """Closes all cached HID devices."""
    print("[HID] Closing all cached devices...")
    paths_to_close = list(_open_devices.keys())
    for path in paths_to_close:
        close_hid_device(path)

def hid_get_feature_report(dev_path, report_id, size):
    if not isinstance(size, int):
        raise ValueError("Size must be an integer.")
    if not (0 <= report_id <= 0xFF):
        raise ValueError("Report ID must be between 0 and 255.")

    device = open_hid_device(dev_path)
    if not device:
        print(f"[HID ERROR] Get Feature Report: Device not open or accessible: {dev_path}")
        return None

    try:
        # Removed time.sleep(0.2). Add a very small sleep (e.g., 0.005)
        # ONLY if necessary after testing on specific problematic hardware.
        # time.sleep(0.005)
        response = device.get_feature_report(report_id, size)

        if not response:
            # Non-blocking read might return None if no data immediately available.
            # Depending on protocol, this might be normal or an error.
            # print(f"[HID WARNING] Get Feature Report: No data received for report ID {report_id}.")
            return None # Or handle as appropriate for your device's protocol

        if response[0] != report_id:
            # This check might be too strict if the device can return other reports
            # on the feature report endpoint, or if report_id is not always the first byte.
            # print(f"[HID WARNING] Get Feature Report: Invalid report ID. Expected {report_id}, got {response[0]}. Data: {response}")
            # For some devices, the actual report data might follow, so consider returning response if it looks valid otherwise.
            pass # Assuming for now that the first byte should match. If not, this check needs adjustment.

        return response
    except hid.HIDException as e: # hid.HIDException is more specific
        print(f"[HID ERROR] Get Feature Report for {dev_path}, report ID {report_id}: {e}")
        if "No such device" in str(e) or "failed to read" in str(e).lower(): # Device likely disconnected
            print(f"[HID] Device {dev_path} seems disconnected. Closing handle.")
            close_hid_device(dev_path)
        return None
    except Exception as e:
        print(f"[HID ERROR] Get Feature Report (Unknown) for {dev_path}, report ID {report_id}: {e}")
        return None

def hid_set_feature_report(dev_path, report_id, data):
    device = open_hid_device(dev_path)
    if not device:
        print(f"[HID ERROR] Set Feature Report: Device not open or accessible: {dev_path}")
        return False # Indicate failure

    try:
        # Removed time.sleep(0.2)
        report = [report_id] + list(data)
        result = device.send_feature_report(report)

        if result < 0: # Typically indicates an error by the underlying system call
            print(f"[HID ERROR] Set Feature Report: send_feature_report failed for {dev_path}, report ID {report_id}. Result: {result}")
            # Consider device state; an error here might mean it's disconnected.
            return False
        else:
            # print(f"[HID] Set Feature Report sent successfully to {dev_path}, report ID {report_id}.")
            return True # Indicate success

    except hid.HIDException as e:
        print(f"[HID ERROR] Set Feature Report for {dev_path}, report ID {report_id}: {e}")
        if "No such device" in str(e) or "failed to write" in str(e).lower():
            print(f"[HID] Device {dev_path} seems disconnected during set. Closing handle.")
            close_hid_device(dev_path)
        return False
    except Exception as e:
        print(f"[HID ERROR] Set Feature Report (Unknown) for {dev_path}, report ID {report_id}: {e}")
        return False

def hid_get_input_report(dev_path, size):
    # This function might need careful handling of non-blocking reads,
    # as input reports are often asynchronous.
    device = open_hid_device(dev_path)
    if not device:
        print(f"[HID ERROR] Get Input Report: Device not open or accessible: {dev_path}")
        return None
    try:
        # Removed time.sleep(0.2)
        # For input reports, a timeout on read might be more appropriate than a sleep before.
        # response = device.read(size, timeout_ms=10) # Example with timeout if your hid library version supports it
        response = device.read(size) # Standard read
        # if not response:
            # print(f"[HID WARNING] Get Input Report: No input report received from {dev_path}.")
        return response
    except hid.HIDException as e:
        print(f"[HID ERROR] Get Input Report for {dev_path}: {e}")
        if "No such device" in str(e):
            close_hid_device(dev_path)
        return None
    except Exception as e:
        print(f"[HID ERROR] Get Input Report (Unknown) for {dev_path}: {e}")
        return None


def hid_set_output_report(dev_path, report_id, data):
    device = open_hid_device(dev_path)
    if not device:
        print(f"[HID ERROR] Set Output Report: Device not open or accessible: {dev_path}")
        return False

    try:
        # Removed time.sleep(0.2)
        report = bytes([report_id] + list(data)) # Ensure it's bytes for write
        result = device.write(report) # device.write usually expects bytes

        if result < 0:
            print(f"[HID ERROR] Set Output Report: device.write failed for {dev_path}. Result: {result}")
            return False
        # print(f"[HID] Output report sent successfully to {dev_path}.")
        return True
    except hid.HIDException as e:
        print(f"[HID ERROR] Set Output Report for {dev_path}: {e}")
        if "No such device" in str(e):
            close_hid_device(dev_path)
        return False
    except Exception as e:
        print(f"[HID ERROR] Set Output Report (Unknown) for {dev_path}: {e}")
        return False

def is_device_responsive(dev_path, tries=2, delay=0.01):
    """
    Checks if a device is responsive by attempting a small read.
    Uses cached device if available, otherwise opens temporarily.
    """
    device = _open_devices.get(dev_path)
    opened_temporarily = False

    if not device:
        try:
            # print(f"[HID is_device_responsive] Temporarily opening {dev_path} for check.")
            device = hid.device()
            device.open_path(dev_path)
            device.set_nonblocking(True)
            opened_temporarily = True
        except Exception as e:
            # print(f"[HID is_device_responsive] Exception opening device {dev_path}: {e}")
            return False
    if not device: # Still no device
        return False

    try:
        for _ in range(tries):
            # Attempt to read a small amount of data (e.g., 1 byte, or a typical report size like 64)
            # The read itself might be blocking or non-blocking based on device.set_nonblocking()
            data = device.read(64) # Read up to 64 bytes
            if data: # Any data received means it's responsive
                # print(f"[HID is_device_responsive] Device {dev_path} responded.")
                return True
            time.sleep(delay) # Wait a bit before retrying
        # print(f"[HID is_device_responsive] Device {dev_path} did not respond after {tries} tries.")
        return False
    except hid.HIDException as e: # Catch HID specific errors
        # print(f"[HID is_device_responsive] HIDException for {dev_path}: {e}")
        if "No such device" in str(e) and not opened_temporarily : # If it was a cached device and now it's gone
             close_hid_device(dev_path) # Remove bad handle from cache
        return False
    except Exception as e:
        # print(f"[HID is_device_responsive] Generic exception for {dev_path}: {e}")
        return False
    finally:
        if opened_temporarily and device:
            try:
                device.close()
                # print(f"[HID is_device_responsive] Temporarily opened device {dev_path} closed.")
            except Exception as e:
                print(f"[HID ERROR] is_device_responsive: Error closing temp device {dev_path}: {e}")
