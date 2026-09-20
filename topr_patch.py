import argparse
import hashlib
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile

try:
    import pefile
except ImportError:
    sys.exit("Install the required package with: python -m pip install pefile")


SOURCE_SHA256 = "ca846f1a08c9da22d2aa6f877fe691e98b1e83da6e492557c5f8d410fa419cd8"
PATCHED_SHA256 = "7c1aedfb1c88c0e653c118be03d8995292130112125907bf63ac2722314ea206"
IMAGE_BASE = 0x400000
CALLBACK_ADDRESS = 0x4B6398
PATCH_ADDRESS = 0x4B63AF
VIEWER_RENDER_ADDRESS = 0x4B61CC
MAIN_RENDER_CALLS = (0x534130, 0x53413D)

CALLBACK = bytes.fromhex(
    "8b9008020000807a2000750e80bac80000000075058b10ff527cc3"
)
REGISTRATION = bytes.fromhex(
    "899efc0000008b038b80c80000008986f8000000"
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_at(image, address, size):
    return image.get_data(address - IMAGE_BASE, size)


def verify(data):
    if sha256(data) != SOURCE_SHA256:
        raise ValueError("Unrecognized topr.exe; refusing to patch this build.")

    image = pefile.PE(data=data)
    if image.FILE_HEADER.Machine != 0x14C:
        raise ValueError("Expected a 32-bit x86 executable.")
    if image.OPTIONAL_HEADER.ImageBase != IMAGE_BASE:
        raise ValueError("Unexpected image base.")
    if image.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size:
        raise ValueError("Refusing to invalidate an Authenticode signature.")
    if read_at(image, CALLBACK_ADDRESS, len(CALLBACK)) != CALLBACK:
        raise ValueError("Unexpected GLScene buffer-change callback.")
    if read_at(image, 0x4B5F32, len(REGISTRATION)) != REGISTRATION:
        raise ValueError("Unexpected GLScene callback registration.")

    code_section = image.sections[0]
    code = code_section.get_data()
    class_name_address = IMAGE_BASE + code_section.VirtualAddress + code.find(
        b"\x0eTGLSceneViewer"
    )
    if class_name_address < IMAGE_BASE + code_section.VirtualAddress:
        raise ValueError("Cannot find TGLSceneViewer metadata.")

    references = []
    needle = struct.pack("<I", class_name_address)
    cursor = 0
    while True:
        offset = code.find(needle, cursor)
        if offset < 0:
            break
        cursor = offset + len(needle)
        vtable = IMAGE_BASE + code_section.VirtualAddress + offset + 44
        if read_at(image, vtable - 76, 4) == struct.pack("<I", vtable):
            references.append(vtable)
    if len(references) != 1:
        raise ValueError("Cannot uniquely verify the TGLSceneViewer VMT.")

    vtable = references[0]
    if read_at(image, vtable + 0xC8, 4) != struct.pack("<I", CALLBACK_ADDRESS):
        raise ValueError("The viewer VMT does not reference the expected callback.")

    for call_address in MAIN_RENDER_CALLS:
        displacement = VIEWER_RENDER_ADDRESS - call_address - 5
        if read_at(image, call_address, 5) != b"\xe8" + struct.pack("<i", displacement):
            raise ValueError("Expected explicit main-loop rendering is missing.")

    patch_rva = PATCH_ADDRESS - IMAGE_BASE
    for block in image.DIRECTORY_ENTRY_BASERELOC:
        for entry in block.entries:
            if entry.type and patch_rva <= entry.rva < patch_rva + 3:
                raise ValueError("Unexpected relocation on the patch instruction.")

    return image


def patch(data):
    image = verify(data)
    result = bytearray(data)
    offset = image.get_offset_from_rva(PATCH_ADDRESS - IMAGE_BASE)
    result[offset:offset + 3] = b"\x90\x90\x90"

    patched = pefile.PE(data=bytes(result))
    checksum_offset = patched.OPTIONAL_HEADER.get_field_absolute_offset("CheckSum")
    struct.pack_into("<I", result, checksum_offset, patched.generate_checksum())

    result = bytes(result)
    if sha256(result) != PATCHED_SHA256:
        raise ValueError("Patched output does not match the verified release build.")
    return result


def write_backup(path, data):
    created = False
    try:
        with path.open("xb") as backup:
            created = True
            backup.write(data)
            backup.flush()
            os.fsync(backup.fileno())
    except FileExistsError:
        existing = path.read_bytes()
        if sha256(existing) != SOURCE_SHA256:
            raise ValueError(f"Refusing to overwrite an unexpected backup: {path}")
    except OSError:
        if created:
            path.unlink(missing_ok=True)
        raise


def replace_file(path, data):
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
            delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        shutil.copystat(path, temporary_path)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main():
    parser = argparse.ArgumentParser(
        description="Patch Tragedy of Prince Rupert for Steam Deck/Proton."
    )
    parser.add_argument(
        "--input", type=Path, default=Path(__file__).with_name("topr.exe")
    )
    parser.add_argument(
        "--backup", type=Path, help="Backup path (default: topr-original.exe beside the input)"
    )
    arguments = parser.parse_args()
    input_path = arguments.input.resolve()
    backup_path = (
        arguments.backup.resolve()
        if arguments.backup is not None
        else input_path.with_name("topr-original.exe")
    )

    if input_path == backup_path:
        raise ValueError("The backup path must differ from the game executable.")

    original = input_path.read_bytes()
    current_hash = sha256(original)
    if current_hash == PATCHED_SHA256:
        if not backup_path.exists() or sha256(backup_path.read_bytes()) != SOURCE_SHA256:
            raise ValueError("The game is already patched, but a valid backup is missing.")
        print(f"Already patched: {input_path}")
        print(f"Backup: {backup_path}")
        return

    result = patch(original)
    write_backup(backup_path, original)
    replace_file(input_path, result)
    if sha256(input_path.read_bytes()) != PATCHED_SHA256:
        raise ValueError("Patched file verification failed; restore the backup.")

    print(f"Patched: {input_path}")
    print(f"Backup: {backup_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        sys.exit(error)