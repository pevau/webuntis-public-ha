# Changelog

All notable changes to **WebUntis Public Timetable** are documented here.

## [0.8.9] - 2026-09-26

### Added

- Added configurable Live Activity notification icons using the native Home Assistant icon picker, defaulting to `mdi:school`.
- Added an optional notification icon color setting.

### Changed

- Set Live Activity progress bars to use the increasing direction.

### Tests

- Added regression coverage for Live Activity icon, icon color, and progress-bar configuration.

## [0.8.8] - 2026-09-26

### Changed

- Switched the School Day Live Activity blueprint to direct `notify.mobile_app_*` notification actions, matching the Companion App path that reliably starts Live Activities.
- Added support for sending the same Live Activity to multiple mobile notification actions.
- Expanded the diagnostic Live Activity button to simulate a complete school-day flow: before school, lesson, break, lesson, and school end.
- Improved the blueprint input guidance with explicit YAML examples for one or multiple mobile notification actions.

### Tests

- Added automated regression coverage for the Live Activity blueprint notification input and diagnostic school-day sequence.

## [0.8.7] - 2026-09-26

### Changed

- Improved the School Day Live Activity blueprint with native Home Assistant Companion App device selection, avoiding manual `notify.mobile_app_*` service names.

### Fixed

- Fixed thread safety for minute-based updates of time-sensitive sensors by keeping state writes on the Home Assistant event loop.
- Fixed the School Day Live Activity notification payload so Companion App-specific notification data is sent through a supported mobile app device action.
- Fixed malformed Live Activity blueprint action structures discovered during Home Assistant validation.

### Tests

- Added regression coverage for the Live Activity diagnostic event and the event-loop-safe time callback.

## [0.8.6] - 2026-09-26

### Added

- Added one-click Home Assistant import buttons for both bundled automation blueprints.
- Added a disabled-by-default diagnostic button per class to test the School Day Live Activity without waiting for an active school day.
- Added class-scoped Live Activity test events so installations with multiple classes only trigger the matching automation.

### Fixed

- Fixed the notification target selectors in both bundled blueprints for current Home Assistant blueprint validation.

## [0.8.5] - 2026-09-25

### Added

- Added semantic timetable events for lesson cancellations, substitutions, room changes, time changes, and changed school start/end times.
- Added a configurable timetable-change notification blueprint with selectable event types and mobile notification targets.
- Added a school-day Live Activity blueprint for mobile devices with current lesson information and countdown updates.

### Changed

- Hardened semantic change detection so persistent WebUntis previous-value metadata does not trigger duplicate notifications.
- Improved Live Activity entity selection by using the matching current-lesson sensor instead of inferring it across all integration entities.
- Improved CI performance with dependency and virtual-environment caching and updated GitHub Actions runtimes.

### Tests

- Added regression coverage for semantic timetable events, timezone-aware event payloads, and persistent WebUntis change metadata.


## [0.8.1] - 2026-09-25

### Added

- Added an option to exclude configured subjects from timetable data.
- Added localized German and English labels for the subject-exclusion option.

### Changed

- Summary timetable attributes now consistently use the English technical field name `subject`.
- Updated the dashboard example to use the normalized `subject` field.

### Tests

- Added regression coverage for excluded-subject defaults, coordinator filtering and summary schedule attributes.

## [0.8.0] - 2026-09-24

### Added

- Added a native Home Assistant reconfigure flow for changing the public WebUntis endpoint and selected classes without removing the config entry.
- Added focused regression tests for reconfiguration, unique-ID collisions, translation-key consistency, calendar lifecycle behavior and additional edge cases.
- Added contributor guidance for a test-first development workflow.

### Changed

- Standardized entity state-attribute translation keys on stable English technical names while keeping German and English display labels localized.
- Raised the CI coverage gate to 95%; the 0.8.0 codebase reaches 95.05% coverage with 220 passing tests.
- Aligned test and validation workflows with Python 3.14 / Home Assistant 2026.9.
- Declared the integration explicitly as a multi-device `hub` integration.
- Expanded the README with entity/data-model documentation, update and cache behavior, known limitations and troubleshooting guidance.
- Release creation is now gated by the complete test suite and the 95% coverage requirement.

