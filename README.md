# Why is the app size larger than expected?
This application is packaged using [PyInstaller](https://www.pyinstaller.org/), which bundles a full Python runtime and all required dependencies into a single executable. As a result, the final package size is bigger than if this were a “native” application. The benefit is that you do not need to install Python separately in order to run the app—all necessary components are included out of the box.

# Why do some antivirus programs flag the `.exe` as a virus?
Some antivirus software may falsely flag executables created by PyInstaller as potentially harmful. This is a known issue and is typically a **false positive**. If you are concerned, you can:
1. **Inspect or run the source code** using Python directly (no installer needed).
2. **Build the executable yourself** using PyInstaller (see instructions below).
3. Scan it with multiple antivirus engines to rule out any genuine threat.

# Can I run it without the large executable?
Yes! If you already have Python 3 installed, you can run the tool directly from the source # code. Simply clone or download this repository and run if you already have requirements installed:
python main_app.py

# Build it yourself using PyInstaller:
1. Install python 3.10.11 and git
2. Create a folder on disk C like DriftGuard_Utility
3. Open windows terminal and do
cd C:\DriftGuard_Utility

4. do git clone https://path_to_repo
5. cd DriftGuard_Calibration_Utility

5. Create new python virtual enviorment in your current location
python -m venv venv

6. Activate
.\venv\Scripts\activate

7. Install requirements
pip install -r requirements.txt

8. Use pyinstaller
pyinstaller main.spec

9. Exe will be in the folder dist
