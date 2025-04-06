# catprint_cli.py
import asyncio
import argparse
import os
import math
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError
from PIL import Image, ImageDraw, ImageFont
import sys # For exit

try:
    from matplotlib import font_manager
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    font_manager = None # Ensure font_manager exists even if import fails

# --- Constants ---
DEFAULT_ADDRESS = "48:0F:57:00:00:00" # Default printer address
CONTROL_WRITE_UUID = "0000ae01-0000-1000-8000-00805f9b34fb" # Write characteristics for commands (printer control)
NOTIFY_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"        # Notify characteristics for responses (printer status)
DATA_WRITE_UUID = "0000ae03-0000-1000-8000-00805f9b34fb"     # Write characteristics for bulk data (image/feed data)

PRINTER_WIDTH_PIXELS = 384
PRINTER_WIDTH_BYTES = PRINTER_WIDTH_PIXELS // 8
MAX_FEED_CHUNK_HEIGHT = 256 # Max lines per single paper feed command
SUPPORTED_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
DELAY_BETWEEN_PRINTS = 1.0 # Seconds (Applied between separate print jobs AND feed chunks)

# Test Print Constants
TEST_IMAGE_FOLDER = "test_print_images" # Folder to scan for --test-print images
TEST_TEXT_JOBS = [
    ("Test: Short Text - Arial 24", "Arial", 24),
    ("Test: Slightly Longer Text - Arial 16", "Arial", 16),
    ("Test: Multi-line\nText Example\nArial 24", "Arial", 24),
    ("Test: Long text string to test wrapping capabilities of the thermal printer using the default Arial font at size 24. This should wrap onto multiple lines hopefully.", "Arial", 24),
    ("Test: Courier New 18 (Monospace?)", "Courier New", 18),
    ("Test: Default Fallback Test (Font Not Found)", "NonExistentFont", 20)
]

# --- Font Handling ---
DEFAULT_FONT_NAME = "Arial" # Keep this as a fallback name
DEFAULT_FONT_SIZE = 24

def load_font(font_name, font_size):
    """Loads a font by name and size using matplotlib.font_manager, falling back to defaults."""
    font_path = None

    if MATPLOTLIB_AVAILABLE:
        # Collect matching fonts first
        matching_fonts = []
        try:
            for f in font_manager.fontManager.ttflist:
                if f.name == font_name:
                    matching_fonts.append(f)
        except Exception as e:
            print(f"    Info: Error during font list iteration while collecting matches: {e}")
            matching_fonts = [] # Ensure it's empty on error
        
        # Strategy 1: Prefer "plain" filename among matches
        try:
            plain_font_path = None
            first_match_path = None
            
            # Filename substrings indicating a non-regular style
            style_indicators_in_filename = [
                'bd', 'bold', 'bld',
                'i', 'italic', 'obl', 'oblique',
                'blk', 'black',
                'narrow', 'n',
            ]
            
            if matching_fonts:
                first_match_path = matching_fonts[0].fname # Fallback to the first match
                for f in matching_fonts:
                    base_name = os.path.basename(f.fname).lower()
                    name_part, _ = os.path.splitext(base_name)
                    # Check if the filename part contains any style indicator
                    is_plain = True
                    # Exclude filenames exactly matching '<fontname>n.ttf' like 'arialn.ttf'
                    # unless the indicator list specifically contains just 'n'. This logic is tricky.
                    # A more robust approach might involve more complex regex or rules.
                    if name_part == font_name.lower() + 'n' and 'n' in style_indicators_in_filename:
                        is_plain = False # Treat 'arialn' as non-plain if 'n' is an indicator
                    # Check other indicators, removing the base font name first
                    elif any(indicator in name_part.replace(font_name.lower(), '') for indicator in style_indicators_in_filename if indicator != 'n'):
                        is_plain = False
                        
                    if is_plain:
                        plain_font_path = f.fname
                        # Keep a quiet confirmation for debugging if needed later
                        # print(f"    Selected plain filename path: {plain_font_path} (Filename: {base_name})")
                        break
                        
            if plain_font_path:
                font_path = plain_font_path
            elif first_match_path:
                # print(f"    Warning: No plain filename found. Falling back to first match: {first_match_path}")
                font_path = first_match_path
            
        except Exception as e:
             print(f"    Info: Error during font selection based on filename: {e}")
             font_path = None

        # Strategy 2: If not found via iteration/filename check, try findfont
        if not font_path:
            try:
                common_extensions = ['.ttf', '.otf']
                font_path_findfont = None
                if not any(font_name.lower().endswith(ext) for ext in common_extensions):
                    for ext in common_extensions:
                        try:
                            font_path_findfont = font_manager.findfont(font_name + ext, fallback_to_default=False)
                            if font_path_findfont: break
                        except Exception: pass
                if not font_path_findfont:
                     font_path_findfont = font_manager.findfont(font_name, fallback_to_default=False)

                if font_path_findfont:
                    font_path = font_path_findfont
                    # print(f"    Found font path via findfont: {font_path}")

            except Exception as e:
                # print(f"    Info: Matplotlib findfont couldn't find or parse font '{font_name}'. Error: {e}")
                font_path = None

    # --- Loading Attempt ---
    if font_path:
        try:
            # print(f"--> Attempting to load font: '{font_name}' (Size: {font_size}) from path: {font_path}")
            return ImageFont.truetype(font_path, font_size)
        except IOError as e:
            print(f"    Warning: Error loading font file '{font_path}'. {e}. Using default.")
    else:
        if MATPLOTLIB_AVAILABLE: # Only print this if matplotlib was actually tried
             print(f"    Info: Font '{font_name}' not found via matplotlib. Proceeding to default '{DEFAULT_FONT_NAME}'.")

    # --- Fallback Logic ---
    default_font_path = None
    if MATPLOTLIB_AVAILABLE:
        try:
            # print(f"--> Searching for default font '{DEFAULT_FONT_NAME}' via matplotlib...")
            default_font_path = font_manager.findfont(DEFAULT_FONT_NAME, fallback_to_default=True)
            # print(f"--> Matplotlib found default font path: {default_font_path}")
        except Exception as e:
            print(f"    Warning: Error finding default font '{DEFAULT_FONT_NAME}' via matplotlib: {e}")
            default_font_path = None

    if default_font_path:
        try:
            # print(f"--> Attempting to load DEFAULT font from path: {default_font_path} (Size: {DEFAULT_FONT_SIZE})")
            return ImageFont.truetype(default_font_path, DEFAULT_FONT_SIZE)
        except IOError as e:
             print(f"    Warning: Error loading default font file '{default_font_path}'. {e}. Using PIL default.")
    else:
        if MATPLOTLIB_AVAILABLE: # Only print if default search via matplotlib failed
             print(f"    Info: Default font '{DEFAULT_FONT_NAME}' not found via matplotlib path. Using PIL default.")

    # Ultimate fallback: PIL's built-in default font
    try:
        # print(f"--> Attempting to load PIL built-in default font.")
        return ImageFont.load_default()
    except IOError:
        print("    ERROR: Could not load ANY font! Text printing will likely fail.")
        return None

