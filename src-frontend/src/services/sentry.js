import * as Sentry from '@sentry/vue';
import { version } from '../../package.json';

let vueApp = null;
let vueRouter = null;
let initialised = false;

/**
 * Initialise the Sentry browser client.
 *
 * @param {string} dsn DSN from the backend config endpoint.
 * @param {object} [options]
 * @param {string} [options.environment] Deploy environment (e.g. Staging).
 * @param {object} [options.tags] Extra tags to attach to every event.
 */
export function initSentry(dsn, { environment, tags = {} } = {}) {
  if (initialised || !dsn || import.meta.env.DEV) {
    return;
  }
  initialised = true;

  Sentry.init({
    app: vueApp,
    dsn,
    environment: environment || 'UNKNOWN',
    // Prefer the CI-injected release (commit SHA) so it matches the uploaded source maps.
    release: import.meta.env.sentryRelease || version,
    integrations: vueRouter
      ? [Sentry.browserTracingIntegration({ router: vueRouter })]
      : [],
    initialScope: {
      tags,
    },
    tracesSampleRate: 0.01, // Capture 1% of transactions for performance monitoring.
    autoSessionTracking: false, // GlitchTip does not support sessions.
    tracePropagationTargets: ['localhost', /^\//], // Only send traces for our own app's requests.
  });
}

export function configureSentry(app, router) {
  vueApp = app;
  vueRouter = router;
}
