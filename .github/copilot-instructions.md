# GitHub Copilot Instructions for EnergyTariff

This repository contains a custom integration for HomeAssistant. All code is written in Python.

## Getting Started

When starting work on this repository, ensure that the repository is in a good state by running all tests:

```bash
pytest tests/test_sensor.py -v
```

## Testing Requirements

Before submitting a PR that has changed code files, all tests must pass. Testing is done with pytest.

To run tests:
```bash
pytest tests/test_sensor.py -v
```

## HomeAssistant Resources

Copilot has been granted access to the HomeAssistant developer documentation and is encouraged to use it:
- HomeAssistant Developer Documentation: https://developers.home-assistant.io/
- HomeAssistant Core Repository: https://github.com/home-assistant/core

Use these resources to look up documentation and reference implementations when working on HomeAssistant integration code.

## Code Structure

This is a HomeAssistant custom integration that provides energy monitoring sensors. Key components:
- `custom_components/energytariff/` - Main integration code
- `tests/` - Test files
- Testing uses pytest with HomeAssistant testing utilities

## Best Practices

- Follow HomeAssistant integration patterns and conventions
- Maintain test coverage for all code changes
- Ensure all tests pass before submitting changes
- Reference HomeAssistant documentation for integration best practices
