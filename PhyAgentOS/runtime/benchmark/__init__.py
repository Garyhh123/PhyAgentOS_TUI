"""Runtime-side benchmark glue.

Adapts production runtime targets and skill runtimes to the
executor-independent benchmark package so a benchmark episode can run on
the real OS stack (a ``MinecraftTarget`` acting as the benchmark
``WorldAdapter``) instead of a hand-written mock.
"""
