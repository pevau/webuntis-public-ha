# WebUntis Public Timetable for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/github/v/release/pevau/webuntis-public-ha)](https://github.com/pevau/webuntis-public-ha/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/pevau/webuntis-public-ha/total)](https://tooomm.github.io/github-release-stats/?username=pevau&repository=webuntis-public-ha)
![HACS Installations](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20installations&suffix=%20installs&cacheSeconds=15600&url=https%3A%2F%2Fanalytics.home-assistant.io%2Fcustom_integrations.json&query=%24.webuntis_public.total)
[![Latest Release](https://img.shields.io/github/release-date/pevau/webuntis-public-ha?style=flat&label=Latest%20Release)](https://github.com/pevau/webuntis-public-ha/releases)
[![Open Issues](https://img.shields.io/github/issues/pevau/webuntis-public-ha?style=flat&label=Open%20Issues)](https://github.com/pevau/webuntis-public-ha/issues)

Custom integration for Home Assistant that imports public WebUntis timetables without a WebUntis login.

## Features

- School search and public class selection during setup
- Multiple classes per school
- Calendar entity per class
- Subject, room and teacher details
- Cancelled lessons, substitutions and timetable changes
- Duplicate lesson merging while keeping real parallel subjects separate
- Sensors for current/next lesson, school start/end, remaining lessons and remaining teaching time
- Binary sensors for school-free days, active lessons and timetable changes
- School-day progress and teaching-time progress sensors
- Central `DataUpdateCoordinator`
- Persistent cache with fallback for temporary WebUntis outages
- Diagnostics and configurable calendar display
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

## Languages

The integration currently includes:

- German (`de`)
- English (`en`)

Setup, options, entity names, data-status values and calendar details such as cancellations, substitutions and room changes follow the Home Assistant language.

## Updating

When installed through HACS, updates can be installed directly from HACS. After updating the integration, restart Home Assistant.

Every release contains a short changelog which is also used as the GitHub/HACS release note. The full history is available in [CHANGELOG.md](CHANGELOG.md).

## Current version

`0.7.3`

## Notes

This is an independent community integration and is not affiliated with Untis GmbH.

## Support

<a href="https://buymeacoffee.com/pevau">
  <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="50">
</a>