## [0.7.15] - 2026-09-24

### Fixed

- Hardened public timetable link parsing, including links without a URL scheme and invalid class IDs.
- Improved validation of configured class IDs and setup robustness for multiple classes.
- Kept coordinator first refreshes sequential to avoid concurrent startup request bursts.
- Hardened stale-cache handling and timezone-aware cache age comparisons.
- Improved cleanup of obsolete entities during setup.
- Fixed the standalone test workflow configuration.

## [0.7.14] - 2026-09-23

### Added

- Added a compact slot-by-slot `stundenplan` attribute to the daily summary sensor.
- Each active lesson slot includes start/end time, subject, teacher, room and timetable-change status, matching the next-school-day summary structure.

## [0.7.13] - 2026-09-23

### Changed

- Reduced the normal visible entity set to seven focused sensors plus the timetable calendar.
- Removed all eight standalone binary sensors, the separate school-start/end-today sensors and the separate teaching-progress sensor.
- Moved later/earlier school times, cancelled first/last lesson and teaching-progress details into the daily summary attributes.
- Added a “no school tomorrow” attribute to the next-school-day summary.
- Obsolete entity-registry entries from previous versions are now removed automatically during setup, so users no longer need to delete retired entities manually.
- Diagnostic sensors remain available separately.

## [0.7.12] - 2026-09-23

### Changed

- Reduced the sensor surface per class from 22 to 13 focused sensors.
- Removed redundant standalone sensors for tomorrow start/end, next-school-day start/end, lesson count, remaining lessons, remaining teaching time, today's changes and today's cancellations.
- The removed information remains available through the central school-status, daily-summary, next-school-day and next-school-day-summary sensors.
- Kept the teaching-progress sensor as a distinct break-excluding progress value and retained the three diagnostic sensors.

## [0.7.11] - 2026-09-23

### Added

- Added a compact summary sensor for the next actual school day after today.
- The sensor skips days without active lessons and reuses the configured coordinator look-ahead cache without additional WebUntis requests.
- Its numeric state is the number of active lesson slots; attributes include date, days until school, start/end time, subjects, teachers, rooms, changes, cancellations and a compact slot-by-slot timetable.
- Cancelled-only days are skipped, while cancellations and other timetable changes on the selected school day remain visible in the summary attributes.

## [0.7.10] - 2026-09-23

### Added

- Added a central school-status sensor for each configured class.
- The sensor exposes stable automation-friendly states: `school_free`, `before_school`, `lesson`, `break` and `after_school`.
- Attributes include current and next subject, current lesson end, next lesson start, school start/end and remaining lessons.
- Cancelled lessons do not count as active teaching; cancelled-only days are reported as `school_free`.
- The time-dependent status updates locally every minute without additional WebUntis requests.

## [0.7.9] - 2026-09-23

### Fixed

- Teacher names now prefer the WebUntis `longName` value instead of the school-configurable `displayName`, so full names are shown when the public timetable exposes them.
- The existing display name and short name remain fallbacks for schools that do not publish a long teacher name.

## [0.7.8] - 2026-09-23

### Added

- Added a Home Assistant event entity that fires only when the semantic timetable actually changes between two WebUntis fetches.
- Change detection ignores technical duplicate-count differences and compares lesson time, status, subject, teacher, room and WebUntis change text.
- Only lessons that have not already ended are considered, preventing irrelevant changes to historical timetable data from creating events.
- Event data includes the affected week, counts and compact lists of added and removed lessons, making the entity suitable for Home Assistant automations and notifications.

### Fixed

- The manual refresh button now bypasses the coordinator cache TTL once and performs a real WebUntis refresh immediately.

## [0.7.7] - 2026-09-23

### Added

- Added a compact daily summary sensor for each configured class.
- The sensor state is the number of active lesson slots today and remains automation-friendly.
- Attributes include school start/end, subjects, timetable changes, cancellations, school-day progress, remaining lessons, current lesson and next lesson.
- The time-dependent attributes update locally every minute without additional WebUntis requests.

## [0.7.6] - 2026-09-23

