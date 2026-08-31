# Jenny Video Agent

Jenny is a Python workflow engine for planning and producing short-form video. It turns a creative brief into structured shot plans, image prompts, video prompts, generated assets, and an assembled result.

The public release contains the reusable engine, model adapters, validation tools, tests, and a small local viewer. Brand-specific prompts, private production notes, and generated media are kept out of this repository.

## What it does

- Models creative and production plans as validated JSON.
- Builds a dependency graph for character, image, video, audio, and assembly steps.
- Supports adapters for video, image, voice, music, storage, and local FFmpeg work.
- Estimates cost and caches completed assets.
- Validates prompts and production specs before paid generation.
- Provides a FastAPI + React viewer for local run output.

The basic flow is:

```text
Brief → Creative plan → Shot plan → Prompts → Generation → Assembly
```

## Project layout

```text
workflow/       Core schemas, compiler, DAG engine, validators, and adapters
scripts/        Validation and workflow utilities
batch/          Optional Airtable batch helpers
tests/          Unit tests for schemas, compilation, adapters, and validation
viewer/         Optional FastAPI backend and React/Vite frontend
```

Generated files belong in `outputs/` and are ignored by Git. The engine does not require a particular creative brand; provide your own brief, prompts, and configuration.

## Requirements

- Python 3.11+
- FFmpeg for local media work
- Node.js 20+ and npm for the optional viewer
- API keys only for the providers you use

## Setup

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

To try the local viewer, install its frontend dependencies first:

```bash
python -m pip install -r viewer/backend/requirements.txt
cd viewer/frontend
npm install
cd ../..
./viewer/start.sh
```

The viewer runs at `http://localhost:5173` and reads local run data from `outputs/`.

## API keys

Copy `.env.example` to `.env`. Never commit `.env` or generated media. The available integrations are listed in the example file:

- FAL for image and video generation
- ElevenLabs for voice and music
- Freepik for image upscaling
- Supabase for public asset URLs
- Google and Anthropic for optional analysis or review
- Airtable for optional batch workflows

Each adapter checks its own configuration when it runs, so you can use the engine without configuring every provider.

## Safety and cost

Some adapters call paid external APIs. Review prompts and estimated cost before running a generation pipeline. Keep provider keys in environment variables, use test accounts where possible, and do not upload private reference media to a public host.

## Status

This is an experimental toolkit. The workflow engine and validation layers are the stable parts of the project. Provider APIs, model behavior, and the viewer may change as those services change.

## License

MIT. See [LICENSE](LICENSE).
