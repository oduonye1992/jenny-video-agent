# Jenny Video Agent

[![CI](https://github.com/oduonye1992/jenny-video-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/oduonye1992/jenny-video-agent/actions/workflows/ci.yml)

Production-minded Python workflow engine for AI-generated video, media orchestration, and creative automation.

Jenny turns a creative brief into validated production data, compiles it into a dependency-aware workflow, runs provider adapters, tracks cost and cached assets, and exposes local run progress through a FastAPI + React viewer.

**Relevant roles:** AI Engineer · Backend Engineer · Platform / Workflow Engineer

## What this demonstrates

- **Schema-first design:** creative plans, shot plans, prompts, and assets are represented as validated data.
- **Workflow orchestration:** a dependency graph coordinates character, image, video, audio, and assembly steps.
- **Provider abstraction:** external generation services sit behind focused adapters instead of being spread through the workflow.
- **Paid-API safety:** validation, health checks, cost estimates, and caching happen before expensive generation work.
- **Observability:** the optional viewer makes local workflow output and progress easy to inspect.
- **Reliable testing:** the Python suite covers schemas, compilation, adapters, and validation without requiring live provider calls.

## Core flow

```text
Brief → Creative plan → Shot plan → Prompts → Generation → Assembly
```

## Architecture

```text
workflow/
  schemas/       Validated creative and production models
  compiler/      Brief-to-shot-plan compilation
  dag/           Dependency-aware execution
  adapters/      Video, image, voice, music, storage, and FFmpeg integrations
  validators/    Prompt and production checks

viewer/
  backend/       FastAPI local API
  frontend/      React/Vite run viewer

tests/           Offline unit tests for the engine and adapters
```

The engine is provider-agnostic. You can bring your own brief, prompts, credentials, and output storage without depending on a particular creative brand.

## Integrations

Optional adapters include FAL for image and video generation, ElevenLabs for voice and music, Freepik for image upscaling, Supabase for public asset URLs, Google and Anthropic for analysis or review, and Airtable for batch workflows.

## Setup

### Requirements

- Python 3.11+
- FFmpeg for local media work
- Node.js 20+ and npm for the optional viewer
- API keys only for the providers you use

```bash
git clone https://github.com/oduonye1992/jenny-video-agent.git
cd jenny-video-agent

python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cp .env.example .env
# Add only the provider keys you need to .env
```

Run the test suite:

```bash
make test
```

To run the optional local viewer:

```bash
python -m pip install -r viewer/backend/requirements.txt
cd viewer/frontend
npm install
cd ../..
./viewer/start.sh
```

The viewer runs at `http://localhost:5173` and reads local run data from `outputs/`.

## Engineering notes

- Generated media and run output stay in ignored local directories.
- Provider credentials are loaded from environment variables and should never be committed.
- The workflow validates prompts and production specs before calling paid services.
- Provider behavior can change over time, so integrations are intentionally isolated behind adapters.

## Project status

Jenny is an experimental toolkit. The workflow engine, validation layers, adapter boundaries, and tests are the most reusable parts; provider APIs, model behavior, and the viewer may change as their services evolve.

## License

MIT. See [LICENSE](LICENSE).
