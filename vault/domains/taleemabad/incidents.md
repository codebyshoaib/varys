# Taleemabad Incidents & Post-mortems

Tracks critical incidents, data loss events, architectural gaps, and recovery status.

---

## Mobile App OutOfMemoryError Crashes (RESOLVING)

**Date reported:** April 24, 2026  
**Date escalated:** April 30, 2026  
**Severity:** CRITICAL — 3.1K crashes/week, 230 users affected, app crashes every 2-3 hours  
**Status:** v1123 deployed (console.log fix), v1124 ready to implement (memory leak fixes)  
**Owned by:** Muhammad Kamal (diagnosis + v1124 implementation)  
**Root cause:** 6 issues cascading: 5 memory leaks + console.log pressure  

### Quick Summary

Mobile app (Android WebView) crashes with OutOfMemoryError after 2-3 hours of use. Firebase Crashlytics shows crash escalation: 1.1K events (65 users) Apr 24 → 3.1K events (230 users) Apr 24-30.

**Root Causes Identified:**
1. ✅ Console.log pressure (631 statements in production) — **FIXED in v1123**
2. 🔧 Observation recording audio URLs not revoked (2-5MB leak per preview) — **Ready to fix in v1124**
3. 🔧 WebSocket notification map cleanup threshold too high (TTL ignored until 100+ items) — **Ready to fix in v1124**
4. ⚠️ Post editor media URLs not revoked on cancel (1-5MB per upload)
5. ⚠️ Download manager listeners never unregistered
6. ⚠️ Analytics events unbounded growth

### Solution Phases

| Version | Fix | Impact | Timeline |
|---------|-----|--------|----------|
| v1123 | Remove 631 console.log statements | 50% reduction | ✅ Deployed |
| v1124 | Fix audio URLs + WebSocket cleanup | +30-40% = 80% total | 🔧 Ready (1h to implement) |
| v1125 | Post editor + image optimization + lifecycle | +15% = 95% total | Next sprint |

### Documentation

- **Detailed Analysis**: `FRONTEND-MEMORY-LEAK-ANALYSIS.md` (5 confirmed + 3 partial leaks)
- **AI Findings Review**: `AI-CRASHLYTICS-ANALYSIS-REVIEW.md` (validation of Firebase Crashlytics AI)
- **Implementation Guide**: `IMPLEMENTATION-PLAN-V1124.md` (step-by-step fixes)
- **Complete Summary**: `MEMORY-CRASH-RESOLUTION-SUMMARY.md` (overview + timeline)
- **Session Log**: `workspace/logs/2026-04-30.md` (detailed investigation log)

### Next Action

- [ ] Implement v1124 (2 critical fixes)
- [ ] Code review + merge
- [ ] Build APK and upload to Firebase Distribution
- [ ] Monitor Crashlytics for 80% crash reduction within 24h

---

## taleemabad-core Memory Leak / Regression (INVESTIGATING)

**Date reported:** April 27, 2026  
**Severity:** HIGH — Production memory utilization ~90%, performance impact  
**Status:** Phase 1 Root Cause Investigation (systematic debugging in progress)  
**Suspect PR:** #4936  
**Owned by:** Muhammad Kamal (diagnosis), Team (code review)  
**Related:** [[memory-leak-apr27-2026|Full incident document]]

### Quick Summary

Post-deployment (Apr 23), gunicorn workers consuming 2-20.7% MEM each (normally 2-5%), total system memory ~90%. Memory normalizes immediately when ASGI service stops, indicating application-layer issue.

**Temporary mitigation:** Reduced parallel worker load (performance impact — NOT permanent).

### Current Phase

🔍 **Phase 1: Root Cause Investigation** (IN PROGRESS)
- Code changes analysis pending
- Diagnostic instrumentation framework designed
- Hypothesis ranking in progress

See [[memory-leak-apr27-2026]] for full investigation checklist and diagnostic plan.

---

## Taleemabad-Auth Architectural Gaps (ACTIVE)

