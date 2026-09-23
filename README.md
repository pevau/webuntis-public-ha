# WebUntis Public Timetable for Home Assistant

Custom Home Assistant integration for public WebUntis timetables without a WebUntis login.

## Features

- School search and public class selection during setup
- Multiple classes per school
- Calendar entity per class
- Subject, room and teacher details
- Cancelled lessons, substitutions and timetable changes
- Duplicate lesson merging while keeping real parallel subjects separate
- Sensors for current/next lesson, school start/end, remaining lessons and remaining teaching time
- School-day progress and teaching-time progress sensors
- Binary sensors for school-free days, active lessons and timetable changes
- Central `DataUpdateCoordinator`
- Persistent cache with fallback for temporary WebUntis outages
- Diagnostics and configurable calendar display
- German and English UI translations, including entity names and calendar details

## Installation with HACS

1. In HACS, open **Integrations**.
2. Add this repository as a **Custom repository** of type **Integration**:
   `https://github.com/pevau/webuntis-public-ha`
3. Install **WebUntis Public Timetable**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration** and search for **WebUntis Public Timetable**.

## Manual installation

Copy `custom_components/webuntis_public` to `/config/custom_components/webuntis_public` and restart Home Assistant.

## Setup

The integration can be configured by searching for a school, pasting a public WebUntis link, or entering the WebUntis server manually. After selecting the school, choose one or more public classes. No WebUntis account is required as long as the school has enabled public timetable access.

## Updating

When installed through HACS, updates can be installed directly from HACS. Restart Home Assistant after updating the integration.

## Languages

The integration currently ships with complete German (`de`) and English (`en`) translations for setup, options and entities. Calendar details such as cancellation, substitution and room-change labels follow the Home Assistant language as well.

## Current version

`0.7.1`

## Notes

This is an independent community integration and is not affiliated with Untis GmbH.
