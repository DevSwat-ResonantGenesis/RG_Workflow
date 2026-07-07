# RG Workflow

> **Part of the [ResonantGenesis](https://resonant.dev-swat.com) platform** — Workflow engine for defining and executing multi-step automation pipelines.

[![Status: Production](https://img.shields.io/badge/Status-Production-brightgreen.svg)]()
[![Port: 8000](https://img.shields.io/badge/Port-8000-orange.svg)]()
[![Database: PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-336791.svg)]()
[![License: RG Source Available](https://img.shields.io/badge/License-RG%20Source%20Available-blue.svg)](LICENSE.txt)

Workflow engine for defining, scheduling, and executing multi-step automation pipelines. Supports workflow definitions, step-by-step execution, event tracking, and run history.

## Features

- **Workflow Definitions** — Define reusable multi-step workflows
- **Workflow Runs** — Execute workflows with input parameters
- **Step Results** — Track individual step outcomes
- **Workflow Events** — Event-driven execution and logging

## Quick Start

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/workflow"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Deployment Status

- **Extracted from**: `genesis2026_production_backend/workflow_service/`
- **Server path**: `/home/deploy/RG_Workflow`
- **Docker service**: `workflow_service`

---
**Organization**: [DevSwat-ResonantGenesis](https://github.com/DevSwat-ResonantGenesis) | **Platform**: [resonant.dev-swat.com](https://resonant.dev-swat.com)
