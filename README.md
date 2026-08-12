# Alpha Daemon - Temporal Python Application

This repository contains a simple Temporal workflow application written in Python.

## Prerequisites

1. **Python 3.10+** (with virtual environment configured).
2. **Temporal CLI** (already installed on this machine).

## Setup

The dependencies are already installed in the `env` virtual environment. If you ever need to set it up again:

```bash
# Activate the virtual environment
source env/bin/activate

# Install dependencies
pip install temporalio
```

## Running the Application

### 1. Start the Local Temporal Server
In a separate terminal tab/window, run:
```bash
temporal server start-dev
```

### 2. Start the Temporal Worker
With the virtual environment activated, run the worker:
```bash
python src/alpha-daemon/worker.py
```

### 3. Run the Workflow
With the virtual environment activated, run the script to execute the workflow:
```bash
python src/alpha-daemon/run_workflow.py
```
