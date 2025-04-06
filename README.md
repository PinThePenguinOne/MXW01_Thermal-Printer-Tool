# MXW01 CLI - Thermal Printer Tool

A command-line interface (CLI) tool written in Python to control and print images or text to mxw01 thermal printers using the Bluetooth LE protocol.

This script allows you to send print jobs directly from your computer without needing the official mobile app.

![duck](https://github.com/user-attachments/assets/c312d74f-dcb0-44c7-bedb-e543f40d926f)

## Features

*   **Print Images:** Print single image files (PNG, JPG, BMP, GIF). Images are automatically resized/padded to the printer's width (384px) and converted to 1-bit black and white.
*   **Print Folders:** Print all supported images within a specified folder.
*   **Print Text:** Print text strings with basic word wrapping.
    *   **Custom Fonts:** Specify system fonts by name (requires `matplotlib`).
    *   **Font Size:** Control the font size.
    *   **Alignment:** Align text left, center, or right.
*   **Paper Feed:** Feed blank paper by a specified number of lines.
*   **Test Sequence:** Run a predefined test sequence including sample images and various text formats.
*   **Debug Mode:** Save the prepared 1-bit bitmap images to files instead of sending them to the printer, useful for troubleshooting or previewing.
*   **Upside Down Printing:** Option to print images and text rotated 180 degrees.
*   **List Fonts:** List available system fonts recognized by `matplotlib`.
*   **Custom Device Address:** Specify the Bluetooth MAC address of your printer.

## Requirements

*   **Python:** 3.8+ (due to `asyncio` and `bleak` requirements)
*   **Libraries:**
    *   `bleak`: For Bluetooth Low Energy communication.
    *   `Pillow` (PIL Fork): For image manipulation and text rendering.
    *   `matplotlib` (Optional but Recommended): For discovering and loading system fonts. If not installed, only a basic default font can be used.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/PinThePenguine/MXW01_Thermal-Printer-Tool.git
    cd MXW01_Thermal-Printer-Tool
    ```
2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Finding Your Printer's Address

You need the Bluetooth MAC address of your printer. You can usually find this using your system's Bluetooth scanning tools or other BLE scanning apps on your phone. Look for a device name similar to "MX01W". The address format is typically `XX:XX:XX:XX:XX:XX`.

## Change your mac address in the script

![image](https://github.com/user-attachments/assets/b4a5b2e5-bdcd-47c9-882b-d8d7107950c4)

## Usage

The basic command structure is:

```bash
python MXW01print.py [OPTIONS] [ACTION]
```

You must specify at least one action (like printing an image, text, or feeding paper).

**Common Actions:**

*   **Print an Image:**
    ```bash
    python MXW01print.py -i path/to/your/image.png -d YOUR_PRINTER_ADDRESS
    ```
*   **Print Text:**
    ```bash
    python MXW01print.py -t "Hello Printer!" -d YOUR_PRINTER_ADDRESS
    ```
*   **Print Text with Options:**
    ```bash
    python MXW01print.py -t "Centered Text" -n "Courier New" -z 32 -a center -d YOUR_PRINTER_ADDRESS
    ```
    *(Short form: `python MXW01print.py -t "Centered Text" -n "Courier New" -z 32 -a center -d YOUR_PRINTER_ADDRESS`)*
*   **Print all images in a folder:**
    ```bash
    python MXW01print.py -f path/to/image_folder/ -d YOUR_PRINTER_ADDRESS
    ```
*   **Feed Paper (e.g., 50 lines):**
    ```bash
    python MXW01print.py -p 50 -d YOUR_PRINTER_ADDRESS
    ```
*   **Run Test Sequence:**
    ```bash
    # Requires a 'test_print_images' folder with some images
    python MXW01print.py -x -d YOUR_PRINTER_ADDRESS
    ```
*   **List Available Fonts:**
    ```bash
    python MXW01print.py -l
    ```
*   **Save Output to Files (Debug):**
    ```bash
    python MXW01print.py -i image.png -s
    # Output saved to 'debug_output/' folder
    ```

**Key Options:**

| Short | Long          | Description                                                    | Default                 |
| :---- | :------------ | :------------------------------------------------------------- | :---------------------- |
| `-i`  | `--image`     | Path to a single image file to print.                        |                         |
| `-f`  | `--folder`    | Path to a folder containing images to print.                 |                         |
| `-t`  | `--text`      | Text string to print.                                          |                         |
| `-p`  | `--feed`      | Feed paper by specified lines (no value = 40).             | `None`                  |
| `-x`  | `--test-print`| Run a test sequence.                                         | `False`                 |
| `-d`  | `--device`    | Bluetooth MAC address of the printer.                        | `48:0F:57:00:00:00`     |
| `-s`  | `--debug-save`| Save prepared bitmaps to files instead of printing.          | `False`                 |
| `-u`  | `--upside-down`| Print the image(s) or text upside down.                      | `False`                 |
| `-z`  | `--font-size` | Font size for text printing.                                 | `24`                    |
| `-n`  | `--font`      | Font name for text printing (use `-l` to list).              | `Arial`                 |
| `-a`  | `--align`     | Text alignment (`left`, `center`, `right`).                  | `left`                  |
| `-l`  | `--list-fonts`| List available system fonts and exit.                        | `False`                 |
| `-h`  | `--help`      | Show the help message and exit.                              |                         |

**Notes:**

*   The script requires `asyncio` for handling Bluetooth communication.
*   Connection timeouts might occur if the printer is off, out of range, or already connected to another device.
*   Font loading relies on `matplotlib`. If it's not installed or can't find the specified font, it will fall back to Arial and then to a basic PIL default font. Ensure the font names match those listed by `-l`.
*   The `--test-print` action looks for images in a folder named `test_print_images` in the same directory as the script.
