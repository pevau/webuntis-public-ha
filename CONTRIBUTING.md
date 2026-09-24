# Contributing

## Test-first workflow

For every behavior change or bug fix:

1. Add or adjust a focused test that demonstrates the expected behavior.
2. Confirm that the new test fails for the reason the change is meant to address.
3. Implement the smallest production-code change that makes the test pass.
4. Run the complete test suite locally before committing:

   ```bash
   python -m pip install -r requirements_test.txt
   python -m pytest -q --cov=custom_components.webuntis_public --cov-report=term-missing
   ```

5. Keep or improve overall coverage. CI currently enforces a minimum of 75%.

Pure documentation, translation-only, metadata, and CI changes do not require a new behavioral test.

## Test scope

Prefer focused unit tests for parsing and transformation logic. Use flow/coordinator tests for Home Assistant lifecycle behavior and regression fixtures for real-world WebUntis payload shapes. External WebUntis calls must be mocked or represented by fixtures so the test suite remains deterministic and does not depend on a live school instance.
