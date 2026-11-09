# HomeAssistant

Home Assistant automation projects, reusable configuration, and installation notes.
This is a source repository, not a backup of a running Home Assistant installation.

## Projects

| Category | Project | Implementation |
| --- | --- | --- |
| EV charging | [Nissan Leaf Gen2 + Vevor smart charging](automations/leaf-smart-charging/README.md) | Native HA scripts, helpers, automations, templates, and dashboard |
| Climate | [AC controller](appDaemon/apps/ACController.py) | Existing AppDaemon app |
| Energy | [Energy calculations](appDaemon/apps/EnergyCalculations.py) | Existing AppDaemon app |
| Shared configuration | [AppDaemon registration](appDaemon/apps/apps.yaml), [energy and climate entities](config/configuration.yaml) | Existing configuration examples |

The existing AppDaemon and configuration paths are intentionally unchanged. New
native automation projects live under `automations/`, with their own documentation
and supporting files. The Leaf project does not depend on the AppDaemon apps.

## What Belongs in Git

Commit reusable source, model-specific device profiles, dashboard configuration,
small tests, installation instructions, and carefully cropped screenshots. Keep a
reviewable source definition as the authority, and generate installation files
locally. A Git commit records a configuration version; it does not deploy it.

Do not commit passwords, Tuya local keys or individual device IDs, Nissan account
data, HA tokens, `.storage`, databases, logs, VINs, location history, or full backups.
The [ignore rules](.gitignore) provide a guardrail, not a substitute for reviewing
the staged diff. Already-tracked secrets are not protected by adding an ignore rule.

Recommended workflow:

1. Back up the running HA configuration privately.
2. Change the relevant project's source and update its README when behavior changes.
3. Generate local installation files and run that project's checks.
4. Review the diff, including screenshots, for private information.
5. Commit and push the source. Deploy separately, with an explicit rollback plan.

Keep site-specific entity IDs and credentials local when adapting an example.
Never replace a complete live HA configuration with this repository's older
configuration example.

## License

See [LICENSE](LICENSE). Third-party integrations retain their own licenses and
installation/update processes; their complete source is not vendored here.
