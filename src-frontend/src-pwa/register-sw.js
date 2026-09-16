/* eslint-disable */
import { register } from 'register-service-worker';

register(import.meta.env.QUASAR_SERVICE_WORKER_FILE, {
  ready() {
    if (import.meta.env.DEV) {
      console.log('App is being served from cache by a service worker.');
    }
  },

  registered(/* registration */) {
    if (import.meta.env.DEV) {
      console.log('Service worker has been registered.');
    }
  },

  cached(/* registration */) {
    if (import.meta.env.DEV) {
      console.log('Content has been cached for offline use.');
    }
  },

  updatefound(/* registration */) {
    if (import.meta.env.DEV) {
      console.log('New content is downloading.');
    }
  },

  updated(/* registration */) {
    if (import.meta.env.DEV) {
      console.log('New content is available; please refresh.');
    }
  },

  offline() {
    if (import.meta.env.DEV) {
      console.log(
        'No internet connection found. App is running in offline mode.',
      );
    }
  },

  error(err) {
    if (import.meta.env.DEV) {
      console.error('Error during service worker registration:', err);
    }
  },
});
