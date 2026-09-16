import 'axios';
import { Preferences } from '@capacitor/preferences';

export default {
  namespaced: true,
  state: {
    accessToken: '',
    refreshToken: '',
  },
  getters: {
    accessToken: (state) => state.accessToken,
    refreshToken: (state) => state.refreshToken,
  },
  actions: {
    async retrieveAuth({ commit }) {
      await Preferences.migrate();
      const accessToken = await Preferences.get({ key: 'accessToken' });
      const refreshToken = await Preferences.get({ key: 'refreshToken' });
      commit('setAuth', {
        access: accessToken.value,
        refresh: refreshToken.value,
      });
    },
  },
  mutations: {
    async setAuth(state, payload) {
      if (payload.access || payload.access === '') {
        state.accessToken = payload.access;
        await Preferences.set({
          key: 'accessToken',
          value: payload.access,
        });
      }

      if (payload.refresh || payload.refresh === '') {
        state.refreshToken = payload.refresh;
        await Preferences.set({
          key: 'refreshToken',
          value: payload.refresh,
        });
      }
    },
  },
};
