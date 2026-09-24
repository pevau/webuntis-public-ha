# WebUntis Public Timetable for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/github/v/release/pevau/webuntis-public-ha)](https://github.com/pevau/webuntis-public-ha/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/pevau/webuntis-public-ha/total)](https://tooomm.github.io/github-release-stats/?username=pevau&repository=webuntis-public-ha)
[![Latest Release](https://img.shields.io/github/release-date/pevau/webuntis-public-ha?style=flat&label=Latest%20Release)](https://github.com/pevau/webuntis-public-ha/releases)
[![Open Issues](https://img.shields.io/github/issues/pevau/webuntis-public-ha?style=flat&label=Open%20Issues)](https://github.com/pevau/webuntis-public-ha/issues)

Custom integration for Home Assistant that imports public WebUntis timetables without a WebUntis login.

## Features

- School search and public class selection during setup
- Multiple classes per school
- Calendar entity per class
- Subject, room and teacher details
- Cancelled lessons, substitutions and semantic timetable-change detection
- Duplicate lesson merging while keeping real parallel subjects separate
- Compact sensor set for current/next lesson, central school status and the next school day
- Daily summary attributes for cancellations, timetable changes, later starts, earlier finishes and teaching progress
- One school-day progress sensor plus compact daily/next-school-day summary sensors
- Central `DataUpdateCoordinator`
- Persistent cache with fallback for temporary WebUntis outages
- Timetable-change event entity, true manual refresh button, diagnostics and configurable calendar display
- German and English translations for setup, options, entities and calendar details
- Local Home Assistant brand icon for custom-integration views (Home Assistant 2026.3+)

## Installation with HACS

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pevau&repository=webuntis-public-ha)

Or add the repository manually:

1. In HACS, open **Integrations**.
2. Add this repository as a **Custom repository** of type **Integration**:
   `https://github.com/pevau/webuntis-public-ha`
3. Install **WebUntis Public Timetable**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration** and search for **WebUntis Public Timetable**.

## Manual installation

Copy `custom_components/webuntis_public` to `/config/custom_components/webuntis_public` and restart Home Assistant.

## Setup

The integration can be configured by:

- searching for a school,
- pasting a public WebUntis link, or
- entering the WebUntis server manually.

After selecting the school, choose one or more public classes. No WebUntis account is required as long as the school has enabled public timetable access.

## Entities and data model

Each configured class is represented as its own Home Assistant device. The integration provides:

- one timetable calendar,
- sensors for current lesson, next lesson, school status, next school day, daily summary, next-school-day summary and school-day progress,
- diagnostic sensors for data source, last successful update and cached weeks,
- a manual refresh button,
- a timetable-change event entity.

Diagnostic/noisy entities can be disabled by default where appropriate. Stable English attribute keys are used internally so automations remain independent of the Home Assistant display language.

## Data updates and caching

The integration uses a central Home Assistant `DataUpdateCoordinator` with a 10-minute polling interval. Time-sensitive sensor values such as the current lesson or school-day progress are calculated locally and do not trigger extra WebUntis requests.

Fetched timetable weeks are cached persistently. If WebUntis is temporarily unavailable, a recent cached week can be used as a fallback. Old cache entries are discarded automatically, and manual refresh bypasses the normal cache TTL once.

## Known limitations

- A school must expose its timetable publicly. Schools without public timetable access cannot be used without authentication.
- The integration depends on the public WebUntis endpoints and their currently observed response formats; undocumented upstream API changes may require an integration update.
- Public timetable data differs between schools. Some schools may not publish full teacher names, room information or substitution details.
- Changes are detected semantically from the public timetable data. WebUntis does not expose a dedicated change-feed for this integration.

## Troubleshooting

If setup cannot find classes, first verify in a normal browser that the school's public WebUntis timetable works without logging in. For manual setup, verify the WebUntis server and technical school name.

If data temporarily stops updating, check the diagnostic entities and download Home Assistant diagnostics for the config entry. The integration reports whether data currently comes from WebUntis, the normal cache or stale-cache fallback.

After updating through HACS, restart Home Assistant before troubleshooting an old behavior. If an issue persists, include the integration version, Home Assistant version and diagnostics when opening a GitHub issue.

## Languages

The integration currently includes:

- German (`de`)
- English (`en`)

Setup, options, entity names, data-status values and calendar details such as cancellations, substitutions and room changes follow the Home Assistant language.

## Dashboard examples

Ready-to-use Home Assistant dashboard examples are available in the [examples](examples/) directory.

## Updating

When installed through HACS, updates can be installed directly from HACS. After updating the integration, restart Home Assistant.

Every release contains a short changelog which is also used as the GitHub/HACS release note. The full history is available in [CHANGELOG.md](CHANGELOG.md).

## Notes

This is an independent community integration and is not affiliated with Untis GmbH.

## Support

<a href="https://buymeacoffee.com/pevau">
  <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="50">
</a>
