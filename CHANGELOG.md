# Changelog

All notable changes to **WebUntis Public Timetable** are documented here.

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
