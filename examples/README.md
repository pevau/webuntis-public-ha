# Dashboard examples

These examples use only built-in Home Assistant cards. No custom cards, card-mod or other frontend dependencies are required.

Before using an example, replace the placeholder entity IDs such as `sensor.school_class_daily_summary` with the entity IDs created in your Home Assistant instance.

- [Compact school overview](compact-school-overview.yaml) — a single compact card with today and a short preview of the next school day.
- [Today + next school day](today-and-next-school-day.yaml) — a detailed two-card view with both timetables.
- [Current school status](current-school-status.yaml) — a small status card for dashboards where only the current situation matters.


## Automation blueprints

- [Timetable change notifications](../blueprints/automation/webuntis_public/timetable-change-notifications.yaml) — choose which semantic timetable changes should send a notification and select the target mobile devices.
