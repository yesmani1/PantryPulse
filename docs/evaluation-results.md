# Evaluation results

`python scripts/run_evaluations.py` reports 20/20 deterministic date-label
cases and a 5/5 PantryAgent specialist topology. Donation safety is covered by
the deterministic replenishment and donation tests: unsealed items and high-risk
Use By items are rejected. One bounded live Bedrock call successfully wrote only
aggregate SDK metrics to ignored `.cache/evaluations/bedrock_metrics.json`.

These results contain no household data, prompts, responses, or credentials.
BE-24 remains PARTIAL until a fake-model invocation trace proves tool selection;
BE-25 remains PARTIAL until a safe committed aggregate metrics artifact is added.
