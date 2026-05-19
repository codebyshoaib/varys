---
name: PostHog Staging Credentials
description: PostHog staging project credentials for taleemabad-core — use for feature flags and analytics setup
type: reference
---

## PostHog — Staging

- **Project API Key:** `phc_L82LCN53mjAcEiXxSRPFVEtuSFk9uKuorHM6JLxUeLJ`
- **API Host:** `https://us.i.posthog.com`
- **Defaults:** `2026-01-30`
- **Person profiles:** `identified_only`

## Usage (JS snippet)

```js
posthog.init('phc_L82LCN53mjAcEiXxSRPFVEtuSFk9uKuorHM6JLxUeLJ', {
    api_host: 'https://us.i.posthog.com',
    defaults: '2026-01-30',
    person_profiles: 'identified_only',
})
```

## Notes

- These are **staging** credentials — prod credentials are already in taleemabad-core
- Used for feature flags (e.g. `beaconhouseFdsEnabled`, `maxVisibleLevel`, `trainingFeatureEnabled`)
- Kamal will share prod credentials separately when needed