# --- CRC Calculation (Standard CRC-8/Dallas Maxim) ---
def crc8_update(crc, data_byte):
    crc ^= data_byte
    for _ in range(8):
        if crc & 0x80: crc = (crc << 1) ^ 0x07 # Polynomial 0x07
        else: crc <<= 1
        crc &= 0xFF # Ensure it stays within 8 bits
    return crc

def calculate_crc8(data):
    """Calculates the CRC-8 checksum for the given data bytes."""
    crc = 0x00
    for byte in data: crc = crc8_update(crc, byte)
    return crc
# ----------------------

# --- Command Creation ---
def create_command_with_crc(command_id, data):
    """Creates a command packet including header, ID, data, CRC, and footer."""
    data_length_le = len(data).to_bytes(2, byteorder='little')
    crc = calculate_crc8(data)
    return bytes([0x22, 0x21, command_id, 0x00]) + data_length_le + data + bytes([crc, 0xFF])

def create_command_simple(command_id, data):
    """Creates a command packet without CRC (uses 0x00 placeholders)."""
    data_length_le = len(data).to_bytes(2, byteorder='little')
    return bytes([0x22, 0x21, command_id, 0x00]) + data_length_le + data + bytes([0x00, 0x00])
# ----------------------------------

# --- Image Loading and Preparation ---
def prepare_image_for_print(image_path, target_width):
    """Loads, resizes/pads, and converts an image to 1-bit format for printing."""
    try:
        img = Image.open(image_path)
    except FileNotFoundError:
        print(f"Error: Image file not found at {image_path}.")
        return None
    except Exception as e:
        print(f"Error loading image '{image_path}': {e}")
        return None

    # Adjust image width (Pad or Resize)
    if img.width < target_width:
        print(f"Padding '{os.path.basename(image_path)}' width ({img.width}px -> {target_width}px)")
        img_padded_width = Image.new('L', (target_width, img.height), color=255) # White background
        x_offset = (target_width - img.width) // 2
        img_padded_width.paste(img.convert('L'), (x_offset, 0))
        img = img_padded_width
    elif img.width > target_width:
        print(f"Resizing '{os.path.basename(image_path)}' width ({img.width}px -> {target_width}px)")
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((target_width, new_height))

    # Convert to 1-bit black and white using default dithering
    img_bw = img.convert('1')

    return img_bw
# -------------------------------------------------

