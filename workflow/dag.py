"""DAG builder and scheduler for workflow execution.

A DAG is a dict of step_id -> Step. Each Step declares its dependencies.
The scheduler resolves which steps can run in parallel at any point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from workflow.adapters.base import Status


@dataclass
class Step:
    """A single step in the execution DAG."""
    step_id: str
    adapter_name: str
    config: dict
    depends_on: list[str] = field(default_factory=list)
    status: Status = Status.PENDING
    job_id: str | None = None
    output: str | None = None
    error: str | None = None
    duration_s: float = 0.0
    retries: int = 0
    cache_key: str = ""
    cache_hit: bool = False


class DAG:
    """Directed acyclic graph of execution steps."""

    def __init__(self):
        self.steps: dict[str, Step] = {}

    def add_step(
        self,
        step_id: str,
        adapter_name: str,
        config: dict,
        depends_on: list[str] | None = None,
    ) -> Step:
        """Add a step to the DAG."""
        if depends_on:
            for dep in depends_on:
                if dep not in self.steps:
                    raise ValueError(f"Dependency '{dep}' not found for step '{step_id}'")
        step = Step(
            step_id=step_id,
            adapter_name=adapter_name,
            config=config,
            depends_on=depends_on or [],
        )
        self.steps[step_id] = step
        return step

    def get_ready_steps(self) -> list[Step]:
        """Return steps whose dependencies are all completed and that are still pending."""
        ready = []
        for step in self.steps.values():
            if step.status != Status.PENDING:
                continue
            deps_met = all(
                self.steps[dep].status == Status.COMPLETED
                for dep in step.depends_on
            )
            if deps_met:
                ready.append(step)
        return ready

    def is_complete(self) -> bool:
        """True if all steps are completed."""
        return all(s.status == Status.COMPLETED for s in self.steps.values())

    def has_failed(self) -> bool:
        """True if any step has permanently failed."""
        return any(s.status == Status.FAILED for s in self.steps.values())

    def get_step(self, step_id: str) -> Step:
        """Get a step by ID."""
        return self.steps[step_id]

    def to_json(self, metadata: dict | None = None) -> dict:
        """Serialize the DAG to a pipeline JSON dict."""
        pipeline = {
            "pipeline_version": 1,
            "nodes": [
                {
                    "id": step.step_id,
                    "adapter": step.adapter_name,
                    "config": step.config,
                    "depends_on": step.depends_on,
                }
                for step in self.steps.values()
            ],
        }
        if metadata:
            pipeline.update(metadata)
        return pipeline

    @classmethod
    def from_json(cls, data: dict) -> "DAG":
        """Deserialize a pipeline JSON dict into a DAG.

        Uses two-pass construction: first add all steps, then validate deps.
        This allows nodes to appear in any order in the JSON.
        """
        dag = cls()
        for node in data.get("nodes", []):
            step = Step(
                step_id=node["id"],
                adapter_name=node["adapter"],
                config=dict(node["config"]),
                depends_on=list(node.get("depends_on", [])),
            )
            dag.steps[step.step_id] = step
        # Validate all dependencies exist
        for step in dag.steps.values():
            for dep in step.depends_on:
                if dep not in dag.steps:
                    raise ValueError(
                        f"Dependency '{dep}' not found for step '{step.step_id}'"
                    )
        return dag

    def summary(self) -> dict:
        """Return a summary dict of step statuses."""
        return {
            step_id: {
                "status": step.status.value,
                "adapter": step.adapter_name,
                "output": step.output,
                "error": step.error,
                "duration_s": step.duration_s,
                "retries": step.retries,
            }
            for step_id, step in self.steps.items()
        }
