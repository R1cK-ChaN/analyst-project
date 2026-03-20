# sandbox/

Docker-based code execution sandbox.

**Not used by the companion agent directly.** This module was built for the
research service (now decoupled). It remains as shared infrastructure but the
companion agent never invokes sandbox execution.

## Files

| File | Status | Notes |
|------|--------|-------|
| `manager.py` | Not for companion | Sandbox orchestrator (policy + container) |
| `policy.py` | Not for companion | Execution policy (resource limits, allowed ops) |
| `container_runner.py` | Not for companion | Docker API wrapper |
| `docker/runner.py` | Not for companion | Python runner inside container |
| `limits.py` | Not for companion | Resource limit configs |