# --- Text Rendering ---
def create_text_bitmap(text, font, width, alignment='left'):
    """Renders multiline text onto a 1-bit bitmap with basic word wrapping and alignment."""
    lines = []
    paragraphs = text.split('\n')

    def get_text_width(txt):
        """Helper to get text width, handling font method differences."""
        if not txt: return 0 # Handle empty strings
        try: return font.getlength(txt)
        except AttributeError: return font.getsize(txt)[0]

    # Simple word wrapping (same as before)
    for paragraph in paragraphs:
        if not paragraph:
            lines.append("")
            continue
        words = paragraph.split(' ')
        current_line = ""
        for i, word in enumerate(words):
            test_line = current_line + (" " if current_line else "") + word
            line_width = get_text_width(test_line)
            if line_width <= width:
                current_line = test_line
            else:
                if current_line: lines.append(current_line)
                word_width = get_text_width(word)
                current_line = word
        if current_line: lines.append(current_line)

    num_lines = len(lines)
    if num_lines == 0: return Image.new('1', (width, 1), color=1)

    # Calculate line height and total text height (same as before)
    try:
        ascent, descent = font.getmetrics()
        line_height = ascent + descent
        interline_spacing = 4
        line_step = line_height + interline_spacing
    except AttributeError:
        _, line_height = font.getsize('A')
        interline_spacing = 2
        line_step = line_height + interline_spacing

    total_text_height = (num_lines * line_step) - interline_spacing
    if total_text_height <= 0: total_text_height = line_height
    img_height = total_text_height

    img_text = Image.new('1', (width, img_height), color=1) # Background white
    draw = ImageDraw.Draw(img_text)
    current_y = 0
    for line in lines:
        line_width = get_text_width(line)
        x_position = 0 # Default to left
        if alignment == 'center':
            x_position = (width - line_width) // 2
        elif alignment == 'right':
            x_position = width - line_width

        draw.text((x_position, current_y), line, font=font, fill=0) # Text black
        current_y += line_step

    print(f"Created text bitmap: num_lines={num_lines}, height={img_height}, align={alignment}")
    return img_text
# --------------------------------------

# --- Image Data Processing ---
def process_image(img):
    """Converts a 1-bit PIL image into the byte format required by the printer."""
    pixels = list(img.getdata())
    width, height = img.size
    processed_data = bytearray()
    # Pack 8 pixels into one byte, row by row
    for y in range(height):
        byte = 0
        for x in range(width):
            pixel_index = y * width + x
            pixel_value = pixels[pixel_index] # 0=black, 255/1=white in PIL '1' mode
            if pixel_value == 0: # Set bit for black pixel
                byte |= (1 << (x % 8)) 
            # If byte is full or end of row reached, append it
            if (x + 1) % 8 == 0 or (x + 1) == width:
                processed_data.append(byte)
                byte = 0 # Reset for next byte
    return bytes(processed_data)
# -----------------------------------------------------------------

# --- Bluetooth Communication ---
received_responses = {} # Dictionary to store received notifications by command ID
notification_condition = asyncio.Condition() # Used to wait for specific notifications

async def notification_handler(sender, data):
    """Callback for handling incoming BLE notifications."""
    global received_responses
    cmd_id, payload = parse_response(data)
    if cmd_id is not None:
        async with notification_condition:
            received_responses[cmd_id] = payload 
            notification_condition.notify_all() # Wake up tasks waiting for this response

def parse_response(data):
    """Parses a raw notification response packet."""
    # Basic validation
    if not data or len(data) < 8 or data[0] != 0x22 or data[1] != 0x21: return None, None
    command_id = data[2]
    payload_len = int.from_bytes(data[4:6], 'little')
    # Check if received data is long enough for the declared payload
    if len(data) < 6 + payload_len: return command_id, None
    payload = data[6:6 + payload_len]
    return command_id, payload

def check_a1_status(payload):
    """Checks the status byte within an A1 response payload."""
    if not payload or len(payload) < 8: return False
    ok_byte = payload[6]
    is_ok = (ok_byte == 0)
    print(f"  [Check A1 Status] OK: {is_ok}")
    return is_ok

def check_a9_status(payload):
    """Checks the status byte within an A9 response payload."""
    if not payload or len(payload) < 1: return False
    status_byte = payload[0]
    is_ok = (status_byte == 0)
    print(f"  [Check A9 Status] Print Request OK: {is_ok}")
    return is_ok

