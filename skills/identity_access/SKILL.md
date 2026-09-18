---
name: Identity and access diagnosis SOP
description: Account, SSO, MFA, authentication and authorization diagnosis
keywords: 账号,账户,登录,权限,认证,授权,密码,sso,ldap,mfa,401,403
agents: identity_access
enabled: true
---

## Required evidence

- Record the login entry, exact status code, affected account scope and latest permission change.
- Never collect a password, verification code, access token or recovery key.

## Procedure

1. Treat 401 as an authentication signal: check expiry, audience, issuer and account state.
2. Treat 403 as an authorization signal: check role, group, resource policy and approval status.
3. Separate a single-account issue from an SSO, LDAP or MFA dependency outage.
4. Recommend only least-privilege access and identify the required approver.
5. Verify with a fresh session and the smallest affected resource.

Escalate account unlocks, role changes, privileged access and shared identity-service outages.

