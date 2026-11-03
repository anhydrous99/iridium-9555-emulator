import unittest

from iridium.lcd import ST7541


INIT = bytes.fromhex(
    "38 00 A1 C0 44 00 AB 27 81 27 57 48 80 64 2C 67 2E "
    "2F 4C 0F F7 1A F3 0D 88 00 89 00 8A AA 8B AA 8C 77 "
    "8D 77 8E FF 8F FF 93 A6 AF"
)


class LCDTest(unittest.TestCase):
    def test_original_controller_initialization_preserves_undefined_ddram(self):
        lcd = ST7541()
        for value in INIT:
            lcd.feed(bytes([value]))
        state = lcd.state()
        self.assertTrue(state["display_on"])
        self.assertTrue(state["adc_reverse"])
        self.assertEqual(state["known_pixels"], 0)
        self.assertEqual(state["written_bytes"], 0)
        self.assertIsNone(state["error"])

    def test_planes_page_layout_and_partial_transfers(self):
        lcd = ST7541()
        lcd.feed(bytes.fromhex("AF B1 10 02 E8 01 81"))
        self.assertEqual(lcd.state()["known_pixels"], 0)
        lcd.feed(bytes([0x02]))
        state = lcd.state()
        self.assertEqual(state["pixels"][8 * 128 + 2], 2)
        self.assertEqual(state["pixels"][9 * 128 + 2], 1)
        self.assertEqual(state["pixels"][15 * 128 + 2], 2)
        self.assertEqual(state["known_pixels"], 8)

    def test_data_that_looks_like_commands_and_256_byte_length(self):
        lcd = ST7541()
        lcd.feed(bytes.fromhex("AF E8 FF") + bytes([0xAF, 0xAE]) * 128)
        self.assertTrue(lcd.display_on)
        self.assertEqual(lcd.column, 0)
        self.assertEqual(lcd.page, 0)
        self.assertEqual(lcd.state()["known_pixels"], 1024)
        self.assertEqual(lcd.data_bytes, 256)

    def test_column_wrap_stays_in_page_and_address_command_resets_plane(self):
        lcd = ST7541()
        lcd.feed(bytes.fromhex("AF B3 17 0F E8 03 01 01 02 02"))
        state = lcd.state()
        self.assertEqual(state["pixels"][24 * 128 + 127], 3)
        self.assertEqual(state["pixels"][25 * 128], 3)
        self.assertEqual(lcd.page, 3)
        lcd.feed(bytes.fromhex("E8 00 FF 00"))
        self.assertEqual(lcd.column & 1, 0)

    def test_output_direction_scrolling_and_override_precedence(self):
        lcd = ST7541()
        lcd.feed(bytes.fromhex("AF E8 01 01 01 A1 C8"))
        self.assertEqual(lcd.state()["pixels"][127 * 128 + 127], 3)
        lcd.feed(bytes.fromhex("C0 40 01"))
        self.assertEqual(lcd.state()["pixels"][127 * 128 + 127], 3)
        lcd.feed(bytes.fromhex("A7"))
        self.assertEqual(lcd.state()["pixels"][127 * 128 + 127], 0)
        lcd.feed(bytes.fromhex("A5"))
        self.assertEqual(set(lcd.state()["pixels"]), {3})
        lcd.feed(bytes.fromhex("AE"))
        self.assertEqual(set(lcd.state()["pixels"]), {0})

    def test_handset_segment_wiring_preserves_adc_and_known_pixel_direction(self):
        lcd = ST7541(segment_zero_on_right=True)
        lcd.feed(INIT)
        # Three asymmetric columns under the firmware's A1: black, dark, light.
        lcd.feed(bytes.fromhex("B0 10 00 E8 05 01 01 01 00 00 01"))
        state = lcd.state()
        self.assertEqual(state["pixels"][:3], [3, 2, 1])
        self.assertEqual(state["known"][:4], [True, True, True, False])
        self.assertFalse(state["known"][127])
        self.assertEqual(state["coordinates"], "SEG127 left, COM0 top")

        # Firmware can still reverse the image by changing ADC, without changing RAM.
        before = bytes(lcd.ram)
        lcd.feed(bytes.fromhex("A0"))
        state = lcd.state()
        self.assertEqual(state["pixels"][125:128], [1, 2, 3])
        self.assertEqual(state["known"][124:128], [False, True, True, True])
        self.assertFalse(state["known"][0])
        self.assertEqual(bytes(lcd.ram), before)
        self.assertEqual(state["known_pixels"], 24)

    def test_handset_mapping_survives_controller_reset_and_com_reversal(self):
        lcd = ST7541(segment_zero_on_right=True)
        lcd.feed(bytes.fromhex("AF A1 E8 01 01 01 C8 E2"))
        state = lcd.state()
        self.assertEqual(state["pixels"][127 * 128], 3)
        self.assertTrue(state["known"][127 * 128])
        self.assertFalse(state["known"][-1])
        self.assertTrue(state["segment_zero_on_right"])

    def test_sleep_preserves_display_ram_and_on_register(self):
        lcd = ST7541()
        lcd.feed(bytes.fromhex("AF E8 01 FF FF A9"))
        self.assertFalse(lcd.state()["display_on"])
        lcd.feed(bytes.fromhex("E1"))
        self.assertTrue(lcd.state()["display_on"])
        self.assertEqual(lcd.state()["pixels"][0], 3)

    def test_software_reset_preserves_ram_and_display_output_registers(self):
        lcd = ST7541()
        lcd.feed(bytes.fromhex("AF A1 C8 E8 01 01 01 40 07 E2"))
        self.assertTrue(lcd.display_on)
        self.assertTrue(lcd.adc_reverse)
        self.assertTrue(lcd.com_reverse)
        self.assertEqual(lcd.start_line, 0)
        self.assertEqual(lcd.state()["pixels"][-1], 3)

    def test_read_modify_write_restores_column(self):
        lcd = ST7541()
        lcd.feed(bytes.fromhex("10 03 E0 E8 01 FF FF EE"))
        self.assertEqual(lcd.column, 6)

    def test_unknown_command_or_unsupported_configuration_latches_error(self):
        for stream in ("18", "A3", "48 40", "44 01", "F7 00", "EE", "38 01"):
            with self.subTest(stream=stream):
                lcd = ST7541()
                with self.assertRaises(ValueError):
                    lcd.feed(bytes.fromhex(stream))
                self.assertIsNotNone(lcd.state()["error"])
                with self.assertRaises(ValueError):
                    lcd.feed(INIT)


if __name__ == "__main__":
    unittest.main()