async def run_print_job(client, img_final, job_description):
    """Sends the necessary commands and data to print a single prepared image."""
    global received_responses
    print(f"Processing: '{job_description}'")
    if img_final is None: print("Error: No image data provided."); return False

    printer_data = process_image(img_final)
    final_data_len = len(printer_data)
    image_height = img_final.height # Actual height of the image data being sent
    print(f"Prepared data: {final_data_len} bytes, height={image_height}px")

    try:
        ae01_char = client.services.get_characteristic(CONTROL_WRITE_UUID)
        ae02_char = client.services.get_characteristic(NOTIFY_UUID)
        ae03_char = client.services.get_characteristic(DATA_WRITE_UUID)
        if not all([ae01_char, ae02_char, ae03_char]): raise ValueError("Missing required GATT characteristic")
    except Exception as e: print(f"Error getting characteristics: {e}"); return False

    # --- Define Commands for this Job ---
    cmd_setup_b1 = create_command_with_crc(0xB1, bytes([0x00])) # Start print setup?
    cmd_setup_a2_1 = create_command_with_crc(0xA2, bytes([0x5D])) # Unknown setup command
    cmd_setup_a1_1 = create_command_with_crc(0xA1, bytes([0x00])) # Check printer status?
    cmd_setup_a2_2 = create_command_with_crc(0xA2, bytes([0x5D])) # Unknown setup command (repeated)
    # A9 command declares the print dimensions (height, width_bytes)
    image_height_le = image_height.to_bytes(2, 'little') 
    width_bytes_le = PRINTER_WIDTH_BYTES.to_bytes(2, 'little')
    print_request_data = image_height_le + width_bytes_le
    cmd_print_request_a9 = create_command_simple(0xA9, print_request_data)
    # AD command signals the end of the print data
    end_print_data = bytes([0x00])
    cmd_end_print_ad = create_command_simple(0xAD, end_print_data)

    # --- Send Commands + Data ---
    try:
        # 1. Setup Sequence (B1, A2, A1) -> Wait/Check A1
        async with notification_condition: received_responses.pop(0xA1, None) # Clear previous response
        for cmd in [cmd_setup_b1, cmd_setup_a2_1, cmd_setup_a1_1]:
            await client.write_gatt_char(ae01_char.uuid, cmd, response=False); await asyncio.sleep(0.01)
        async with notification_condition:
            try: await asyncio.wait_for(notification_condition.wait_for(lambda: 0xA1 in received_responses), timeout=7.0)
            except asyncio.TimeoutError: raise ValueError("Timeout waiting for A1 response")
            if not check_a1_status(received_responses.pop(0xA1)): raise ValueError("A1 status check failed")

        # 2. Print Request Sequence (A2, A9) -> Wait/Check A9
        async with notification_condition: received_responses.pop(0xA9, None) # Clear previous response
        for cmd in [cmd_setup_a2_2, cmd_print_request_a9]:
            await client.write_gatt_char(ae01_char.uuid, cmd, response=False); await asyncio.sleep(0.01)
        async with notification_condition:
            try: await asyncio.wait_for(notification_condition.wait_for(lambda: 0xA9 in received_responses), timeout=7.0)
            except asyncio.TimeoutError: raise ValueError("Timeout waiting for A9 response")
            if not check_a9_status(received_responses.pop(0xA9)): raise ValueError("A9 status check failed")

        # 3. Send Image Data (AE03) in small chunks
        print(f"Sending image data ({final_data_len} bytes) to {DATA_WRITE_UUID[-12:-8]}...")
        max_chunk = 20 # Max bytes per write seems limited
        for j in range(0, len(printer_data), max_chunk):
            chunk = printer_data[j:j + max_chunk]
            await client.write_gatt_char(ae03_char.uuid, chunk, response=False)
        print("Finished sending image data.")

        # 4. Send End Print Command (AD) -> Wait/Check AA (Print Complete)
        async with notification_condition: received_responses.pop(0xAA, None) # Clear previous response
        await client.write_gatt_char(ae01_char.uuid, cmd_end_print_ad, response=False)
        await asyncio.sleep(0.01)

        # Wait for AA notification (print finished)
        print("Waiting for AA (Print Complete)...")
        aa_received = False
        async with notification_condition:
            try:
                 # Timeout needs to be long enough for the physical print
                 timeout_print = max(15.0, image_height / 20.0) # Rough estimate
                 await asyncio.wait_for(notification_condition.wait_for(lambda: 0xAA in received_responses), timeout=timeout_print)
                 payload = received_responses.pop(0xAA)
                 aa_received = True
                 print("  AA notification received.")
            except asyncio.TimeoutError:
                 # This might be okay if the print completed visually, but log it.
                 print("Warning: AA notification not received within timeout.")
        await asyncio.sleep(0.5) # Brief pause after job completion

        print(f"Print job for '{job_description}' sequence completed."); return True
    except Exception as e: print(f"Error during print job for '{job_description}': {e}"); return False

