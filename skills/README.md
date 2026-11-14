# Bundled model skills

This directory contains vendor-provided prompt skills used by ComicFlow.

- `h3-prompt-writing`: MiniMax H3 prompt structure for T2VA, I2VA, FL2VA,
  L2VA, and reference-based video generation.
- `manju-laoli-drama`: Chinese story, script, continuity, dialogue timing, and
  quality planning rules adapted to ComicFlow's JSON Script Contract.
- `xiaoluo-visual-assets`: Character reference, view, and scene asset rules
  adapted to ComicFlow's image provider and reference asset contracts.

The two drama adapters are project-maintained compatibility layers derived from
the repositories recorded in `HANDOFF.md`. They supplement the H3 skill; they
do not replace it or execute vendor scripts.
