import hid
import time

def hid_get_feature_report(dev_path, report_id, size):
    # Basic checks
    if not isinstance(size, int):
        raise ValueError("Size must be an integer.")
    if not (0 <= report_id <= 0xFF):
        raise ValueError("Report ID must be between 0 and 255.")

    try:
        device = hid.device()
        device.open_path(dev_path)
        print("[hid_get_feature_report] Device opened successfully.")

        # device.set_nonblocking(1)

        time.sleep(0.2)

        # Attempt to read the feature report:
        # size+1 = 1 byte for the report ID + 'size' bytes for data
        response = device.get_feature_report(report_id, size)

        if not response:
            raise RuntimeError("No feature report received.")

        if response[0] != report_id:
            raise RuntimeError(f"Invalid feature report ID received. Expected {report_id}, got {response[0]}")

        # Return as a bytes object
        return response

    except Exception as e:
        print(f"[hid_get_feature_report] Error: {e}")
        return None
    finally:
        if "device" in locals():
            device.close()
            print("[hid_get_feature_report] Device closed.")


def hid_set_feature_report(dev_path, report_id, data):
    try:
        device = hid.device()
        device.open_path(dev_path)
        print("[hid_set_feature_report] Device opened successfully for Feature report.")

        device.set_nonblocking(1)

        time.sleep(0.2)

        # send_feature_report requires the first item to be the report_id
        report = [report_id] + list(data)
        result = device.send_feature_report(report)

        if result < 0:
            raise RuntimeError("Failed to send feature report.")
        else:
            print("[hid_set_feature_report] Feature report sent successfully.")

    except Exception as e:
        print(f"[hid_set_feature_report] Error: {e}")
    finally:
        if "device" in locals():
            device.close()
            print("[hid_set_feature_report] Device closed.")


def hid_get_input_report(dev_path, size):
    try:
        device = hid.device()
        device.open_path(dev_path)
        print("[hid_get_input_report] Device opened successfully.")

        device.set_nonblocking(1)

        time.sleep(0.2)

        # Read size+1 bytes from the device.
        # The first byte should be the report ID, followed by 'size' bytes of data.
        response = device.read(size)
        print(f"[hid_get_input_report] Input report received: {response}")
        if not response:
            raise RuntimeError("No input report received.")

        return response

    except Exception as e:
        print(f"[hid_get_input_report] Error: {e}")
        return None
    finally:
        if "device" in locals():
            device.close()
            print("[hid_get_input_report] Device closed.")


def hid_set_output_report(dev_path, report_id, data):
    try:
        device = hid.device()
        device.open_path(dev_path)
        print("[hid_set_output_report] Device opened successfully for Output report.")

        device.set_nonblocking(1)

        # .write() is typically used for Output reports
        report = [report_id] + list(data)

        time.sleep(0.2)

        result = device.write(report)

        if result < 0:
            raise RuntimeError("Failed to send output report.")
        else:
            print("[hid_set_output_report] Output report sent successfully.")

    except Exception as e:
        print(f"[hid_set_output_report] Error: {e}")
    finally:
        if "device" in locals():
            device.close()
            print("[hid_set_output_report] Device closed.")

def is_device_responsive(dev_path,  tries=3, delay=0.05):
    try:
        d = hid.device()
        d.open_path(dev_path)
        d.set_nonblocking(True)

        for _ in range(tries):
            time.sleep(0.2)
            data = d.read(64)
            if data:
                d.close()
                return True
            time.sleep(delay)

        d.close()
        return False

    except Exception as e:
        print(f"[is_device_responsive_nonblocking] Exception: {e}")
        return False