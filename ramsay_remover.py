import os

START_HEX = "704E3634526161666151666A57586A4D334B7533556B7150"
END_HEX   = "394A37755154716754786871486147557565356361614572334B55"

START_BYTES = bytes.fromhex(START_HEX)
END_BYTES = bytes.fromhex(END_HEX)


def process_file(filepath):
    try:
        with open(filepath, "rb") as f:
            data = f.read()

        start_index = data.find(START_BYTES)
        end_index = data.find(END_BYTES)

        if start_index == -1 or end_index == -1 or end_index <= start_index:
            return  # markers not found

        # Move start to end of START marker
        start_index += len(START_BYTES)

        extracted = data[start_index:end_index]

        if not extracted:
            return

        # Backup original file (recommended)
        # backup_path = filepath + ".bak"
        # if not os.path.exists(backup_path):
        #     with open(backup_path, "wb") as f:
        #         f.write(data)

        # Overwrite original file with extracted content
        with open(filepath, "wb") as f:
            f.write(extracted)

        print(f"[+] Processed: {filepath}")

    except Exception as e:
        print(f"[!] Error processing {filepath}: {e}")


def scan_directory(root_folder):
    for root, dirs, files in os.walk(root_folder):
        for file in files:
            if file.lower().endswith(".exe"):
                full_path = os.path.join(root, file)
                process_file(full_path)


if __name__ == "__main__":
    target_folder = input("Enter folder path: ").strip()
    scan_directory(target_folder)