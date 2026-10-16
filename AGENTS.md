# Working on Pixel Engine

This is a standalone proprietary desktop engine, not a wrapper around a game
engine. Preserve the separation between `pixel-engine` and `engine-lab`.

- Read README.md and docs/ARCHITECTURE.md first. Run `engine-lab describe` for
  the live protocol and authoritative scene schema; never guess scene fields.
- Use `python3 scripts/verify.py --gpu` on a GPU machine. Without a GPU, omit
  the flag and explicitly report that rendering was not verified.
- Use JSON scenes, named cameras, fixed ticks and seeds for visual changes.
  Capture before/after images and inspect them. Tests cannot certify beauty.
- `serve` uses the real renderer headlessly. `run --agent-stdio` controls the
  same session in a native window. Both start paused for deterministic control.
- stdout is exclusively command responses in agent mode; diagnostics go to stderr.
- Keep chosen pixel resolution stable. Never hide performance regressions by
  automatically changing pixel size. Scale effect quality separately.
- Keep baseline and research variants independently selectable. Record prior
  art, hypotheses, costs and visual findings in docs/RESEARCH.md.
- Don't promote experimental defaults based only on an FPS result or one still.
- Mac tests do not verify Windows rendering. Keep unresolved acceptance gates
  visible in docs/STATUS.md. Do not claim target-hardware support from compilation.
- GPU replay is same-device repeatable; cross-vendor results use tolerances.
- Shader reload is transactional: failures must preserve the working pipelines.
- Use the shared Session operations for inspector/automation features.
- Keep secrets and model-provider dependencies out of this engine. Agent access
  is a local authoring interface and requires no external AI service.