async def run_feed_paper(client, lines_to_feed):
    """Sends commands to feed blank paper, handling chunking for large amounts."""
    global received_responses
    print(f"Requested paper feed: {lines_to_feed} lines")

    total_lines_to_feed = lines_to_feed
    if total_lines_to_feed <= 0: print("Error: Lines to feed must be positive."); return False

    lines_remaining = total_lines_to_feed
    chunk_num = 0
    overall_success = True

    # Loop through chunks if requested feed exceeds max height
    while lines_remaining > 0:
        chunk_num += 1
        current_chunk_lines = min(lines_remaining, MAX_FEED_CHUNK_HEIGHT)
        print(f"\n--- Starting Feed Chunk {chunk_num}/{math.ceil(total_lines_to_feed/MAX_FEED_CHUNK_HEIGHT)} ({current_chunk_lines} lines) --- ")

        # Prepare blank data for this chunk
        blank_data_len = PRINTER_WIDTH_BYTES * current_chunk_lines
        blank_data = bytes([0x00] * blank_data_len)

        try:
            ae01_char = client.services.get_characteristic(CONTROL_WRITE_UUID)
            ae02_char = client.services.get_characteristic(NOTIFY_UUID)
            ae03_char = client.services.get_characteristic(DATA_WRITE_UUID)
            if not all([ae01_char, ae02_char, ae03_char]): raise ValueError("Missing required GATT characteristic")
        except Exception as e: print(f"Error getting characteristics: {e}"); overall_success = False; break

        # --- Define Commands for this Chunk --- 
        cmd_setup_b1 = create_command_with_crc(0xB1, bytes([0x00]))
        cmd_setup_a2_1 = create_command_with_crc(0xA2, bytes([0x5D]))
        cmd_setup_a1_1 = create_command_with_crc(0xA1, bytes([0x00]))
        cmd_setup_a2_2 = create_command_with_crc(0xA2, bytes([0x5D]))
        # A9 declares height for this specific feed chunk
        feed_height_le = current_chunk_lines.to_bytes(2, 'little') 
        width_bytes_le = PRINTER_WIDTH_BYTES.to_bytes(2, 'little')
        print_request_data = feed_height_le + width_bytes_le
        cmd_feed_request_a9 = create_command_simple(0xA9, print_request_data)
        # AD signals end of data for this chunk
        end_print_data = bytes([0x00]) 
        cmd_end_feed_ad = create_command_simple(0xAD, end_print_data)

        # --- Send Commands + Blank Data for Chunk --- 
        chunk_success = False
        try:
            # 1. Setup Sequence (B1, A2, A1) -> Wait/Check A1
            async with notification_condition: received_responses.pop(0xA1, None)
            for cmd in [cmd_setup_b1, cmd_setup_a2_1, cmd_setup_a1_1]:
                await client.write_gatt_char(ae01_char.uuid, cmd, response=False); await asyncio.sleep(0.01)
            async with notification_condition:
                try: await asyncio.wait_for(notification_condition.wait_for(lambda: 0xA1 in received_responses), timeout=7.0)
                except asyncio.TimeoutError: raise ValueError("Timeout waiting for A1 response")
                if not check_a1_status(received_responses.pop(0xA1)): raise ValueError("A1 status check failed")

            # 2. Feed Request Sequence (A2, A9) -> Wait/Check A9
            async with notification_condition: received_responses.pop(0xA9, None)
            for cmd in [cmd_setup_a2_2, cmd_feed_request_a9]: 
                await client.write_gatt_char(ae01_char.uuid, cmd, response=False); await asyncio.sleep(0.01)
            async with notification_condition:
                try: await asyncio.wait_for(notification_condition.wait_for(lambda: 0xA9 in received_responses), timeout=7.0)
                except asyncio.TimeoutError: raise ValueError("Timeout waiting for A9 response")
                if not check_a9_status(received_responses.pop(0xA9)): raise ValueError("A9 status check failed")

            # 3. Send Blank Data (AE03)
            print(f"  Sending chunk blank data ({blank_data_len} bytes) to {DATA_WRITE_UUID[-12:-8]}...")
            max_chunk = 20
            for j in range(0, len(blank_data), max_chunk):
                chunk = blank_data[j:j + max_chunk]
                await client.write_gatt_char(ae03_char.uuid, chunk, response=False)
            print("  Finished sending chunk blank data.")

            # 4. Send End Feed Command (AD) -> Wait/Check AA
            async with notification_condition: received_responses.pop(0xAA, None)
            await client.write_gatt_char(ae01_char.uuid, cmd_end_feed_ad, response=False)
            await asyncio.sleep(0.01)

            # Wait for AA notification (feed chunk finished)
            print("  Waiting for AA (Chunk Feed Complete)...")
            async with notification_condition:
                try:
                     timeout_feed_chunk = max(15.0, current_chunk_lines / 20.0) # Rough estimate
                     await asyncio.wait_for(notification_condition.wait_for(lambda: 0xAA in received_responses), timeout=timeout_feed_chunk)
                     payload = received_responses.pop(0xAA)
                     print("    AA notification received.")
                     chunk_success = True
                except asyncio.TimeoutError:
                     print(f"  Warning: AA notification not received for feed chunk {chunk_num}.")
            await asyncio.sleep(0.5)

        except Exception as e:
             print(f"Error during feed chunk {chunk_num}: {e}")
             overall_success = False
             break # Stop trying further chunks if one fails
             
        if not chunk_success: # Handle AA timeout specifically as failure
             overall_success = False
             break

        # Update remaining lines and pause if necessary
        lines_remaining -= current_chunk_lines
        print(f"--- Feed Chunk {chunk_num} Complete. Lines remaining: {lines_remaining} ---")
        if lines_remaining > 0:
             print(f"--- Waiting {DELAY_BETWEEN_PRINTS}s before next feed chunk ---")
             await asyncio.sleep(DELAY_BETWEEN_PRINTS)

    # --- End of Feed Loop --- 
    if overall_success:
        print(f"\nTotal requested feed ({total_lines_to_feed} lines) sequence complete.")
    else:
        print(f"\nFeed sequence failed or was incomplete.")
    return overall_success
