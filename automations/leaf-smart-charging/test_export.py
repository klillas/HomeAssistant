from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml

from export import build_exports, export_definition


FOLDER = Path(__file__).resolve().parent
SOURCE = FOLDER / "leaf-smart-charging.yaml"


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.definition = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
        self.exports = build_exports(self.definition)

    def test_native_logic_is_preserved(self):
        package = self.exports["package.yaml"]
        self.assertEqual(package["script"], self.definition["scripts"])
        self.assertEqual(package["automation"], list(self.definition["automations"].values()))
        for domain, helpers in self.definition["helpers"].items():
            self.assertEqual(package[domain], helpers)

    def test_template_helpers_preserve_selected_program_states(self):
        templates = self.exports["package.yaml"]["template"][0]
        indicators = templates["binary_sensor"]
        self.assertEqual(len(indicators), 4)
        for source, exported in zip(self.definition["program_indicators"], indicators):
            self.assertEqual(exported["state"], source["state"])
            self.assertEqual(exported["unique_id"], source["entity_id"].split(".")[1])
            self.assertEqual(exported["device_class"], "running")
        self.assertEqual(templates["sensor"][0]["state"], self.definition["program_status"]["state"])

    def test_dashboard_commands_use_persistent_state_and_existing_scripts(self):
        commands = self.definition["dashboard_cards"][1]["cards"]
        self.assertEqual(len(commands), 6)
        expected = [indicator["entity_id"] for indicator in self.definition["program_indicators"]]
        self.assertEqual([card["entity"] for card in commands[:4]], expected)
        for card in commands:
            service = card["tap_action"]["perform_action"]
            if service.startswith("script."):
                self.assertIn(service.split(".", 1)[1], self.exports["scripts.yaml"])
        self.assertTrue(all(card["state_color"] for card in commands[:5]))
        self.assertEqual(commands[0]["tap_action"]["perform_action"], "script.leaf_resume_automatic_charging")
        self.assertEqual(commands[4]["entity"], "climate.leaf_climate")

    def test_dashboard_includes_charger_and_conditional_next_start(self):
        card = self.exports["dashboard.yaml"]["cards"][0]
        self.assertEqual(card, self.definition["dashboard_charger_card"])
        self.assertEqual(card["entities"][-1], self.exports["next-start-row.yaml"])
        self.assertEqual(card["entities"][-1]["type"], "conditional")

    def test_each_export_is_independently_loadable(self):
        with TemporaryDirectory() as output:
            names = export_definition(SOURCE, output)
            self.assertEqual(set(names), set(self.exports))
            for name in names:
                loaded = yaml.safe_load((Path(output) / name).read_text(encoding="utf-8"))
                self.assertEqual(loaded, self.exports[name], name)

    def test_export_does_not_mutate_source(self):
        original = deepcopy(self.definition)
        build_exports(self.definition)
        self.assertEqual(original, self.definition)
        with self.assertRaises(ValueError):
            export_definition(SOURCE, SOURCE.parent)

    def test_unknown_versions_and_missing_sections_are_rejected(self):
        self.definition["version"] = 2
        with self.assertRaises(ValueError):
            build_exports(self.definition)
        self.definition["version"] = 1
        del self.definition["scripts"]
        with self.assertRaises(ValueError):
            build_exports(self.definition)


if __name__ == "__main__":
    unittest.main()