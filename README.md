# Raspberry Pi Fluorescence Detection Interface

This repository contains a Flask-based control interface for running fluorescence detection experiments on a Raspberry Pi. It coordinates camera capture, LED control, heater PID control, fluorescence signal analysis, experiment state tracking, and a browser dashboard for live monitoring.

## Features

- Web dashboard for starting, stopping, and resetting assay runs
- Preset and saved assay protocols
- Raspberry Pi camera image capture with LED control
- MLX90614 temperature sensing and PWM heater control
- PID-based temperature regulation with safety cutoff
- Green fluorescence intensity analysis from configured chamber ROIs
- Live amplification curves and chamber status table
- JSON experiment snapshots and heater CSV logs

## Project Structure

```text
.
+-- app.py                       # Flask app factory and entry point
+-- config/
|   +-- analysis_config.json     # Fluorescence detection thresholds
|   +-- device_config.json       # Host, camera, GPIO, and heater settings
|   +-- protocols.json           # Built-in assay protocols
|   +-- ui_config.json           # UI defaults
+-- data/
|   +-- coordinates.json         # Chamber ROI coordinates
|   +-- saved_protocols.json     # User-saved protocols
+-- routes/                      # Flask API blueprints
+-- services/                    # Camera, heater, analysis, protocol, and state services
+-- static/                      # Frontend JavaScript and styles
+-- templates/                   # Dashboard HTML
```

## Hardware Requirements

This project is intended to run on a Raspberry Pi with:

- Raspberry Pi Camera compatible with `picamera2`
- GPIO-controlled LED
- GPIO-controlled heater using PWM
- MLX90614 infrared temperature sensor over I2C

The default GPIO and I2C settings are configured in `config/device_config.json`.

## Software Requirements

- Python 3.11 or newer recommended
- Raspberry Pi OS or another environment with Raspberry Pi camera and GPIO support
- I2C enabled for the MLX90614 sensor

Install Python dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Raspberry Pi OS, some camera/GPIO dependencies may also require system packages and enabled interfaces through `raspi-config`.

## Running

Start the Flask app:

```bash
python app.py
```

By default, the app binds to the host and port in `config/device_config.json`:

```json
{
  "host": "0.0.0.0",
  "port": 5000
}
```

Open the dashboard from another device on the same network:

```text
http://<raspberry-pi-ip>:5000
```

## Configuration

- `config/device_config.json`: camera LED GPIO, image/log paths, heater GPIO, PWM, PID, MLX90614 address, and safety cutoff.
- `config/analysis_config.json`: HSV green threshold, signal scaling, warmup, noise model, and chamber confirmation parameters.
- `config/protocols.json`: built-in assay protocols.
- `data/coordinates.json`: circular chamber ROI center points and radii.
- `data/saved_protocols.json`: custom protocols saved from the UI.

## Experiment Outputs

Runs are written under the paths configured in `config/device_config.json`:

- Images: `runs/images/<run_id>/`
- Experiment snapshot: `runs/logs/<run_id>.json`
- Heater log: `runs/logs/<run_id>_heater.csv`

These generated outputs are ignored by Git.

## Development Notes

The application imports Raspberry Pi-specific packages such as `picamera2`, `gpiozero`, `lgpio`, `board`, and `busio`. Because of that, the full experiment workflow is expected to run on Raspberry Pi hardware rather than a normal desktop machine.

For safer development, keep hardware-related configuration changes in `config/device_config.json` and review GPIO assignments before starting a run.
