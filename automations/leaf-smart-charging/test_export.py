from copy import deepcopy
from ast import literal_eval
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
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

    def test_charger_delay_is_explicitly_requested_after_reconnect(self):
        profile = yaml.safe_load((FOLDER / 'tuya_local' / 'vevor_ev_b07_eu011b.yaml').read_text(encoding='utf-8'))
        delay = next(entity for entity in profile['entities'] if entity.get('name') == 'Delay')
        datapoint = delay['dps'][0]
        self.assertEqual(datapoint['id'], 28)
        self.assertTrue(datapoint['force'])
        self.assertEqual(datapoint['range'], {'min': 0, 'max': 12})
        self.assertNotIn('mapping', datapoint)

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

    def test_stopped_and_failed_plans_take_precedence_over_a_due_timestamp(self):
        template = self.definition["templates"]["next_start"]
        timestamp_branch = template.index("elif plan.get('a')")
        self.assertLess(template.index("plan.get('k', false)"), timestamp_branch)
        self.assertLess(template.index("decision.get('failed', false)"), timestamp_branch)
        self.assertIn("Stopped - resume night charging", template)
        self.assertIn("if already_charging else decision.reason", template)


class ScriptStopped(Exception):
    def __init__(self, response=None):
        self.response = response


class NativeFixture:
    def __init__(self, definition):
        self.definition = definition
        self.clock = datetime(2026, 11, 9, 20, 48, tzinfo=timezone(timedelta(hours=2)))
        self.values = {
            'input_text.leaf_control_generation': 'base',
            'input_text.leaf_night_plan': '{}',
            'input_select.leaf_charging_request': 'Automatic',
            'input_boolean.leaf_smart_charging': 'on',
            'binary_sensor.nissan_charge_problem': 'off',
            'number.nissan_charge_charge_current': '16',
            'sensor.leaf_battery_level': '54',
            'sensor.leaf_last_updated': self.clock.isoformat(),
            'sensor.nissan_charge_connection_state': 'Vehicle connected',
            'binary_sensor.leaf_plugged_in': 'on',
            'switch.nissan_charge': 'off',
            'number.nissan_charge_delay': '0',
            'select.nissan_charge_charging_mode': 'immediate',
            'sensor.nissan_charge_power': '0',
            'sensor.nissan_charge_status': 'available',
        }
        self.stamps = {entity: self.clock for entity in self.values}
        self.writes = []
        self.after_write = lambda: None
        self.after_delay = lambda: None
        fixture = self

        class States:
            def __call__(self, entity):
                return fixture.values.get(entity, 'unknown')

            def __getattr__(self, domain):
                class Domain:
                    def __getattr__(self, entity):
                        name = domain + '.' + entity
                        return SimpleNamespace(last_changed=fixture.stamps.get(name, fixture.clock))
                return Domain()

        self.env = NativeEnvironment(undefined=StrictUndefined)
        self.env.globals.update(
            states=States(), now=lambda: self.clock,
            is_state=lambda entity, value: self.values.get(entity) == value,
            is_number=lambda value: str(value).replace('.', '', 1).replace('-', '', 1).isdigit(),
            has_value=lambda entity: self.values.get(entity, 'unknown') not in ['unknown', 'unavailable'],
            as_timestamp=self.timestamp, as_datetime=lambda value: datetime.fromtimestamp(value, timezone.utc),
            as_local=lambda value: value.astimezone(timezone(timedelta(hours=2))),
            timedelta=timedelta, state_attr=lambda entity, attribute: [],
        )
        self.env.filters.update(
            to_json=lambda value: json.dumps(value, separators=(',', ':')),
            from_json=lambda value, fallback=None: json.loads(value) if value else fallback,
            timestamp_custom=lambda value, pattern: datetime.fromtimestamp(
                value, timezone(timedelta(hours=2))).strftime(pattern),
        )

    def timestamp(self, value, default=None):
        try:
            return (value if isinstance(value, datetime) else datetime.fromisoformat(value)).timestamp()
        except (ValueError, TypeError):
            return default

    def render(self, value, variables):
        if isinstance(value, str):
            rendered = self.env.from_string(value).render(**variables)
            if isinstance(rendered, str):
                rendered = rendered.strip()
                try:
                    return literal_eval(rendered)
                except (ValueError, SyntaxError):
                    pass
            return rendered
        if isinstance(value, dict):
            return {key: self.render(item, variables) for key, item in value.items()}
        return value

    def run(self, script, **variables):
        try:
            self.steps(self.definition['scripts'][script]['sequence'], variables)
        except ScriptStopped as stopped:
            return stopped.response

    def steps(self, steps, variables):
        for step in steps:
            if 'variables' in step:
                for key, value in step['variables'].items():
                    variables[key] = self.render(value, variables)
            elif 'if' in step:
                branch = 'then' if self.render(step['if'], variables) else 'else'
                self.steps(step.get(branch, []), variables)
            elif 'choose' in step:
                for branch in step['choose']:
                    if self.render(branch['conditions'], variables):
                        self.steps(branch['sequence'], variables)
                        break
                else:
                    self.steps(step.get('default', []), variables)
            elif 'condition' in step:
                if not self.render(step['value_template'], variables):
                    raise ScriptStopped()
            elif 'repeat' in step:
                for iteration in range(step['repeat']['count']):
                    variables['repeat'] = {'index': iteration + 1}
                    self.steps(step['repeat']['sequence'], variables)
            elif 'delay' in step:
                self.clock += timedelta(seconds=step['delay']['seconds'])
                self.after_delay()
            elif 'wait_template' in step:
                completed = bool(self.render(step['wait_template'], variables))
                if not completed:
                    hours, minutes, seconds = map(int, step['timeout'].split(':'))
                    self.clock += timedelta(hours=hours, minutes=minutes, seconds=seconds)
                    self.after_delay()
                    completed = bool(self.render(step['wait_template'], variables))
                variables['wait'] = {'completed': completed}
            elif 'stop' in step:
                raise ScriptStopped(variables.get(step.get('response_variable')))
            elif 'action' in step:
                action = step['action']
                data = self.render(step.get('data', {}), variables)
                if action.startswith('script.'):
                    result = self.run(action.split('.', 1)[1], **data)
                    if 'response_variable' in step:
                        variables[step['response_variable']] = result
                elif action == 'homeassistant.save_persistent_states':
                    pass
                elif action == 'persistent_notification.create':
                    self.writes.append((action, data))
                else:
                    entity = step['target']['entity_id']
                    value = data.get('value', data.get('option', 'on' if action.endswith('turn_on') else 'off'))
                    if entity.startswith(('switch.', 'select.', 'number.')):
                        self.writes.append((entity, value))
                        self.values[entity] = str(value)
                        self.after_write()
                    else:
                        self.values[entity] = str(value)
            else:
                raise AssertionError('Unimplemented fixture action: ' + str(step))


class ChargingBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.definition = yaml.safe_load(SOURCE.read_text(encoding='utf-8'))
        self.fixture = NativeFixture(self.definition)
        now = self.fixture.clock.timestamp()
        self.plan = dict(s=now + 4320, e=now + 36720, a=now + 21600, z=now + 33300,
                         t=80, c=True, f=True, p=80, m='continuous', v=3,
                         r='Automatic', h=6, x=True)
        self.context = dict(plan=self.plan, now_ts=now, enabled=True, connected=True,
                            fault_clear=True, actuator_available=True, soc_valid=True,
                            fresh=True, soc=54, target=80, request='Automatic',
                            timer_armed=False, already_charging=False, rate=8,
                            price_valid=True, price_eur=0.9, limit=0.5)

    def decision(self, **overrides):
        context = dict(self.context, **overrides)
        return json.loads(self.fixture.render(self.definition['templates']['decision'], context))

    def test_lost_timer_recovers_within_original_window_even_at_high_price(self):
        result = self.decision()
        self.assertTrue(result['recover'])
        self.assertTrue(result['arm'])
        self.assertLess(result['start'], self.plan['e'])
        self.assertGreaterEqual(result['start'], self.plan['s'])
        self.assertEqual(result['delay_hours'], 6)

    def test_recovery_is_bounded_and_intentional_stops_never_retry(self):
        for change in [dict(k=True), dict(n=2), dict(e=self.context['now_ts'] - 1)]:
            with self.subTest(change=change):
                result = self.decision(plan=dict(self.plan, **change))
                self.assertFalse(result['arm'] or result['charge'])
        self.assertTrue(self.decision(plan=dict(self.plan, n=2))['failed'])
        pending = self.decision(plan=dict(self.plan, u=self.context['now_ts'] - 10))
        self.assertTrue(pending['recover'])
        self.assertFalse(pending['arm'] or pending['charge'])

    def test_each_safety_gate_prevents_recovery(self):
        for override in [dict(enabled=False), dict(connected=False), dict(fault_clear=False),
                         dict(actuator_available=False), dict(soc_valid=False), dict(fresh=False),
                         dict(soc=80)]:
            with self.subTest(override=override):
                result = self.decision(**override)
                self.assertFalse(result['charge'] or result['arm'] or result['recover'])

    def test_due_but_not_running_does_not_display_charging(self):
        context = dict(self.context, now_ts=self.plan['a'] + 60)
        context['decision'] = self.decision(now_ts=context['now_ts'], timer_armed=True)
        result = self.fixture.render(self.definition['templates']['next_start'], context)
        self.assertIn('waiting for charger startup', result)
        context['plan'] = dict(self.plan, k=True)
        result = self.fixture.render(self.definition['templates']['next_start'], context)
        self.assertIn('Stopped', result)

    def test_late_missing_power_uses_recovery_not_permanent_startup_grace(self):
        result = self.decision(now_ts=self.plan['a'] + 301)
        self.assertTrue(result['recover'] and result['charge'])
        self.assertEqual(result['delay_hours'], 0)

    def test_old_generation_and_aba_request_cannot_write_after_intent_changes(self):
        programs = ['Immediate to 100%', 'Automatic', 'Immediate to 80%',
                    'Immediate to 100%', 'Automatic']
        for generation_change in [True, False]:
            with self.subTest(generation_change=generation_change):
                fixture = NativeFixture(self.definition)
                def change_intents():
                    for index, program in enumerate(programs):
                        fixture.values['input_select.leaf_charging_request'] = program
                        fixture.stamps['input_select.leaf_charging_request'] = fixture.clock + timedelta(microseconds=index + 1)
                        if generation_change:
                            fixture.values['input_text.leaf_control_generation'] = 'g' + str(index)
                fixture.after_write = change_intents
                result = fixture.run('leaf_charger_write', operation='arm', hours=6)
                self.assertTrue(result['superseded'])
                self.assertEqual(fixture.writes, [('switch.nissan_charge', 'off')])

    def test_unstable_acknowledgement_is_not_committed(self):
        initial = self.fixture.clock
        def delayed_bad_feedback():
            if (self.fixture.clock - initial).total_seconds() >= 6:
                self.fixture.values['number.nissan_charge_delay'] = '0'
        self.fixture.after_delay = delayed_bad_feedback
        result = self.fixture.run('leaf_charger_write', operation='arm', hours=6)
        self.assertFalse(result['ok'])
        self.assertEqual(self.fixture.values['switch.nissan_charge'], 'off')
        self.assertEqual(self.fixture.values['select.nissan_charge_charging_mode'], 'immediate')
        self.assertEqual(self.fixture.values['number.nissan_charge_delay'], '0')

    def test_stable_acknowledgement_requires_ten_seconds(self):
        initial = self.fixture.clock
        result = self.fixture.run('leaf_charger_write', operation='arm', hours=6)
        self.assertTrue(result['ok'])
        self.assertEqual((self.fixture.clock - initial).total_seconds(), 10)
        self.assertEqual(result['start'], initial.timestamp() + 21600)

    def test_safety_changes_during_arming_abort_before_further_commands(self):
        for entity, value in [('binary_sensor.nissan_charge_problem', 'on'),
                              ('input_boolean.leaf_smart_charging', 'off'),
                              ('sensor.leaf_battery_level', '80'),
                              ('sensor.leaf_last_updated', '2026-11-09T00:00:00+02:00')]:
            with self.subTest(entity=entity):
                fixture = NativeFixture(self.definition)
                fixture.after_write = lambda: fixture.values.update({entity: value})
                result = fixture.run('leaf_charger_write', operation='arm', hours=6)
                self.assertTrue(result['superseded'])
                self.assertEqual(len(fixture.writes), 1)

    def test_running_manual_charge_requires_no_actuator_commands(self):
        self.fixture.values.update({'input_select.leaf_charging_request': 'Immediate to 100%',
                                    'switch.nissan_charge': 'on', 'sensor.nissan_charge_power': '10.25',
                                    'sensor.nissan_charge_status': 'charging'})
        result = self.fixture.run('leaf_smart_charge_controller')
        self.assertTrue(result['charge'])
        self.assertFalse(self.fixture.writes)

    def test_idle_maintenance_delay_is_not_cancelled_by_controller(self):
        self.fixture.stamps['sensor.nissan_charge_connection_state'] = self.fixture.clock - timedelta(seconds=30)
        self.fixture.values.update({'sensor.nissan_charge_connection_state': 'standby',
                                    'binary_sensor.leaf_plugged_in': 'off',
                                    'number.nissan_charge_delay': '12',
                                    'select.nissan_charge_charging_mode': 'delayed_charge'})
        result = self.fixture.run('leaf_smart_charge_controller')
        self.assertFalse(result['charge'] or result['arm'])
        self.assertFalse(self.fixture.writes)

    def test_recovered_and_failed_plans_fit_persistent_helper(self):
        for attempts in [0, 2]:
            with self.subTest(attempts=attempts):
                fixture = NativeFixture(self.definition)
                fixture.values['input_text.leaf_control_generation'] = 'g999999'
                fixture.values['input_text.leaf_night_plan'] = json.dumps(
                    dict(self.plan, g='g999999', n=attempts))
                fixture.run('leaf_smart_charge_controller')
                self.assertLessEqual(len(fixture.values['input_text.leaf_night_plan']), 255)
                fixture.values['binary_sensor.nissan_charge_problem'] = 'on'
                fixture.run('leaf_smart_charge_controller')
                self.assertLessEqual(len(fixture.values['input_text.leaf_night_plan']), 255)
        helper = self.definition['helpers']['input_text']['leaf_control_generation']
        self.assertNotIn('initial', helper)

    def test_manual_safety_stop_does_not_restart_when_fault_clears(self):
        self.fixture.values.update({'input_select.leaf_charging_request': 'Immediate to 100%',
                                    'switch.nissan_charge': 'on', 'sensor.nissan_charge_power': '10.25',
                                    'sensor.nissan_charge_status': 'charging'})
        self.fixture.run('leaf_smart_charge_controller')
        self.fixture.values['binary_sensor.nissan_charge_problem'] = 'on'
        self.fixture.run('leaf_smart_charge_controller')
        self.fixture.values.update({'binary_sensor.nissan_charge_problem': 'off',
                                    'sensor.nissan_charge_power': '0',
                                    'sensor.nissan_charge_status': 'available'})
        result = self.fixture.run('leaf_smart_charge_controller')
        self.assertFalse(result['charge'] or result['arm'] or result['recover'])
        self.assertEqual(self.fixture.values['switch.nissan_charge'], 'off')

    def test_retry_cooldown_clears_unexpected_output_without_latching_stop(self):
        self.fixture.values['input_text.leaf_night_plan'] = json.dumps(
            dict(self.plan, u=self.context['now_ts']))
        self.fixture.values.update({'switch.nissan_charge': 'on',
                                    'sensor.nissan_charge_power': '10.25'})
        result = self.fixture.run('leaf_smart_charge_controller')
        self.assertTrue(result['recover'])
        self.assertFalse(result['charge'] or result['arm'])
        self.assertEqual(self.fixture.values['switch.nissan_charge'], 'off')
        self.assertFalse(json.loads(self.fixture.values['input_text.leaf_night_plan']).get('k', False))

    def test_busy_writer_missing_response_is_a_recoverable_failure(self):
        self.fixture.values['input_text.leaf_night_plan'] = json.dumps(self.plan)
        original_run = self.fixture.run
        def busy_writer(script, **variables):
            if script == 'leaf_charger_write':
                return None
            return original_run(script, **variables)
        self.fixture.run = busy_writer
        self.fixture.run('leaf_smart_charge_controller')
        pending = json.loads(self.fixture.values['input_text.leaf_night_plan'])
        self.assertTrue(pending['l'])
        self.assertFalse(pending.get('k', False))
        self.assertFalse(self.fixture.writes)

    def test_only_transaction_script_writes_charger(self):
        def check(value, owner):
            if isinstance(value, dict):
                if value.get('action') in ['switch.turn_on', 'switch.turn_off', 'number.set_value', 'select.select_option']:
                    self.assertEqual(owner, 'leaf_charger_write')
                for item in value.values():
                    check(item, owner)
            elif isinstance(value, list):
                for item in value:
                    check(item, owner)
        for section in ['scripts', 'automations']:
            for name, body in self.definition[section].items():
                check(body, name)
        self.assertEqual(self.definition['scripts']['leaf_smart_charge_controller']['mode'], 'single')
        self.assertEqual(self.definition['automations']['leaf_smart_charge_control']['mode'], 'restart')


if __name__ == "__main__":
    unittest.main()