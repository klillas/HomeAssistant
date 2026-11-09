"""Export the versioned Leaf definition as native Home Assistant YAML."""

import argparse
from copy import deepcopy
from pathlib import Path

import yaml


class StandaloneDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def represent_string(dumper, value):
    return dumper.represent_scalar(
        "tag:yaml.org,2002:str", value, style="|" if "\n" in value else None
    )


StandaloneDumper.add_representer(str, represent_string)


def build_exports(definition):
    if definition.get("version") != 1:
        raise ValueError("Expected Leaf definition version 1")
    required = (
        "helpers", "scripts", "automations", "program_indicators",
        "program_status", "dashboard_cards", "dashboard_charger_card",
        "dashboard_next_start_row",
    )
    for key in required:
        if key not in definition:
            raise ValueError(f"Missing definition section: {key}")
    helpers = deepcopy(definition["helpers"])
    supported = {"input_boolean", "input_number", "input_select", "input_text", "timer"}
    if not set(helpers).issubset(supported):
        raise ValueError("Unsupported helper domain")

    indicators = []
    for indicator in definition["program_indicators"]:
        indicators.append({
            "name": indicator["name"],
            "unique_id": indicator["entity_id"].split(".", 1)[1],
            "device_class": "running",
            "state": indicator["state"],
        })
    status = definition["program_status"]
    templates = [{
        "binary_sensor": indicators,
        "sensor": [{
            "name": status["name"],
            "unique_id": status["entity_id"].split(".", 1)[1],
            "icon": "mdi:calendar-clock",
            "state": status["state"],
        }],
    }]
    scripts = deepcopy(definition["scripts"])
    automations = deepcopy(list(definition["automations"].values()))
    package = {
        **helpers,
        "script": scripts,
        "automation": automations,
        "template": templates,
    }
    dashboard = {
        "type": "vertical-stack",
        "cards": [
            deepcopy(definition["dashboard_charger_card"]),
            *deepcopy(definition["dashboard_cards"]),
        ],
    }
    return {
        "package.yaml": package,
        "scripts.yaml": scripts,
        "automations.yaml": automations,
        "helpers.yaml": helpers,
        "program-templates.yaml": templates,
        "dashboard.yaml": dashboard,
        "next-start-row.yaml": deepcopy(definition["dashboard_next_start_row"]),
    }


def export_definition(source, output):
    source = Path(source).resolve()
    output = Path(output).resolve()
    if output == source.parent:
        raise ValueError("Use a separate output directory, such as generated/")
    definition = yaml.safe_load(source.read_text(encoding="utf-8"))
    exports = build_exports(definition)
    output.mkdir(parents=True, exist_ok=True)
    for name, value in exports.items():
        (output / name).write_text(
            yaml.dump(value, Dumper=StandaloneDumper, sort_keys=False, width=100),
            encoding="utf-8", newline="\n",
        )
    return list(exports)


def main():
    folder = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--definition", type=Path, default=folder / "leaf-smart-charging.yaml")
    parser.add_argument("--output", type=Path, default=folder / "generated")
    args = parser.parse_args()
    for name in export_definition(args.definition, args.output):
        print(args.output / name)


if __name__ == "__main__":
    main()