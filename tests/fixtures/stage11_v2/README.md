# Stage11 v2 fixture policy

The Stage11 v2 test suite creates all Stage8, Stage9, Stage10, authorization,
generation, verification, final-approval, and final-status fixtures inside a
fresh `tempfile.TemporaryDirectory`.

These fixtures are synthetic parser and gate inputs only. They are not valid
external evidence, execution authorization, final approval, formal status, or
paper evidence. No persistent fixture in this directory may contain measured
latency, perf, RSS, model-memory, or asynchronous-system claims.
