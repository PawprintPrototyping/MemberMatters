import { api } from 'boot/axios';
import { initSentry } from 'boot/sentry';

export default {
  namespaced: true,
  state: {
    siteName: 'MemberMatters Portal',
    siteOwner: 'MemberMatters',
    siteLocaleCurrency: 'en-AU',
    contact: {},
    homepageCards: {},
    webcamLinks: {},
    keys: {},
    features: {},
    kioskId: null,
    images: {},
    theme: {},
  },
  getters: {
    siteName: (state) => state.siteName,
    siteOwner: (state) => state.siteOwner,
    siteLocaleCurrency: (state) => state.siteLocaleCurrency,
    contact: (state) => state.contact,
    homepageCards: (state) => state.homepageCards,
    webcamLinks: (state) => state.webcamLinks,
    keys: (state) => state.keys,
    features: (state) => state.features,
    kioskId: (state) => state.kioskId,
    images: (state) => state.images,
    theme: (state) => state.theme,
  },
  mutations: {
    setSiteName(state, payload) {
      state.siteName = payload;
    },
    setSiteOwner(state, payload) {
      state.siteOwner = payload;
    },
    setSiteLocaleCurrency(state, payload) {
      state.siteLocaleCurrency = payload;
    },
    setContact(state, payload) {
      state.contact = payload;
    },
    setHomepageCards(state, payload) {
      state.homepageCards = payload;
    },
    setWebcamLinks(state, payload) {
      state.webcamLinks = payload;
    },
    setKeys(state, payload) {
      state.keys = payload;
    },
    setFeatures(state, payload) {
      state.features = payload;
    },
    setKioskId(state, payload) {
      state.kioskId = payload;
    },
    setImages(state, payload) {
      state.images = payload;
    },
    setTheme(state, payload) {
      state.theme = payload;
    },
  },
  actions: {
    getSiteConfig({ commit }) {
      return new Promise((resolve, reject) => {
        api
          .get('/api/config/')
          .then((result) => {
            commit('setSiteName', result.data.general.siteName);
            commit('setSiteOwner', result.data.general.siteOwner);
            commit(
              'setSiteLocaleCurrency',
              result.data.general.siteLocaleCurrency,
            );
            commit('setContact', result.data.contact);
            commit('setHomepageCards', result.data.homepageCards);
            commit('setWebcamLinks', result.data.webcamLinks);
            commit('setKeys', result.data.keys);
            commit('setFeatures', result.data.features);
            commit('setImages', result.data.images);
            commit('setTheme', result.data.theme);

            // Initialise Sentry once the DSN is known. initSentry() is a
            // no-op without a DSN or in development, and ignores repeat
            // calls, so a config refetch won't re-init the client.
            initSentry(result.data.sentryDSN, {
              environment: result.data.sentryEnvironment,
              tags: {
                siteOwner: result.data.general.siteOwner,
                siteContact: result.data.contact?.sysadmin,
              },
            });

            const { analyticsId } = result.data;

            if (analyticsId) {
              const scriptId = 'gtag-script';
              if (!document.getElementById(scriptId)) {
                const script = document.createElement('script');
                script.id = scriptId;
                script.async = true;
                script.src = `https://www.googletagmanager.com/gtag/js?id=${analyticsId}`;
                document.head.insertBefore(script, document.head.firstChild);

                window.dataLayer = window.dataLayer || [];
                window.gtag = function () {
                  dataLayer.push(arguments);
                };

                gtag('js', new Date());
                gtag('config', analyticsId);
              }
            }

            resolve();
          })
          .catch((e) => {
            console.warn(e);
            reject();
          });
      });
    },
    async getKioskId({ commit }) {
      if (!window.memberMatters) {
        throw new Error('Electron kiosk identity bridge is unavailable');
      }

      commit('setKioskId', await window.memberMatters.getKioskIdentity());
    },
    pushKioskId({ state }) {
      return new Promise((resolve, reject) => {
        api
          .put('/api/kiosks/', { name: state.kioskId, kioskId: state.kioskId })
          .then((result) => {
            resolve(result);
          })
          .catch((error) => {
            reject();
            throw error;
          });
      });
    },
  },
};
