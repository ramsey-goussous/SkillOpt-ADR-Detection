"""ADR environment adapter for SkillOpt (mirrors the SearchQA adapter).

Rollout is ADR-specific (run_batch). Reflection reuses SkillOpt's generic
minibatch reflector, so skill edits are produced the same way as every built-in
benchmark.
"""
from __future__ import annotations
import os
from skillopt.datasets.base import BatchSpec
from skillopt.envs.base import EnvAdapter
from skillopt.envs.adr.dataloader import ADRDataLoader
from skillopt.envs.adr.rollout import run_batch
from skillopt.gradient.reflect import run_minibatch_reflect


class ADRAdapter(EnvAdapter):
    def __init__(self, split_dir="", data_path="", split_mode="split_dir",
                 split_ratio="2:1:7", split_seed=42, split_output_dir="",
                 max_turns=1, exec_timeout=120, workers=8, analyst_workers=16,
                 failure_only=False, minibatch_size=8, edit_budget=4,
                 seed=42, limit=0):
        self.max_turns = max_turns
        self.exec_timeout = self._env_int("ADR_EXEC_TIMEOUT", exec_timeout, minimum=30)
        self.workers = workers
        self.analyst_workers = analyst_workers
        self.failure_only = failure_only
        self.minibatch_size = minibatch_size
        self.edit_budget = edit_budget
        self.dataloader = ADRDataLoader(
            split_dir=split_dir, data_path=data_path, split_mode=split_mode,
            split_ratio=split_ratio, split_seed=split_seed,
            split_output_dir=split_output_dir, seed=seed, limit=limit,
        )

    @staticmethod
    def _env_int(name: str, default: int, minimum: int = 1) -> int:
        raw = os.environ.get(name)
        if not raw:
            return default
        try:
            return max(minimum, int(raw))
        except ValueError:
            return default

    def setup(self, cfg: dict) -> None:
        super().setup(cfg)
        self.dataloader.setup(cfg)

    def get_dataloader(self):
        return self.dataloader

    def build_env_from_batch(self, batch: BatchSpec, **kwargs):
        return list(batch.payload or [])

    def build_train_env(self, batch_size: int, seed: int, **kwargs):
        return self.build_env_from_batch(
            self.dataloader.build_train_batch(batch_size=batch_size, seed=seed, **kwargs), **kwargs)

    def build_eval_env(self, env_num: int, split: str, seed: int, **kwargs):
        return self.build_env_from_batch(
            self.dataloader.build_eval_batch(env_num=env_num, split=split, seed=seed, **kwargs), **kwargs)

    def rollout(self, env_manager, skill_content: str, out_dir: str, **kwargs) -> list[dict]:
        return run_batch(
            items=env_manager, out_root=out_dir, skill_content=skill_content,
            max_turns=self.max_turns, exec_timeout=self.exec_timeout, workers=self.workers,
            diagnostic_mode=kwargs.get("diagnostic_mode", False),
            diagnostic_instruction=kwargs.get("diagnostic_instruction", ""),
            diagnostic_trace_context_by_id=kwargs.get("diagnostic_trace_context_by_id"),
            task_timeout=self.exec_timeout,
        )

    def reflect(self, results, skill_content, out_dir, **kwargs):
        return run_minibatch_reflect(
            results=results, skill_content=skill_content,
            prediction_dir=kwargs.get("prediction_dir", os.path.join(out_dir, "predictions")),
            patches_dir=kwargs.get("patches_dir", os.path.join(out_dir, "patches")),
            workers=self.analyst_workers, failure_only=self.failure_only,
            minibatch_size=self.minibatch_size, edit_budget=self.edit_budget,
            random_seed=kwargs.get("random_seed"),
            error_system=self.get_error_minibatch_prompt(),
            success_system=self.get_success_minibatch_prompt(),
            step_buffer_context=kwargs.get("step_buffer_context", ""),
            meta_skill_context=kwargs.get("meta_skill_context", ""),
            update_mode=getattr(self, "_cfg", {}).get("skill_update_mode", "patch"),
        )

    def get_task_types(self) -> list[str]:
        return ["adr"]
