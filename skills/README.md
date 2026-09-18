# OpsPilot Skills

Each `SKILL.md` contains one domain-specific diagnosis SOP. `SkillManager` loads
the files at startup and injects only the SOP whose `agents` and `keywords`
match the current request.

Built-in domains:

- `network`: VPN, DNS, connectivity and latency
- `identity_access`: account, authentication and authorization
- `software`: operating system and application failures
- `device`: endpoints, printers and peripherals
- `security`: phishing, malware, leakage and intrusion

After editing a skill, reload it with `POST /skills/reload` and inspect the
active set with `GET /skills`.