# ---------------------------------

# --- Script Logic ---
def validate_args(args):
    """Checks for conflicting or missing command line arguments."""
    is_print_action_specified = bool(args.image or args.folder or args.text)
    is_feed_action_specified = args.feed is not None
    is_test_action_specified = args.test_print
    
    action_count = sum([is_print_action_specified, is_feed_action_specified, is_test_action_specified])

    if action_count == 0:
        print("Error: No action specified. Use -i, -f, -t, -p, or -x.")
        return False
        
    if is_feed_action_specified and (is_print_action_specified or is_test_action_specified):
        print("Error: -p cannot be used with image/folder/text arguments or -x.")
        return False

    if is_test_action_specified and (is_print_action_specified or is_feed_action_specified):
        print("Error: -x cannot be used with image/folder/text arguments or -p.")
        return False
        
    return True # Args are valid

def prepare_print_jobs(args):
    """Prepares a list of (image_object, description) tuples based on arguments."""
    jobs = []
    if args.test_print:
        print("--- Running Test Print Sequence ---")
        # 1. Test Images from standard folder
        if os.path.isdir(TEST_IMAGE_FOLDER):
            print(f"Scanning test image folder: {TEST_IMAGE_FOLDER}")
            try:
                file_list = sorted([f for f in os.listdir(TEST_IMAGE_FOLDER) if f.lower().endswith(SUPPORTED_EXTENSIONS)])
                if not file_list: print(f"No supported image files found in '{TEST_IMAGE_FOLDER}'.")
                else:
                    for filename in file_list:
                        image_path = os.path.join(TEST_IMAGE_FOLDER, filename)
                        img_raw = prepare_image_for_print(image_path, PRINTER_WIDTH_PIXELS)
                        if img_raw:
                            if args.upside_down: 
                                print(f"Rotating '{filename}' 180 degrees.")
                                img_raw = img_raw.rotate(180)
                            jobs.append((img_raw, f"Test Img: {filename}"))
            except Exception as e: print(f"Error processing test image folder '{TEST_IMAGE_FOLDER}': {e}")
        else:
            print(f"Warning: Test image folder '{TEST_IMAGE_FOLDER}' not found. Skipping image tests.")
            
        # 2. Predefined Test Text Jobs
        print("Preparing test text jobs...")
        for text, font_name, font_size in TEST_TEXT_JOBS:
            print(f"  Preparing text: '{text[:40]}...' (Font: {font_name}, Size: {font_size})")
            font = load_font(font_name, font_size) # Use helper
            img_raw = create_text_bitmap(text, font, PRINTER_WIDTH_PIXELS)
            if img_raw:
                 if args.upside_down: 
                     print("    Rotating text 180 degrees.")
                     img_raw = img_raw.rotate(180)
                 jobs.append((img_raw, f"Test Txt: {text[:30]}..."))
            else: print(f"    Error: Could not generate bitmap for text: {text[:30]}...")
        print("--- Test Print Sequence Prepared ---")
            
    else: # Normal print actions (image, folder, text can be combined)
        if args.image:
            img_raw = prepare_image_for_print(args.image, PRINTER_WIDTH_PIXELS)
            if img_raw:
                if args.upside_down: 
                    print("Rotating image 180 degrees.")
                    img_raw = img_raw.rotate(180)
                jobs.append((img_raw, os.path.basename(args.image)))
        
        if args.folder:
            if not os.path.isdir(args.folder): print(f"Error: Folder not found: {args.folder}")
            else:
                print(f"Scanning folder: {args.folder}")
                try:
                    file_list = sorted([f for f in os.listdir(args.folder) if f.lower().endswith(SUPPORTED_EXTENSIONS)])
                    if not file_list: print(f"No supported image files found in '{args.folder}'.")
                    else:
                        for filename in file_list:
                            image_path = os.path.join(args.folder, filename)
                            img_raw = prepare_image_for_print(image_path, PRINTER_WIDTH_PIXELS)
                            if img_raw:
                                if args.upside_down: 
                                    print(f"Rotating '{filename}' 180 degrees.")
                                    img_raw = img_raw.rotate(180)
                                jobs.append((img_raw, filename))
                except Exception as e: print(f"Error processing folder '{args.folder}': {e}")

        if args.text:
            # Use the font specified on the command line
            font = load_font(args.font, args.font_size)
            # Pass alignment to the bitmap creation function
            img_raw = create_text_bitmap(args.text, font, PRINTER_WIDTH_PIXELS, alignment=args.align)
            if img_raw:
                 if args.upside_down:
                     print("Rotating text 180 degrees.")
                     img_raw = img_raw.rotate(180)
                 # Update job description to include alignment
                 jobs.append((img_raw, f"Text: '{args.text[:25]}...' (Font: {args.font}, Size: {args.font_size}, Align: {args.align})"))
                 
    return jobs

