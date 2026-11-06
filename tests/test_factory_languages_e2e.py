"""The remaining 22 factory menu locales, including non-Latin saved widgets.

English/French journeys live in test_factory_customization_e2e.py. These exact
128x128 LCD oracles come from inspected native factory captures on both models;
they cover the Language widgets, selection marks and translated soft keys.
They do not establish every translated screen or predictive text behavior.
"""

import os
import unittest

from factory_handset import FactoryHandset, HOME_CAPTIONS


ENGLISH_PARENT = 'b2800c4484e844cbff1f9585c8adba9a968aff23a9f8083285741996a8ff33ce'

SELECTOR_ROWS = (
    'b1663383c687721323f80859352aa3a4a289c9acbc7bc9483592ae3bbfa8e1a2',  # 0: English
    '57e678428e24ac724fadce0bc0cbf4ebe77dae44970801bd7728c5879634f708',  # 1: Čeština
    '6cad616e30aab69b7ad8173da4132c2da0a8f66d89330757aaa1b2bc50adf353',  # 2: Dansk
    '6b662a09c7234420823ce07e07503a4a13768d7b2ee2b9e795faa1e42f4f84d3',  # 3: Nederlands
    '59ef5ae4db81c2d9ae3b2ac31daba467236937ec5ab50d373a18749948a597fc',  # 4: Suomi
    'e200fcde6ee79a66a10500380a337e536e9b1c2b682eb9bce83b74c010829e01',  # 5: Français
    'd35d6ff496e3fb2e00db4c505d67347a622dad269f2109265d7099700d614d3b',  # 6: Deutsch
    'abfd04be9ff5c0b5c4db8371f69bb9ac8d95ea7ae7ded15416872143c9383715',  # 7: Ελληνικά
    'd710dfb074f2920bc85614172cce3feaf8dc67da3673ee6f5b21141d07f76d9d',  # 8: Magyar
    '707e903bf46b3fe24ff39a30abc5477aaea7e8970ef3543c45d0b75f32019f86',  # 9: Italiano
    '9724aeb164706160b68190b8d027b9a1f56cb8045c7ce329b937ac800832afbb',  # 10: Norsk
    'c1b939da6e690fa60580b963f169a5f0a010f89216598ae0f5f57ca52a000a09',  # 11: Polski
    'e0bebf46a2a12f532abedcbcb2148b7cea85d4d153348c07c7745810ce142a5f',  # 12: Español
    'ff8313b924d1664df632e9d8da3e4ce2d996da61adced83d27432e7821c5c5b6',  # 13: Svensk
    'dcf089320ce14635d7868a23cc3abe543512def9659f3daebf947e2eb23a6b4a',  # 14: Türkçe
    '48e65f189a5cc46b2af4643085ca43400a575483b1b4208179b0061fd97ad907',  # 15: Português
    '42f774997d43eb4ce23ef21246242405330b6ec5305cd43e833a9215a532f6ea',  # 16: 简体中文
    '1cb8e9d6d0af35d6e08c5be869d1f917162dec78fcd9d2de0b4af4d4f49b7617',  # 17: 繁體中文
    'cdd3028d65e6da7b85db4d240b9af62ae831b123fc8fd223364f41c8ce55a106',  # 18: 日本語
    'b1ea8d334d1b259a5b40a3a985ceec03468016673545bae0848bfb933b75542a',  # 19: 한국인
    '95347e388e97065b3f31e15e3bcc8846eb9e26a13422622984454cf824ddb2dc',  # 20: Русский
    'b17f1c8aad2d66d7692833b1e65ccf7216118bef3f3c197e68f011beea1db40d',  # 21: عربي
    'b90135afde1c9b3c1f73f6bc4aed6e4e2cc9a831856fd01f16bac25d1efc3ca8',  # 22: עברית
    'd530d850e469d2846ff9d91a179b24a26fa385db55be1cf64c83b5e534237607',  # 23: کوردی سۆرانی
)

