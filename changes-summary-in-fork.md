# Major changes and updates in this fork.

## Billing / Stripe hardening & invoicing

- New **"Pay by Invoice"** billing method (`ENABLE_INVOICE_BILLING`, due-days,
  notes) plus a **Pending Invoices** admin screen with mark-as-paid.
- Extensive webhook hardening: idempotency, race/lock-contention fixes, scoping
  webhooks to the member's own subscription, unique `stripe_customer_id`.
- `ENABLE_NEW_SUBSCRIPTIONS` kill-switch; payment-plan **descriptions**, "year"
  interval, and interval-casing fixes.

## Membership signup & lifecycle rework

- New derived `signupStage` field on `/api/profile/`; frontend screens
  (`MembershipStatusCard`, `MembershipPlan`, dashboard) all collapse onto it.
- Backend consolidated: `Profile.complete_signup()` / `complete_cancel()` replace
  the old `MakeMember` path.
- New **Terms & Conditions** step and **privacy-policy consent** checkbox in signup
  (`SIGNUP_REQUIRE_PRIVACY_CONSENT`, `TERMS_ACCEPTANCE_CARDS`, `terms_accepted_at`).
- `FORCE_SIGNUP_COMPLETION` redirects unfinished members; new admin **Signup
  Progress** and **Signup Preview** screens.

## Admin ManageMember overhaul

- The monolithic `ManageMember.vue` (~1,700 lines) split into per-tab components:
  **Access / Billing / Logs / Profile** tabs.
- "Three orthogonal buttons" model for member state; standalone **state-lock**
  control (`state_locked`), **Toggle Access** (`admin_disabled_access`), **Cancel
  Membership** endpoint, and an "ensure Stripe customer" tool.

## Induction requirements overhaul

- Replaced hardcoded handling of Canvas/Moodle induction scoring with an unified
  provider-based architecture.
  - Create centralized induction service (`services/induction.py`) to handle provider
    refresh and status aggregation.
  - User induction state table replaces `lastInduction` field for determining member
    induction completion.
- Add [Docuseal](https://www.docuseal.com/) integration for kicking off document
  signing as an induction requirement.

## Email handling improvements

- Add support for SMTP server configuration (in addition to Postmark).
  - Refactored to use Django email abstraction so support for any other supported
    transactional mail services is much easier.
- Support for syncing emails of active and inactive members to [Listmonk](https://listmonk.app/).

## Code quality and stability improvements

- Introduce backend [unit test coverage](https://coveralls.io/github/PawprintPrototyping/MemberMatters)
  for all new code changes.
- Configure internal nginx proxy for proper container logging.

## Security improvements

- Upgrade all major frameworks and dependencies to their latest versions and
  configure Dependabot to keep everything up to date.
- Upgrade Docker base image from Debian Bookworm to Trixie.
- Static security analysis of Github Actions using [Zizmor](https://zizmor.sh/).


# Smaller edits

- **Phone numbers → E.164**: client-side validation/formatting via
  `libphonenumber-js`, stored as E.164, parsed against a configurable
  `PROFILE_DEFAULT_PHONE_REGION`, plus a `backfill_phone_e164` management command.
- **Account/auth hardening**: unique `screen_name` constraint, case-insensitive
  email, atomic user writes, throttling on Register/ResetPassword, atomic
  verify-email token, `ENABLE_REGISTRATION` kill-switch.
- **Configurability**: new toggles to hide/disable features — recent-swipes page,
  last-seen page, report-issue card, member email/basic-detail editing, optional
  screen name, member-entered access cards.
- **UX polish**: responsive dashboard/quick-card grids, mobile-friendly metrics
  charts, profile form switched from auto-save to explicit submit, per-route
  `allowedStates` route guards.
- **Privacy improvements**: adds option to prefer handle over full name.
- **i18n & infra**: expanded Swedish (sv-SE) and en-AU translations
  - Docker image builds retargeted to the fork with GHCR.
  - Switch to `uv` for backend dependency management.
  - CI efficiency improvements with build cache, build only runs frontend or
    backend build as necessary.