async def main(args):
    """Main orchestration function."""
    target_address = args.device if args.device else DEFAULT_ADDRESS

    # 1. Validate Arguments
    if not validate_args(args):
        sys.exit(1)

    # 2. Handle Feed Action (if specified, then exit)
    if args.feed is not None:
        lines_to_feed = args.feed
        print(f"Feed paper mode selected: {lines_to_feed} lines")
        print(f"Attempting to connect to printer at {target_address}...")
        try:
            async with BleakClient(target_address, timeout=20.0) as client:
                if not client.is_connected: print("Failed to connect."); sys.exit(1)
                print(f"Connected to {client.address}")
                try: await client.start_notify(NOTIFY_UUID, notification_handler)
                except Exception as e: print(f"Error enabling notifications: {e}"); sys.exit(1)
                success = await run_feed_paper(client, lines_to_feed)
                await asyncio.sleep(1.0) 
                print("Stopping notifications..."); await client.stop_notify(NOTIFY_UUID)
                print("Disconnected.")
                sys.exit(0 if success else 1)
        except BleakError as e: print(f"Bluetooth Error: {e}"); sys.exit(1)
        except asyncio.TimeoutError: print("Connection timed out."); sys.exit(1)
        except Exception as e: print(f"An unexpected error occurred: {e}"); sys.exit(1)
    
    # 3. Prepare Print Jobs (test mode or normal)
    jobs_to_print = prepare_print_jobs(args)
    if not jobs_to_print:
        print("Error: No valid print jobs could be prepared. Exiting.")
        sys.exit(1)
    print(f"\nTotal print jobs prepared: {len(jobs_to_print)}")

    # 4. Handle Debug Save (if specified, then exit)
    if args.debug_save:
        print("\n--- Debug Save Mode --- ")
        if not os.path.exists("debug_output"): 
            try: os.makedirs("debug_output")
            except OSError as e: print(f"Error creating debug_output directory: {e}"); sys.exit(1)
        print(f"Saving {len(jobs_to_print)} prepared job(s) to 'debug_output/'...")
        for i, (img_to_save, job_desc) in enumerate(jobs_to_print):
            # Create a safe filename from the description
            safe_desc = "".join(c if c.isalnum() or c in ('_', '-', '.') else '_' for c in job_desc)
            if job_desc.startswith("Test Img: "): safe_desc = f"test_img_{safe_desc[10:30]}"
            elif job_desc.startswith("Test Txt: "): safe_desc = f"test_txt_{safe_desc[10:30]}"
            elif job_desc.startswith("Text: "): safe_desc = f"text_{safe_desc[6:30]}"
            elif safe_desc.endswith(SUPPORTED_EXTENSIONS):
                 safe_desc = safe_desc[:-len(os.path.splitext(safe_desc)[1])]
            safe_desc = safe_desc.replace(" ", "_").replace("\n", "_").strip('._-')[:40] # Limit length
            
            suffix = "_rotated" if args.upside_down else ""
            filename = os.path.join("debug_output", f"debug_{i:02d}_{safe_desc}{suffix}.png")
            try:
                img_to_save.save(filename)
                print(f"  Saved: {filename}")
            except Exception as e: print(f"  Error saving {filename}: {e}")
        print("--- Debug Save Complete. Exiting. --- ")
        sys.exit(0) 
        
    # 5. Connect and Print Loop
    print(f"Attempting to connect to printer at {target_address}...")
    overall_success = False # Assume failure unless all jobs succeed
    try:
        async with BleakClient(target_address, timeout=20.0) as client:
            if not client.is_connected: print("Failed to connect."); sys.exit(1)
            print(f"Connected to {client.address}")
            try: await client.start_notify(NOTIFY_UUID, notification_handler)
            except Exception as e: print(f"Error enabling notifications: {e}"); sys.exit(1)

            print("\nStarting print jobs...")
            all_jobs_succeeded = True 
            for i, (img_to_print, job_desc) in enumerate(jobs_to_print):
                print(f"\n--- Starting Print Job {i+1}/{len(jobs_to_print)} --- ")
                success = await run_print_job(client, img_to_print, job_desc)
                if not success:
                    all_jobs_succeeded = False
                                
                # Pause between jobs if more are coming
                if i < len(jobs_to_print) - 1: 
                    print(f"--- Waiting {DELAY_BETWEEN_PRINTS}s before next job ---")
                    await asyncio.sleep(DELAY_BETWEEN_PRINTS)
            
            overall_success = all_jobs_succeeded
            print("\nAll print jobs processed.")
            await asyncio.sleep(1.0) # Short pause before disconnect
            print("Stopping notifications..."); await client.stop_notify(NOTIFY_UUID)
            print("Disconnected.")

    except BleakError as e: print(f"Bluetooth Error: {e}")
    except asyncio.TimeoutError: print("Connection timed out.")
    except Exception as e: print(f"An unexpected error occurred: {e}")
    
    # Exit with appropriate code
    if not overall_success: 
        print("Exiting with error status due to connection/print failure.")
        sys.exit(1) 
    else:
        print("Exiting successfully.")
        sys.exit(0)