# Index, original locale name, localized parent, tentative English, saved radio.
LOCALES = (
    (1, 'Čeština',
     'a6eb16a663bc262511b9c524e15660f87207263046e8972a6704c45707106c33',
     'dff8000f8f451cd2482bd122e53ff6ce95fb8d92b75ca9597cc4dc649279f4f3',
     '39dc6229c79c253059bdc64c8d25c399ab881d3e551ff6ea30dcfef482e976a5'),
    (2, 'Dansk',
     'eaae4b8b0c7dbf35c9c501b8325da63018e98157b229ae8ad3395239861a29b1',
     'e0216d3001a0f720e8d32d99cbd9b74ce85058998702b4e5d45b344178b2a2b1',
     '66b304449dec6d569ccfb35ffb2280146727ef1252db0d424c6eadd901d25105'),
    (3, 'Nederlands',
     'c881853d0223db3be8a38c78d92dbdf79e699e6bbac627a23015006ed3964cc8',
     '5242f27af5d7e1436173b33aefe8d3533df1a42dbe334bbc5b0a7dc58cb81605',
     '1639d6a3b5e76a33399aa7fe675f1bcf2328d708ad842f655cff847eda04b5dc'),
    (4, 'Suomi',
     'de35efa34692419bca5ec7fee36184fc8dc1d2fb2ed7b6e08e700e16202fb7ac',
     'ac9393017aab9865da7a4c9a89c38d78d089fdb746292c0aad1e71edc3d3241a',
     '16d87391a585bb31d312587736fac9ab89a96f056101c1deddb4ca7916971a21'),
    (6, 'Deutsch',
     '7c4ccc3da32623fd9f42a00136978e54e6506321d24d52b3796fd6c1e3a74d1f',
     'f76c7d8bda79d11755ad368c337f670cc7527ce1e8390c0a2b75b203b2e5d1e2',
     '12e409b95f7a88cf6ee2bf91548fc35008868cfd6d39232d8edd61388790690c'),
    (7, 'Ελληνικά',
     'e50dd2e9e235a6119c2326299aac6122377e2f5158e1e2983b496c6f3a62aa37',
     '7961350aa8873af76bc79443ceeb50f44fed37398f003502188ba499f6b464c7',
     '54582f4208fb2724218742f4c3ad8f0f46dfd53f6c8970d4fdec5b0494bf0c83'),
    (8, 'Magyar',
     '21a94820b534c49a4a531fad001f6a1b6ba3692791986e268a975d7fb29c9bc0',
     '8f8c94be0c9bc6cbcfda6b5dfb741c1957bbab94cf6703194e41dd2b0cdf1822',
     '7a73eec27a90dcd0b32e105507df0a599a8a21f3c6f50cc042cb2326a9ef3b0f'),
    (9, 'Italiano',
     '968a79a7626ea52d8ff21c831a3112a94987850212d91841c619e5e3cfa6f571',
     '6bd12232c63bfb3b807ae5ce25c972f0fbeda26905cd35d17fe10f5768bdc13d',
     '48c9b37ec670ebf299b5350de4f664ab276e69269d74a9b24cdae6763faa683a'),
    (10, 'Norsk',
     'c7c84782820e7d8b981be30eea656c7e854d70ced09929992f60fb063cc3e69a',
     'd614e4bc423bc9f87501128b7471f1e58854e0c6276ecc0cc4bc0ec25cee077c',
     '80b1c0268cbc5186f1796c673f99b2ee16e331c20ca59a788c5aa1eb4d68fb7c'),
    (11, 'Polski',
     '355a8a4653c0ed776435fae53210eea15b4fac46220243bc4fad96d3a186d50b',
     '2da42143083cd1e4b81a25b4873b7ea31acba0cbd8202717c67b356a4ad83b7a',
     '4845a7100dc9f98449e59a1e2d9a554b19ecc13e6a56caad6bffa18384930aff'),
    (12, 'Español',
     '5e99ccba64ec7fac040edae233ab4ceaf0e770f878d46653e27a68e5587adf10',
     '3aabfefec0eed00d423b4090875c1c868fe979f81b8b78dbfdd2e1c3ee4f1ea9',
     'ff78fa9429ebf1606e6dd720f51391edac55d220746a0621aaa57983127071c2'),
    (13, 'Svensk',
     '93d184a68734ed7fbd95ff5961e7d112fcac44bf4809910cae9bb084e331e5fa',
     '67464b1e7c5d4dc954514f1070599607ba045c9ff355f51e07c434168dc2a66b',
     'e0f02959694a393beb9741d609cec88158cb25c3427053475f79a9964e1938bd'),
    (14, 'Türkçe',
     '182458cf0b501e08575a750260efed8c1d67143765ead9096785c827d49aa0aa',
     '2cf6362091235760a743cf113970f30943a3621d75a67cfce2b09afadfb13e08',
     '4792c3a52ea64dc0287c96efdb1db16babd6923b2b55d9b375696e5468956a66'),
    (15, 'Português',
     '3cef2cc83e5f0256138fde76eef6e09240f909f33c013b193b2b2489ea649511',
     '49a9aedfe63540c84964b1a7dc36dee992271ebd1ecdd3df3fd301681a44b570',
     'c17463d898deb6ced307a70c238a2d83843a92ca1b05bfac48f80acd776d084f'),
    (16, '简体中文',
     'c596a3c9c8d5e7d7f4eb7aae46ece334923c24f4dbb17de32822566f0cb7f298',
     '2c7e0f2dc19f8c7a819a170d51df94c9ebfd362334c60eb9086ad03fd6bb543a',
     '0359edde9532fba111b0f6a1bc8e22c133b433ee9d6e6fcde63ce2c0992b8e72'),
    (17, '繁體中文',
     'adc9a2b137f06a3e41e0f299d2ffe720ce19d271faf61e820da4ba4528415cd4',
     '70cefc1896f558e4dac8be695b04569db884c71548e4e829c1b055e2de4c38a8',
     '94994b3298c33923a3054825d431badb8bf553f7b3163eb6bf10815b49b18315'),
    (18, '日本語',
     '488fe9dc1021289c516efcb347e243981074d211990bb50ec851dd1a9cefa1fb',
     '7605a163ed92c67bf4668f9c5c9d8a43ec6a2ac4fa295005b94a7f10eec90006',
     'cd437b96feab3d6defee13a9205638304fc2f680ba9bc2a8a625f7dbd57cce31'),
    (19, '한국인',
     '55097ff02c28684a624a5816611e5b29288f518cea2c28e9fa547e8557c71dbe',
     '82d4b84782a5dc3627d5483049b9b6aff1f041ebf65102c0df1d2dd8d2c48ee4',
     '81c47386a708cdf189161dfdcd796fc58d5c992c4790d134663ed591d7701d7b'),
    (20, 'Русский',
     'e93dd671b0ffebfa87d685f1b47ea2dba99df7e85e6f9c7f8f537fc642bdc2cc',
     '4043f62012e6c1cb8e48fff74391ec60d065e93d2203663054a256bbfc7ac867',
     '2f71d948a001bfbdc6633186acf73c0dc52e1f548babaf1ecd97b5b1827808b8'),
    (21, 'عربي',
     '3f9f277c658664ab751d9e8d53a8789f69bf708d9198901818fe19f2c97f5c97',
     '3ee43fc30c47f790bb1919d215b0da0fdce4f5b0dab5088f3336f8518893bf55',
     '027ca70159ccc433e49c82f771d9beb5d26c9e7630474e78afd86b67959f2c3e'),
    (22, 'עברית',
     '8165103a2439a75b5f000453a9b4773c9755a4551c5b6b9edb61152febac5f9f',
     '4b773aa42b86fd00621374fd2b0f51a6b2acb20816652dda83de34eff21286f1',
     '19a7800ac4932c0f159e46aedefec88b87adfe3c7013bb8f8c39c7b1469e86c1'),
    (23, 'کوردی سۆرانی',
     'c087f4cc0d6b6c7b3e6d4d99a0b69584107873f721fb61e5ca7afad7c6190de8',
     'bfda9ea573b7b581b9af8b3e56b0dc47c311b71179bbaf7800e0b03ee25af2f3',
     'f5c610085093d7a5faa059506c76f2ab5c64cffdf365e9fa106fdfcaa48b5675'),
)


