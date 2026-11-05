"""
Generates a virtual monitor EDID (256 bytes: base block + CTA-861 extension)
with the requested resolutions, each one on a chosen pixel clock.

The clock matters: the Rockchip HDMI (RK3566/RK3568) rejects with NOCLOCK
every mode whose clock the PLL cannot generate exactly, which is why the
Lenovo ultrawide.bin (319.75 MHz, 181.25 MHz...) does not come up on the Orange Pi.

Usage:
  python3 -m virtual_monitor.edid output.bin 3440x1440@312:60 2560x1080@216:60 ...
    each mode is WIDTHxHEIGHT@CLOCK_MHZ[:TARGET_HZ] (TARGET_HZ defaults to 60)
  python3 -m virtual_monitor.edid output.bin 3440x1440@312 --vic 16 --vic 4
    adds standard CEA modes by VIC number
"""

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

# Minimum blanking, CVT reduced blanking style
H_FRONT, H_SYNC, H_BLANK_MIN = 48, 32, 160
V_FRONT, V_SYNC, V_BLANK_MIN = 3, 10, 23

# Physical size of a 34" ultrawide in mm
WIDTH_MM, HEIGHT_MM = 800, 335

# Timing descriptor limits: 12 bits per measure, clock in 16 bits of 10 kHz
MAX_PIXELS = 4095
MAX_CLOCK_KHZ = 0xFFFF * 10

# What the app offers: clocks the RK3566 PLL generates exactly
DEFAULT_MODES = ("3440x1440@312", "2560x1080@216", "3008x1260@241.5")
DEFAULT_VICS = (16, 4)  # 1080p60 and 720p60
DEFAULT_NAME = "Virtual UW"

# Where scripts/install-edid.sh copies the EDID
INSTALLED = Path("/usr/lib/firmware/edid/ultrawide.bin")


class EdidError(ValueError):
    """Invalid mode or EDID that does not fit in 256 bytes."""


@dataclass(frozen=True)
class Timing:
    width: int
    height: int
    clock_khz: int
    htotal: int
    vtotal: int

    @property
    def refresh(self) -> float:
        return self.clock_khz * 1000 / (self.htotal * self.vtotal)

    def label(self) -> str:
        return f"{self.width}x{self.height} @ {self.clock_khz / 1000:g} MHz = {self.refresh:.2f} Hz"


def _positive(value: float) -> bool:
    return math.isfinite(value) and value > 0


def build_timing(width: int, height: int, clock_mhz: float, target_hz: float = 60.0) -> Timing:
    """Picks htotal/vtotal to get close to target_hz with the fixed clock."""
    if not (0 < width <= MAX_PIXELS and 0 < height <= MAX_PIXELS):
        raise EdidError(f"Resolution beyond the {MAX_PIXELS} pixel limit: {width}x{height}")

    if not (_positive(clock_mhz) and _positive(target_hz)):
        raise EdidError(f"Clock and rate must be positive: {clock_mhz} MHz, {target_hz} Hz")

    clock_khz = round(clock_mhz * 1000)
    if clock_khz > MAX_CLOCK_KHZ:
        raise EdidError(f"Clock above {MAX_CLOCK_KHZ / 1000:g} MHz: {clock_mhz:g}")

    clock_hz = clock_mhz * 1_000_000
    htotal = width + H_BLANK_MIN
    vtotal = max(height + V_BLANK_MIN, round(clock_hz / (htotal * target_hz)))
    if vtotal - height > MAX_PIXELS:
        raise EdidError(f"Clock too high for {width}x{height} at {target_hz:g} Hz")

    # Fine line adjustment; vtotal already absorbed the clock, so hblank stays at the minimum (+1 from rounding)
    htotal = max(width + H_BLANK_MIN, round(clock_hz / (vtotal * target_hz)))
    return Timing(width, height, clock_khz, htotal, vtotal)


def parse_mode(text: str) -> Timing:
    """WIDTHxHEIGHT@CLOCK_MHZ[:TARGET_HZ], like 3440x1440@312 or 2560x1080@216:50."""
    size, _, rest = text.partition("@")
    clock, _, hz = rest.partition(":")
    try:
        width, height = (int(n) for n in size.lower().split("x"))
        clock_mhz = float(clock)
        target_hz = float(hz or 60)
    except ValueError:
        raise EdidError(f"Invalid mode: {text} (use WIDTHxHEIGHT@MHZ[:HZ])") from None

    return build_timing(width, height, clock_mhz, target_hz)


