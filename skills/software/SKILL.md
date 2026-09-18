---
name: Software diagnosis SOP
description: Operating system, application, installation and upgrade diagnosis
keywords: 软件,应用,客户端,程序,安装,升级,崩溃,闪退,报错,500,依赖,日志
agents: software
enabled: true
---

## Required evidence

- Collect application name, version, operating system, exact error and occurrence time.
- Ask what changed immediately before the failure and whether other users are affected.

## Procedure

1. Reproduce the smallest failing action and preserve the exact error.
2. Check service status, configuration, permissions, dependencies and logs in that order.
3. Compare the failing version or environment with a known-good one.
4. Prefer reversible actions; state rollback and verification steps before a change.

Escalate production-wide failures, data corruption, repeated 5xx errors or changes requiring administrator access.
Do not invent log content or claim a backend operation was performed.

