# Development Guide

This guide will help you set up your development environment and contribute to the EnergyTariff integration.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Development Setup](#development-setup)
  - [Option 1: Using VS Code Dev Container (Recommended)](#option-1-using-vs-code-dev-container-recommended)
  - [Option 2: Local Development Environment](#option-2-local-development-environment)
- [Running Tests](#running-tests)
- [Code Quality](#code-quality)
- [Development Workflow](#development-workflow)
- [Debugging](#debugging)

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.12** or higher
- **Git** for version control
- **Visual Studio Code** (recommended for dev container support)
- **Docker** (if using the dev container)

## Development Setup

### Option 1: Using VS Code Dev Container (Recommended)

The easiest way to start developing is using the included dev container configuration.

1. **Install Prerequisites:**
   - Install [Visual Studio Code](https://code.visualstudio.com/)
   - Install the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
   - Install [Docker Desktop](https://www.docker.com/products/docker-desktop)

2. **Open in Container:**
   ```bash
   # Clone the repository
   git clone https://github.com/epaulsen/energytariff.git
   cd energytariff
   
   # Open in VS Code
   code .
   ```

3. **Reopen in Container:**
   - When prompted, click "Reopen in Container"
   - Or use Command Palette (F1): `Dev Containers: Reopen in Container`
   - The container will automatically install all dependencies via the `scripts/setup` script

4. **Access Home Assistant:**
   - The dev container will forward port 8123
   - Access Home Assistant at http://localhost:8123
   - Configuration is located in the `config/` directory

### Option 2: Local Development Environment

If you prefer not to use the dev container:

1. **Clone the repository:**
   ```bash
   git clone https://github.com/epaulsen/energytariff.git
   cd energytariff
   ```

2. **Create a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   # Install runtime dependencies
   pip install -r requirements.txt
   
   # Install development dependencies
   pip install -r requirements_dev.txt
   
   # Install test dependencies
   pip install -r requirements_test.txt
   ```

4. **Run Home Assistant for development:**
   ```bash
   # Use the development script
   ./scripts/develop
   ```
   
   This will:
   - Create a `config/` directory if it doesn't exist
   - Set up PYTHONPATH to include custom_components
   - Start Home Assistant in debug mode on http://localhost:8123

## Running Tests

This project uses pytest for testing. Tests are located in the `tests/` directory.

### Run All Tests

```bash
# Activate your virtual environment first
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Run tests with coverage report
pytest --cov=custom_components.energytariff --cov-report=term-missing
```

### Run Specific Tests

```bash
# Run only sensor tests
pytest tests/test_sensor.py

# Run a specific test function
pytest tests/test_sensor.py::test_estimated_energy_sensor_initialization

# Run tests matching a pattern
pytest -k "energy_sensor"
```

### Test Options

```bash
# Show the slowest 10 tests
pytest --durations=10

# Stop on first failure
pytest -x

# Show local variables in tracebacks
pytest -l

# Run tests in parallel (requires pytest-xdist)
pytest -n auto
```

### Current Test Status

The project currently has 22 test cases in `tests/test_sensor.py`:
- **8 tests pass** and validate core sensor functionality
- **14 tests** require full Home Assistant event system integration

All passing tests cover:
- Sensor initialization and configuration
- State calculation logic
- Response to coordinator updates
- Units of measurement
- Grid level sensors

## Code Quality

### Linting and Formatting

This project uses Ruff for both linting and formatting.

```bash
# Format and lint code automatically
./scripts/lint

# Or manually:
ruff format .
ruff check . --fix
```

### Pre-commit Hooks

To automatically run checks before each commit:

```bash
# Install pre-commit
pip install pre-commit

# Set up the git hooks
pre-commit install

# Run checks on all files manually
pre-commit run --all-files
```

### Code Style Guidelines

- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guidelines
- Use type hints where appropriate
- Write descriptive docstrings for classes and functions
- Keep line length to 88 characters (Black's default)
- Use meaningful variable and function names

## Development Workflow

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes:**
   - Write code following the style guidelines
   - Add or update tests as needed
   - Update documentation if necessary

3. **Test your changes:**
   ```bash
   # Run tests
   pytest
   
   # Run linting
   ./scripts/lint
   ```

4. **Commit your changes:**
   ```bash
   git add .
   git commit -m "Description of your changes"
   ```

5. **Push and create a pull request:**
   ```bash
   git push origin feature/your-feature-name
   ```
   
   Then create a pull request on GitHub.

## Debugging

### Using VS Code Debugger

A launch configuration is included in `.vscode/launch.json`.

1. Open VS Code
2. Set breakpoints in your code
3. Press F5 or go to Run > Start Debugging
4. Home Assistant will start in debug mode

### Debug Logging

Enable debug logging in Home Assistant by adding to `config/configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.energytariff: debug
```

### Troubleshooting

**Issue: Tests fail with import errors**
- Solution: Make sure you've installed test dependencies: `pip install -r requirements_test.txt`

**Issue: Home Assistant doesn't see the integration**
- Solution: Check that PYTHONPATH includes the custom_components directory
- Or: Restart Home Assistant after code changes

**Issue: Dev container fails to build**
- Solution: Make sure Docker is running and you have sufficient disk space
- Try: Rebuild the container using Command Palette > "Dev Containers: Rebuild Container"

## Additional Resources

- [Home Assistant Developer Documentation](https://developers.home-assistant.io/)
- [Integration Blueprint Template](https://github.com/custom-components/integration_blueprint)
- [Contributing Guidelines](CONTRIBUTING.md)
- [Project README](README.md)

## Getting Help

If you encounter issues or have questions:

1. Check existing [GitHub Issues](https://github.com/epaulsen/energytariff/issues)
2. Create a new issue with detailed information about your problem
3. Include steps to reproduce, expected behavior, and actual behavior

## License

By contributing to this project, you agree that your contributions will be licensed under the MIT License.