### Added

- Added a Home Assistant button entity for each configured class to refresh the timetable immediately.
- The button uses the existing DataUpdateCoordinator refresh path, including the integration's normal retry, cache and error handling.
- Added German and English names for the new button entity.

## [0.7.5] - 2026-09-23

### Added

- Added a sensor with the number and details of cancelled lessons today.
- Added binary sensors for a later school start and an earlier school end caused by cancelled timetable entries at the beginning or end of the day.
- Added binary sensors for a cancelled first and last lesson.
- Later-start and earlier-end entities expose scheduled time, actual time, minute difference and affected subjects as attributes.

### Note

- The public WebUntis data exposes cancelled timetable entries but does not provide a separate original timestamp for every possible time shift. Therefore the new start/end indicators compare active lessons with cancelled timetable entries at the edges of the day and do not guess undocumented original times.

## [0.7.4] - 2026-09-23

### Added

- Added a date sensor for the next school day after today.
- Added start and end timestamp sensors for the next school day.
- The next-school-day lookup skips days without active lessons and uses the configured look-ahead range, so it reuses the coordinator cache without extra WebUntis requests.
- The next-school-day sensor includes school start, school end, lesson count and subjects as attributes.

## [0.7.3] - 2026-09-23

### Fixed

- Restored the integration brand icon files that were present in the ZIP builds but missing from the GitHub/HACS package.
- Home Assistant 2026.3+ can now use the local integration icon in supported integration views.

### Note

- The HACS update entity currently still requests its picture from the Home Assistant Brands CDN. Therefore the HACS update dialog can continue to show a placeholder until HACS switches that view to the local Brands API.

## [0.7.2] - 2026-09-23

### Changed

- Restored the full README with status badges, HACS install button and support button.
- Added a persistent `CHANGELOG.md`.
- GitHub releases now use the matching changelog section as their release notes, so HACS can show concise update information directly.
- Validation now checks that every released version has a changelog entry.

## [0.7.1] - 2026-09-23

### Added

- Complete German and English translations for setup and options.
- Localized entity names, data-status values and calendar details.
- Translation keys for Home Assistant entities.

### Changed

- Calendar labels such as cancellation, substitution and room changes now follow the Home Assistant language.
- Custom integration translations now use `translations/en.json` and `translations/de.json`.

## [0.7.0] - 2026-09-23

### Added

- School-day progress sensor.
- Teaching-time progress sensor excluding breaks.
- Minute-based local updates for time-sensitive entities without extra WebUntis requests.

## [0.6.0]

### Added

- Current lesson.
- School start and school end for tomorrow.
- Remaining lessons and remaining teaching time.
- Binary sensors for no school today/tomorrow and lesson in progress.

## [0.5.0]

### Added

- Data-source and cache diagnostics.
- Last successful update sensor.
- Privacy-conscious Home Assistant diagnostics export.

## [0.4.0]

### Added

- Multiple classes per school.
- Separate Home Assistant devices and caches per class.

## [0.3.2]

### Fixed

- Added the required `anonymous-school` header to direct WebUntis requests.

## [0.3.0]

### Changed

- Migrated timetable fetching to Home Assistant aiohttp and `DataUpdateCoordinator`.
- Added persistent cache with stale-cache fallback.

## [0.2.8]

### Changed

- Improved German option labels and help text.
- Added local brand assets for Home Assistant.

## [0.2.7]

### Added

- Configurable calendar title format and display options.
- Configurable look-ahead period for the next lesson.

## [0.2.6]

### Added

- Next lesson, school start/end, lessons today and timetable-change sensors.

## [0.2.5]

### Fixed

- Technical duplicate entries are merged while real parallel subjects remain separate.

## [0.2.4]

### Added

- Retry handling, in-memory week cache and stale-cache fallback for temporary WebUntis errors.

## [0.2.3]

### Fixed

- Subject, teacher and room extraction based on WebUntis element types.
- Cancelled lessons remain available instead of being discarded.

## [0.2.2]

### Fixed

- Home Assistant calendar `event` support.

## [0.2.1]

### Fixed

- Updated WebUntis school-search endpoint and request format.