def detailed_timing(timing: Timing) -> bytes:
    hblank = timing.htotal - timing.width
    vblank = timing.vtotal - timing.height
    clock = timing.clock_khz // 10

    dtd = bytearray(18)
    dtd[0], dtd[1] = clock & 0xFF, clock >> 8
    dtd[2], dtd[3] = timing.width & 0xFF, hblank & 0xFF
    dtd[4] = (timing.width >> 8) << 4 | hblank >> 8
    dtd[5], dtd[6] = timing.height & 0xFF, vblank & 0xFF
    dtd[7] = (timing.height >> 8) << 4 | vblank >> 8
    dtd[8], dtd[9] = H_FRONT, H_SYNC
    dtd[10] = (V_FRONT & 0xF) << 4 | (V_SYNC & 0xF)
    dtd[11] = 0
    dtd[12], dtd[13] = WIDTH_MM & 0xFF, HEIGHT_MM & 0xFF
    dtd[14] = (WIDTH_MM >> 8) << 4 | HEIGHT_MM >> 8
    dtd[17] = 0x1E  # digital, separate sync, +hsync +vsync

    return bytes(dtd)


def name_descriptor(name: str) -> bytes:
    try:
        text = name.encode("ascii")[:13]
    except UnicodeEncodeError:
        raise EdidError(f"The monitor name must be ASCII: {name}") from None

    if len(text) < 13:
        text += b"\n" + b" " * (12 - len(text))

    return bytes([0, 0, 0, 0xFC, 0]) + text


def checksum(block: bytearray) -> None:
    block[127] = (256 - sum(block[:127]) % 256) % 256


def base_block(descriptors: list[bytes]) -> bytearray:
    block = bytearray(128)
    block[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    block[8:10] = (0x5904).to_bytes(2, "big")  # manufacturer "VHD"
    block[10:12] = (1).to_bytes(2, "little")  # product
    block[16], block[17] = 1, 2024 - 1990  # week, year
    block[18], block[19] = 1, 3  # EDID 1.3
    block[20] = 0x80  # digital input
    block[21], block[22] = WIDTH_MM // 10, HEIGHT_MM // 10
    block[23] = 0x78  # gamma 2.2
    block[24] = 0x06  # sRGB, preferred mode in the first descriptor
    block[25:35] = bytes.fromhex("ee91a3544c99260f5054")  # sRGB colors
    block[38:54] = b"\x01" * 16  # no standard timings

    for i, descriptor in enumerate(descriptors):
        block[54 + 18 * i : 72 + 18 * i] = descriptor

    block[126] = 1  # one extension
    checksum(block)
    return block


def cta_block(vics: list[int], dtds: list[bytes]) -> bytearray:
    if len(vics) > 31 or not all(1 <= vic <= 127 for vic in vics):
        raise EdidError("Provide up to 31 VICs, each from 1 to 127")

    data = bytearray()
    if vics:
        data += bytes([0x40 | len(vics)]) + bytes(vics)

    # HDMI Vendor Specific Data Block: address 1.0.0.0, max TMDS 340 MHz
    data += bytes([0x67, 0x03, 0x0C, 0x00, 0x10, 0x00, 0x00, 340 // 5])

    block = bytearray(128)
    block[0], block[1] = 0x02, 0x03
    block[2] = 4 + len(data)
    block[4 : 4 + len(data)] = data

    offset = 4 + len(data)
    for dtd in dtds:
        if offset + 18 > 127:
            raise EdidError("Too many modes to fit in the EDID")
        block[offset : offset + 18] = dtd
        offset += 18

    checksum(block)
    return block


def build_edid(timings: list[Timing], vics: list[int], name: str = DEFAULT_NAME) -> bytes:
    """The first three modes go in the base block (the first is the preferred one); the rest go in the extension."""
    if not timings:
        raise EdidError("Provide at least one mode")

    dtds = [detailed_timing(t) for t in timings]
    base = dtds[:3] + [name_descriptor(name)]
    return bytes(base_block(base) + cta_block(list(vics), dtds[3:]))


def generate(texts: list[str], vics=DEFAULT_VICS, name: str = DEFAULT_NAME) -> tuple[list[Timing], bytes]:
    """Mode strings to (timings, EDID). Raises EdidError if something does not fit."""
    timings = [parse_mode(text) for text in texts]
    return timings, build_edid(timings, vics, name)


def is_installed(texts: list[str]) -> bool:
    """Whether the EDID for these modes is the one scripts/install-edid.sh installed."""
    try:
        data = generate(texts)[1]
        return INSTALLED.read_bytes() == data
    except (EdidError, OSError):
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m virtual_monitor.edid", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("modes", nargs="+", help="WIDTHxHEIGHT@CLOCK_MHZ[:TARGET_HZ]")
    parser.add_argument("--vic", type=int, action="append", default=[], help="standard CEA mode (VIC)")
    parser.add_argument("--name", default=DEFAULT_NAME)
    args = parser.parse_args(argv)

    try:
        timings, data = generate(args.modes, args.vic, args.name)
    except EdidError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    args.output.write_bytes(data)
    for timing in timings:
        print(timing.label())

    if args.vic:
        print("VICs:", " ".join(str(v) for v in args.vic))

    return 0


if __name__ == "__main__":
    sys.exit(main())