**Date reported:** April 21, 2026  
**Severity:** HIGH — Service under development, gaps block production readiness  
**Owned by:** Muhammad Kamal (architecture decision)  
**Related:** [[workspace/domains/taleemabad/people/omer-rana#4-Week Coaching Review]]

### What's Missing

1. **User Data Ownership** — unclear if Auth Service or taleemabad-core is source of truth
2. **Role Level Definitions** — Teachers/Principals/Admins need clear level assignments
3. **Permission Model** — Fine-grained vs level-based access control unclear
4. **Deletion Flow** — No documented user deletion synchronization between services
5. **Sync Strategy** — User creation/update flows not defined across CMS, Core, Mobile
6. **Testing** — Missing test coverage for integration across all Orenda services
7. **Documentation** — No CLAUDE.md, Swagger/OpenAPI, or Taleemabad Integration Architecture doc

### Context

- v1 basic app setup complete (Omer Rana)
- Currently under QA testing with Saleh
- **Concern:** Project created by prompt/AI; lacks original architectural thinking
- No clear integration strategy with taleemabad-core, CMS, mobile, and other services

### GitHub Issues Created

- [#3 Missing CLAUDE.md](https://github.com/Orenda-Project/Taleemabad-Auth/issues/3)
- [#4 Missing Swagger/OpenAPI](https://github.com/Orenda-Project/Taleemabad-Auth/issues/4)
- [#5 Missing Taleemabad Integration Architecture](https://github.com/Orenda-Project/Taleemabad-Auth/issues/5)

### Action Items

| Action | Owner | Priority |
|--------|-------|----------|
| Define user data ownership across services | Kamal | High |
| Document role level hierarchy & permission model | Kamal | High |
| Create integration architecture doc | Kamal | High |
| Add comprehensive test suite (unit + integration) | Omer / Saim | High |
| Add CLAUDE.md with workspace automation | Omer | Medium |
| Generate Swagger/OpenAPI docs | Dev | Medium |

---

## Student Photo Data Loss (CRITICAL — RECOVERY IN PROGRESS)

**Date reported:** April 20, 2026  
**Date discovered:** April 18, 2026 (by Saleh Muhammad)  
**Duration:** ~10 days undetected (April 10–18, 2026)  
**Severity:** CRITICAL — Data Loss + Financial Impact (Rs. 416,000/month)  
**Status:** Reverted — Recovery blocked on manual photo collection  
**Owned by:** Omer Rana (original fix), Saim (revert), Saleh & Mavia (recovery)

### Incident Summary

On April 10, Omer applied a fix in Task Orchestra: if a student's image path did not start with "USP", replace it with a placeholder before sending to PEF-SIS. This stopped rejections.

However, the fix had an unintended side effect:
- CMS sends correct photo
- Task Orchestra intercepts and swaps with placeholder
- PEF-SIS stores placeholder
- CMS syncs back from PEF-SIS and overwrites real photo with placeholder
- This repeated silently for ~10 days

**Impact:** 260 student records now hold placeholder photos instead of real images, disqualifying them from Rs. 416,000/month in government subsidy (Rs. 1,600 per student).

### Timeline

| Date | Event |
|------|-------|
| Apr 10 | Saleh reports rejections; Omer applies Task Orchestra fix |
| Apr 10–18 | Silent data loss repeats on every CMS-PEF-SIS sync |
| Apr 18 | Saleh discovers data loss while investigating separate bug |
| Apr 18 | Saim reverts Task Orchestra fix; data loss stops |
| Apr 20 | Post-mortem completed; recovery blocked on field collection |

### Root Cause

**Bidirectional sync without safeguards.** The placeholder was stored in PEF-SIS, so every sync faithfully copied it back into CMS — overwriting the real photo already there. No alert or validation caught this.

### Business Impact

- **Monthly loss:** Rs. 416,000 (while records unrestored)
- **Students affected:** 260 records
- **Subsidy condition:** Complete data on PEF-SIS (photo required — placeholder fails)

### Recovery Plan

**Step 1 — Manual photo collection** (Owner: Saleh & Mavia) — **BLOCKING**
- Contact all affected schools and collect actual student photos
- Field-level effort across multiple schools
- Must complete before automated recovery can run

**Step 2 — Recovery script** (Owner: Saim)
- Once photos collected, run script using image endpoint
- Replace all placeholder values in CMS DB with correct restored photos

### Lessons Learned

**What went wrong:**
- Hotfix applied without tracing full data flow in **both directions**
- Inbound sync path not considered when evaluating fix
- No test existed for complete push-sync round-trip
- No monitoring/alert flagged placeholder propagation for ~10 days

**What went right:**
- Issue caught and escalated promptly once discovered
- Fix reverted quickly, stopping further data loss
- Recovery path identified rapidly

### Action Items

| Action | Owner | Priority | Status |
|--------|-------|----------|--------|
| Collect real student photos from all affected schools | Saleh & Mavia | High | Blocked — Field collection |
| Run recovery script to restore photos in CMS | Saim | High | Blocked waiting on photos |
| Add sync safeguard: never overwrite real photo with known placeholder | Dev | Medium | Pending |
| Add data integrity alert for placeholder values entering CMS DB on sync | Dev | Medium | Pending |
| Add round-trip test: CMS push → PEF store → CMS sync back | QA | Medium | Pending |
| Establish review checklist for middleware fixes touching bidirectional sync | Team Lead | Low | Pending |

---

## Qcloud Django Migration Permission Errors (RECURRING — SOLVED)

**First reported:** Recurring across multiple deployments (Apr 28, 2026 onwards)  
**Severity:** MEDIUM — Blocks deployments but has proven fix  
**Frequency:** ~2-3 times per quarter  
**Root causes:**
1. **django-tenants misconfiguration** — app in SHARED_APPS instead of TENANT_APPS (PRIMARY)
2. Transaction locks from live app traffic during foreign key constraint creation
3. Database user permissions (rare with proper setup)

**Status:** SOLVED — Tested solution documented with complete runbook  
**Owned by:** Muhammad Kamal (diagnosis), DevOps (implementation)  
**Related:** [[qcloud-django-migration-permission-error]]

### Issue Summary

When deploying taleemabad-core to Qcloud production:
```
err: django.db.utils.ProgrammingError: permission denied for table neo_neoobservation
err: Failed to apply migrations. Exiting...
```

### Root Cause (Confirmed Apr 28)

The `neo` app was in `SHARED_APPS` but should be in `TENANT_APPS` (multi-tenant setup). When Django tried to:
1. Create tables in `public` schema
2. Add foreign keys to `coaching_observation` (which lives in `fde_production` schema)
3. The cross-schema reference failed

### Proven Solution

**Step 1: Verify django-tenants configuration**
```bash
grep "SHARED_APPS\|TENANT_APPS" repos/taleemabad-core/taleemabad_core/settings/base.py
# Move 'neo' from SHARED_APPS to TENANT_APPS if needed
```

**Step 2: Stop the app** (critical — live traffic blocks locks)
```bash
sudo systemctl stop gunicorn
# Wait for existing transactions to complete
```

**Step 3: Clean up any partial migrations**
```sql
SET search_path TO fde_production;
DROP TABLE IF EXISTS neo_historicalneofeedback CASCADE;
DROP TABLE IF EXISTS neo_historicalneoobservation CASCADE;
DROP TABLE IF EXISTS neo_neofeedback CASCADE;
DROP TABLE IF EXISTS neo_neoobservation CASCADE;
DELETE FROM fde_production.django_migrations WHERE app = 'neo';
```

**Step 4: Run the migration (correct command)**
```bash
python manage.py migrate_schemas --schema=fde_production neo
```

**Step 5: Monitor for locks in pgAdmin** (if stuck):
```sql
SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE query ILIKE '%coaching_observation%'
AND state = 'active'
AND pid != pg_backend_pid();
```

**Step 6: Restart the app**
```bash
sudo systemctl start gunicorn
```

### Lessons Learned

- ✓ Always use `migrate_schemas --schema=<name>` for tenant apps, NOT `migrate`
- ✓ Stop the app server before migrations to prevent lock contention
- ✓ Kill blocking pids (UPDATE queries), not the migration process itself
- ✓ Clear partial tables before retrying — they cause lock cascades
- ✓ Verify SHARED_APPS vs TENANT_APPS configuration before deploying new apps

### Action Items

| Action | Owner | Priority | Status |
|--------|-------|----------|--------|
| Add django-tenants migration guide to taleemabad-core CLAUDE.md | DevOps | High | Pending |
| Add pre-deployment checklist: verify app placement in settings | DevOps | High | Pending |
| Create deployment script that stops app → migrates → restarts | DevOps | High | Pending |
| Document in runbook: when to use migrate vs migrate_schemas | DevOps | Medium | Pending |

---

## Android App Crash — OutOfMemoryError (CRITICAL — BUILD CONFIG FIX READY)

**Date reported:** April 24, 2026  
**Date escalated:** April 30, 2026 (crashes continuing post-fix proposal)  
**Date root cause found:** April 30, 2026 15:58 UTC+5  
**Severity:** 🔴 CRITICAL — Active user-facing crashes, ESCALATING  
**Affected users:** ~230 users, 2.5K–3.1K crash events (Apr 24–30)  
**Platform:** Android (Samsung 28%, Transsion 19%, Xiaomi 18%, Vivo 16%; Android 15/13/12/14/11)  
**Root cause:** ✅ **FOUND** — `build-apk.sh` uses `--configuration=development` instead of `production`  
**Fix:** Change 1 line in build-apk.sh (10 min), rebuild APK, deploy  
**Status:** 🟡 **Ready to deploy — awaiting approval**  
**Owned by:** Muhammad Kamal (verified root cause), Dev (implement fix)  
**Related file:** [[app-crash-oom-escalation-apr30]]

### 🚨 Latest Update (Apr 30, 15:58)

**ROOT CAUSE FOUND & VERIFIED:**

Web app fix ✅ was deployed (no console logs at https://schools.niete.pk).  
Mobile APK fix ❌ was never deployed (build script uses wrong configuration).

| Metric | Finding |
|--------|---------|
| webpack.config.js | ✅ Has `drop_console: true` (lines 26-39) |
| Web app (schools.niete.pk) | ✅ No console logs visible |
| Mobile app (Firebase) | ❌ 3.1K crashes, all 631 console.log calls present |
| **Root cause** | ❌ build-apk.sh line 29: `--configuration=development` |
| **Why crashes continue** | `NODE_ENV !== 'production'` → `drop_console: true` never runs |

### The One-Line Fix

**File**: `frontend/build-apk.sh`  
**Line 29**:

```bash
# WRONG (current):
npx nx run school-app:build --configuration=development

# CORRECT (fix):
npx nx run school-app:build --configuration=production
```

**Impact**: TerserPlugin's `drop_console: true` will run, stripping all console calls from APK.

### Quick Summary

Capacitor bridge's `BridgeWebChromeClient.onConsoleMessage()` crashing due to 631 console.log calls still in APK. webpack.config.js has the fix, but APK build uses `development` configuration which skips TerserPlugin.

### Impact

- **3.1K crashes** in 7 days (230 users)
- **21 crashes per user average** (escalating from 17)
- Affects mid-range/budget Android devices most (Infinix, Xiaomi, Vivo, Oppo, Transsion)
- App becomes unusable when WebView memory exhausted
- **Escalating rapidly** — 49 crashes in last 12 hours

### Action Items (DO THIS NOW)

| Action | Priority | Owner | Status |
|--------|----------|-------|--------|
| **Fix build-apk.sh line 29** (1 line change) | CRITICAL | Dev | Ready |
| **Rebuild APK with production config** | CRITICAL | Dev | Blocked |
| **Verify: grep "console\." dist/main.js \| wc -l → 0** | CRITICAL | QA | Blocked |
| **Deploy new APK (v1123) to Firebase Distribution** | CRITICAL | DevOps | Blocked |
| **Monitor Firebase 2 hours post-deploy** | CRITICAL | Kamal | Pending |
| Expected: Crash rate drops >80% within 2 hours | — | — | Pending |

---

