import unittest

from src.fishing import (
    FISHING_PATCH_SPECS,
    _SPLICE_PATCH_SPECS,
    FishConfig,
    fish_matches,
)


class TestFishMatches(unittest.TestCase):
    def _fish(self, **over):
        base = dict(is_chest=False, school="Storm", rank=3, template_id=123, size=7.0)
        base.update(over)
        return base

    def test_default_accepts_plain_fish_rejects_chest(self):
        cfg = FishConfig()
        self.assertTrue(fish_matches(cfg, **self._fish()))
        self.assertFalse(fish_matches(cfg, **self._fish(is_chest=True)))

    def test_chest_target(self):
        cfg = FishConfig(chest=True)
        self.assertTrue(fish_matches(cfg, **self._fish(is_chest=True)))
        self.assertFalse(fish_matches(cfg, **self._fish(is_chest=False)))

    def test_school_filter(self):
        cfg = FishConfig(school="Storm")
        self.assertTrue(fish_matches(cfg, **self._fish(school="Storm")))
        self.assertFalse(fish_matches(cfg, **self._fish(school="Fire")))

    def test_any_school_ignores_school(self):
        cfg = FishConfig(school="Any")
        self.assertTrue(fish_matches(cfg, **self._fish(school="Fire")))

    def test_rank_filter(self):
        cfg = FishConfig(rank=3)
        self.assertTrue(fish_matches(cfg, **self._fish(rank=3)))
        self.assertFalse(fish_matches(cfg, **self._fish(rank=5)))
        # rank 0 means "any"
        self.assertTrue(fish_matches(FishConfig(rank=0), **self._fish(rank=9)))

    def test_template_id_filter(self):
        cfg = FishConfig(template_id=123)
        self.assertTrue(fish_matches(cfg, **self._fish(template_id=123)))
        self.assertFalse(fish_matches(cfg, **self._fish(template_id=999)))

    def test_size_bounds(self):
        cfg = FishConfig(size_min=5.0, size_max=10.0)
        self.assertTrue(fish_matches(cfg, **self._fish(size=7.0)))
        self.assertFalse(fish_matches(cfg, **self._fish(size=3.0)))
        self.assertFalse(fish_matches(cfg, **self._fish(size=12.0)))


class TestFishConfig(unittest.TestCase):
    def test_round_trip(self):
        cfg = FishConfig(chest=True, school="Fire", rank=4, size_max=50.0)
        self.assertEqual(FishConfig.from_dict(cfg.to_dict()), cfg)

    def test_from_none_is_default(self):
        self.assertEqual(FishConfig.from_dict(None), FishConfig())

    def test_from_dict_ignores_unknown_keys(self):
        cfg = FishConfig.from_dict({"chest": True, "bogus": 99})
        self.assertTrue(cfg.chest)
        self.assertEqual(cfg.school, "Any")


class TestPatchTableIntegrity(unittest.TestCase):
    def test_direct_specs_well_formed(self):
        names = set()
        for spec in FISHING_PATCH_SPECS:
            self.assertIn("name", spec)
            self.assertNotIn(spec["name"], names, f"duplicate {spec['name']}")
            names.add(spec["name"])
            self.assertIsInstance(spec["pattern"], bytes)
            self.assertGreater(len(spec["pattern"]), 0)
            self.assertIsInstance(spec["write"], bytes)
            self.assertGreater(len(spec["write"]), 0)
            self.assertGreaterEqual(spec.get("offset", 0), 0)

    def test_splice_specs_preserve_length(self):
        # an in-place patch must rebuild exactly ``read`` bytes from the original
        for spec in _SPLICE_PATCH_SPECS:
            self.assertIsInstance(spec["pattern"], bytes)
            self.assertGreater(len(spec["pattern"]), 0)
            n = spec["read"]
            self.assertGreater(n, 0)
            out = spec["build"](b"\x00" * n)
            self.assertIsInstance(out, bytes)
            self.assertEqual(len(out), n, f"{spec['name']} changed patch length")


if __name__ == "__main__":
    unittest.main()