class RemainingMenuLanguageChecks:
    def setUp(self):
        self.handset = FactoryHandset(self, self.model, self.firmware_directory)
        self.addCleanup(self.handset.save_artifacts, "final")
        self.handset.boot()

    def keys(self, *keys):
        for key in keys:
            self.handset.press(key, settle_steps=1000000)

    def expect(self, screen, first=0, last=128):
        return self.handset.wait_screen(screen, first=first, last=last, max_steps=30000000)

    def check_languages(self, indices, *, scan_selector=False):
        self.keys("soft_left", *(["down"] * 6), "soft_left",
                  *(["down"] * (3 + (self.model == "9575"))), "soft_left")
        self.expect(ENGLISH_PARENT)
        if scan_selector:
            self.keys("soft_left")
            for index, screen in enumerate(SELECTOR_ROWS):
                if index:
                    self.keys("down")
                self.expect(screen)
            self.keys("down")  # The last of 24 selectable locales clamps at Sorani.
            self.expect(SELECTOR_ROWS[-1])
            self.keys(*(["up"] * 23))
            self.expect(SELECTOR_ROWS[0])
            self.keys("soft_right")
            self.expect(ENGLISH_PARENT)

        completed = []
        for index, name, parent, english_candidate, saved in LOCALES:
            if index not in indices:
                continue
            self.keys("soft_left")
            self.expect(SELECTOR_ROWS[0])
            self.keys(*(["down"] * index), "soft_left")
            self.expect(parent)
            self.handset.save_artifacts(f"locale-{index:02d}-localized-parent")
            self.keys("soft_right", "soft_left")
            self.expect(parent)  # Reopen the translated Language parent.
            self.keys("soft_left")
            # Reopening focuses English, with its radio unselected. It is a
            # distinct tentative choice while this locale remains saved.
            self.expect(english_candidate)
            self.keys("soft_right")
            self.expect(parent)
            self.keys("soft_left")
            self.expect(english_candidate)
            self.keys(*(["down"] * index))
            self.expect(saved)  # Both the highlight and saved radio are visible.
            self.handset.save_artifacts(f"locale-{index:02d}-saved-after-cancel")
            self.keys(*(["up"] * index))
            self.expect(english_candidate)
            self.keys("soft_left")
            self.expect(ENGLISH_PARENT)
            self.keys("soft_left")
            self.expect(SELECTOR_ROWS[0])  # English is saved again.
            self.keys("soft_right")
            self.expect(ENGLISH_PARENT)
            self.handset.save_artifacts(f"locale-{index:02d}-english-restored")
            completed.append((index, name))
        self.assertEqual([index for index, _ in completed],
                         [index for index in indices if index != 5])
        self.keys("red")
        state = self.expect(HOME_CAPTIONS, 113, 128)
        self.assertEqual(state["keys"], [])
        self.handset.assert_healthy(state)

    def test_latin_and_greek_menu_locales_save_readback_cancel_and_restore_english(self):
        self.check_languages(range(1, 16), scan_selector=True)

    def test_cjk_cyrillic_and_rtl_menu_locales_save_readback_cancel_and_restore_english(self):
        self.check_languages(range(16, 24))


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_FIRMWARE"),
                     "Set IRIDIUM_TEST_FIRMWARE for factory 9555 menu language E2E")
class Factory9555LanguagesE2ETests(RemainingMenuLanguageChecks, unittest.TestCase):
    model = "9555"
    firmware_directory = os.environ.get("IRIDIUM_TEST_FIRMWARE")


@unittest.skipUnless(os.environ.get("IRIDIUM_TEST_9575_FIRMWARE"),
                     "Set IRIDIUM_TEST_9575_FIRMWARE for factory 9575 menu language E2E")
class Factory9575LanguagesE2ETests(RemainingMenuLanguageChecks, unittest.TestCase):
    model = "9575"
    firmware_directory = os.environ.get("IRIDIUM_TEST_9575_FIRMWARE")


if __name__ == "__main__":
    unittest.main()
