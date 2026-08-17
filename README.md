<div align="center">

# UpTime.ai

**Automated AI on-call engineer for incident investigation and source code patching.**

![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)

</div>

## Highlights

- Autonomous Multi-Agent Workflow: Utilizes specialized agents for investigation, repository context retrieval, and patching via the uAgents framework.
- Sentry Integration: Automatically ingests and categorizes error signals, providing full error summaries and stack trace details.
- Automated Patch Generation: Produces AI-driven code recommendations, including precise diffs to resolve backend logic errors and configuration issues.
- GitHub Contextual Awareness: Dynamically fetches source code and repository metadata to inform investigation and ensure recommendations are context-aware.
- Real-Time Observability Dashboard: Features a React-based interface for monitoring service state, health percentages, and queued remediation changes.

## Overview

UpTime.ai is an automated observability and incident response system designed to function as an AI on-call engineer. It monitors backend health by ingesting Sentry error events and orchestrating a multi-agent workflow to investigate root causes. By integrating directly with GitHub to retrieve repository context, the system generates actionable code recommendations and patches to resolve observed failures, reducing the manual effort required for incident triage.

## Usage

Users run the system by starting the FastAPI backend and a suite of background agents defined in the project. Once operational, the system listens for incoming Sentry events via webhooks. Developers interact with the web dashboard to monitor system health, inspect high-severity incidents, and review or apply recommended code changes surfaced by the patch agent.

## Architecture

The project follows a distributed architecture comprising a FastAPI backend, a React frontend, and a multi-agent orchestration layer. The backend handles data persistence via SQLModel and Redis, while the agents communicate asynchronously to move incidents through stages of investigation, repository lookup, and patch generation. The system integrates with external services including Sentry for error tracking and GitHub for source code management.

## Tech Stack

| Category | Technologies |
| --- | --- |
| **Languages** | Python, TypeScript, JavaScript |

## Project Structure

```text
UpTime.ai/
├── backend/
│   └── app/
├── frontend/
│   ├── public/
│   └── src/
└── README.md  # Project documentation
```