def list_system_fonts():
    """Lists available system fonts using matplotlib."""
    if not MATPLOTLIB_AVAILABLE:
        print("Matplotlib is not installed. Cannot list system fonts.")
        print("Please install it with: pip install matplotlib")
        return

    print("Available system fonts:")
    fonts = sorted(list(set(f.name for f in font_manager.fontManager.ttflist)))
    for font_name in fonts:
        print(f"- {font_name}")

def show_help():
    """Displays a detailed help message with examples."""
    help_text = """
MX01W Print CLI - Thermal Printer Control Tool
=========================================

Usage:
    python catprint_cli.py [options] [action]

Actions:
    -i, --image <file>     Print a single image file
    -f, --folder <dir>     Print all images from a folder
    -t, --text <string>    Print text
    -p, --feed [lines]     Feed paper (default: 40 lines)
    -x, --test-print       Run test sequence
    -h, --help            Show this help message

Options:
    -d, --device <addr>    Bluetooth MAC address
    -s, --debug-save       Save bitmaps to files instead of printing
    -u, --upside-down      Print upside down
    -z, --font-size <size> Font size for text (default: 24)
    -n, --font <name>      Font name for text (default: Arial)
    -a, --align <pos>      Text alignment: left/center/right (default: left)
    -l, --list-fonts       List available system fonts

Examples:
    1. Print a single image:
       python catprint_cli.py -i photo.png

    2. Print text with custom font and size:
       python catprint_cli.py -t "Hello World" -n "Courier New" -z 32

    3. Print text centered:
       python catprint_cli.py -t "Centered Text" -a center

    4. Print all images from a folder:
       python catprint_cli.py -f images/

    5. Feed paper 50 lines:
       python catprint_cli.py -p 50

    6. Run test sequence:
       python catprint_cli.py -x

    7. Save debug output:
       python catprint_cli.py -i image.png -s

    8. Print upside down:
       python catprint_cli.py -t "Upside Down" -u

    9. Use different printer:
       python catprint_cli.py -d 00:11:22:33:44:55 -t "Hello"

Notes:
    - Multiple actions can be combined (e.g., -i and -t)
    - --feed cannot be used with other actions
    - --test-print cannot be used with other actions
    - Use --list-fonts to see available system fonts
"""
    print(help_text)

if __name__ == "__main__":
    # Setup command line argument parsing
    parser = argparse.ArgumentParser(description="Print images or text to a Thermal Printer (MXW01 protocol). Use --test-print for a predefined sequence.")
    # Print Content Arguments
    parser.add_argument("-i", "--image", help="Path to a single image file to print.")
    parser.add_argument("-f", "--folder", help="Path to a folder containing images to print.")
    parser.add_argument("-t", "--text", help="Text string to print.")
    # Action Arguments
    parser.add_argument("-p", "--feed", type=int, default=None, const=40, nargs='?', help="Feed paper by specified lines (default: 40). Cannot be used with other actions.")
    parser.add_argument("-x", "--test-print", action="store_true", help=f"Run a test sequence (images from '{TEST_IMAGE_FOLDER}/', various texts). Cannot be used with other actions.")
    # Global Options
    parser.add_argument("-d", "--device", default=DEFAULT_ADDRESS, help=f"Bluetooth MAC address of the printer (default: {DEFAULT_ADDRESS})")
    parser.add_argument("-s", "--debug-save", action="store_true", help="Save prepared bitmaps to files instead of printing.")
    parser.add_argument("-u", "--upside-down", action="store_true", help="Print the image(s) or text upside down.")
    parser.add_argument("-z", "--font-size", type=int, default=DEFAULT_FONT_SIZE, help=f"Font size for text printing (default: {DEFAULT_FONT_SIZE})")
    parser.add_argument("-n", "--font", default=DEFAULT_FONT_NAME, help=f"Font name for text printing (default: {DEFAULT_FONT_NAME}). Use --list-fonts to see available system fonts.")
    parser.add_argument("-a", "--align", choices=['left', 'center', 'right'], default='left', help="Text alignment (default: left).")
    parser.add_argument("-l", "--list-fonts", action="store_true", help="List available system fonts and exit.")
    
    args = parser.parse_args()

    # Handle --list-fonts before any other processing
    if args.list_fonts:
        list_system_fonts()
        sys.exit(0)

    asyncio.run(main(args)) 
