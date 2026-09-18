---
name: Network diagnosis SOP
description: Safe diagnosis workflow for enterprise network incidents
keywords: 网络,wifi,vpn,dns,丢包,断网,延迟,代理,网关,ip,无法连接
agents: network
enabled: true
---

## Required evidence

- Record time, location, affected users, connection type and target address.
- Distinguish local connectivity, DNS resolution, route reachability and application-layer access.

## Procedure

1. Confirm whether the device has a valid IP, gateway and DNS server.
2. Compare access by hostname and IP to isolate DNS issues.
3. For VPN, verify client version, account status, MFA and gateway reachability.
4. Check whether one user, one site or the whole company is affected.
5. State a verification command or observable result for every action.

## Escalate when

- Multiple users or a site are offline, packet loss persists, or a shared gateway is unavailable.
- A firewall, switch, route or production configuration must be changed.

Never ask for passwords, VPN secrets or private keys. Never recommend disabling security controls.

