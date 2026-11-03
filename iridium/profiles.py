"""Build-specific layouts and observed software integration boundaries.

These profiles describe upgrade images, not a claim of complete board emulation.
See docs/9575-firmware.md and docs/hardware-evidence.md for their evidence.
"""

from dataclasses import dataclass


KEY_CODES = {str(n): 0x64 + n for n in range(10)} | {
    "*": 0x79, "#": 0x78, "up": 0x82, "down": 0x83,
    "soft_left": 0x96, "soft_right": 0x97, "green": 0x8D,
    "red": 0x8C, "volume_up": 0xA0, "volume_down": 0xA1, "convenience": 0xAA,
}


@dataclass(frozen=True)
class HandsetProfile:
    model: str
    name: str
    version: str
    product: int
    code_bytes: int
    data_bytes: int
    avr_bytes: int
    trx_bytes: int
    ptt_bytes: int
    directory_pointer: int
    directory_slots: int
    animation_file: int
    graphics_pointer: int
    key_callback: int
    key_entry: int
    graphics_init: int
    application_setup: int
    power_on: int

    @property
    def payload_bytes(self) -> int:
        return self.code_bytes + self.data_bytes

    @property
    def image_sizes(self) -> dict[str, int]:
        return {"bc5": self.payload_bytes, "avr": self.avr_bytes,
                "trx": self.trx_bytes, "ptt": self.ptt_bytes}

    @property
    def keys(self) -> set[str]:
        return set(KEY_CODES) | {"power"} | ({"sos"} if self.model == "9575" else set())

    @property
    def key_codes(self) -> dict[str, int]:
        return KEY_CODES | ({"sos": 0xAB} if self.model == "9575" else {})

    def describe(self) -> dict:
        return {"model": self.model, "name": self.name, "firmware_version": self.version,
                "keys": sorted(self.keys)}


PROFILES = {
    "9555": HandsetProfile(
        model="9555", name="Iridium 9555", version="HT25003", product=0xA555,
        code_bytes=0x3096BE, data_bytes=0x78FC, avr_bytes=8678,
        trx_bytes=0x260760, ptt_bytes=0xA7BF8,
        directory_pointer=0x2BD6, directory_slots=140, animation_file=19,
        graphics_pointer=0xF719, key_callback=0xF6FB, key_entry=0x67F04,
        graphics_init=0x6365E, application_setup=0x8CC8C, power_on=0x6BE4C),
    "9575": HandsetProfile(
        model="9575", name="Iridium 9575 Extreme", version="HL25003", product=0x9575,
        code_bytes=0x363E4A, data_bytes=0x7CD8, avr_bytes=14296,
        trx_bytes=0x260760, ptt_bytes=0xA7BF8,
        directory_pointer=0x2BD6, directory_slots=140, animation_file=21,
        graphics_pointer=0xF72C, key_callback=0xF70E, key_entry=0x67F04,
        graphics_init=0x6365E, application_setup=0x93788, power_on=0x6BED0),
}
