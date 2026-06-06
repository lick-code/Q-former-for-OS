import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import learned_baselines
from scripts import run_learned_baselines


class LearnedBaselinesTest(unittest.TestCase):

  def test_kleio_lite_eviction_uses_lowest_predicted_hotness(self):
    policy = learned_baselines.LearnedBaselinePolicy({
        "policy": "kleio_lite",
        "feature_names": ["rank_norm"],
        "weights": [1.0],
        "candidate_count": 3,
        "history_length": 4,
    })

    victim = policy.choose_victim(
        dram_pages=[4, 3, 2, 1],
        history=[],
        access_index=10,
        dram_insert_time={1: 0, 2: 1, 3: 2, 4: 3},
        dirty_pages=set(),
        access_frequency={},
        last_access_time={})

    self.assertEqual(1, victim)

  def test_patterns_lite_uses_page_pattern_group_weights(self):
    policy = learned_baselines.LearnedBaselinePolicy({
        "policy": "patterns_lite",
        "feature_names": ["bias"],
        "cluster_weights": [[2.0], [0.1]],
        "clusters": {
            "centroids": [[1.0, 0.0], [0.0, 1.0]],
            "page_to_cluster": {"10": 0, "20": 1},
            "default_cluster": 0,
        },
        "candidate_count": 2,
        "history_length": 4,
    })

    victim = policy.choose_victim(
        dram_pages=[20, 10],
        history=[],
        access_index=10,
        dram_insert_time={10: 0, 20: 1},
        dirty_pages=set(),
        access_frequency={10: 5, 20: 1},
        last_access_time={10: 8, 20: 9})

    self.assertEqual(20, victim)

  def test_runner_builds_train_and_eval_commands_for_ml_baseline(self):
    config = run_learned_baselines.WORKLOADS["canneal"]
    model_path = run_learned_baselines.model_path(
        "canneal", "kleio_lite", "outputs/models")
    result_path = run_learned_baselines.result_json_path(
        "canneal", "kleio_lite", "outputs/results/ml_baselines")

    train_command = run_learned_baselines.build_train_command(
        python_bin="python3",
        workload_key="canneal",
        policy="kleio_lite",
        model_root="outputs/models")
    eval_command = run_learned_baselines.build_eval_command(
        python_bin="python3",
        workload_key="canneal",
        policy="kleio_lite",
        model_path_value=model_path,
        result_root="outputs/results/ml_baselines")

    self.assertIn("qmap/learned_baselines.py", train_command)
    self.assertEqual("kleio_lite", train_command[
        train_command.index("--policy") + 1])
    self.assertEqual(config["train_trace"], train_command[
        train_command.index("--train_trace") + 1])
    self.assertEqual(model_path, train_command[
        train_command.index("--model_output") + 1])

    self.assertIn("qmap/qmap_eval.py", eval_command)
    self.assertEqual("kleio_lite", eval_command[
        eval_command.index("--policy") + 1])
    self.assertEqual(model_path, eval_command[
        eval_command.index("--learned_model") + 1])
    self.assertEqual(result_path, eval_command[
        eval_command.index("--json_output") + 1])


if __name__ == "__main__":
  unittest.main()
