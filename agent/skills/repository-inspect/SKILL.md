---
name: repository-inspect
description: Inspect a public GitHub repository read-only and return framework candidates with file and dependency evidence. Use before recommending a deployment preset.
---

# Repository Inspect

Accept only a public GitHub HTTPS repository URL. Shallow-clone into a temporary
directory, inspect known dependency and build files, return candidates and
evidence, and always remove the temporary clone.
