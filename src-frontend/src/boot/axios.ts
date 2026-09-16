import axios, { AxiosInstance } from 'axios';
import { Platform } from 'quasar';
import { boot } from 'quasar/wrappers';
import store from '../store';

declare module '@vue/runtime-core' {
  interface ComponentCustomProperties {
    $axios: AxiosInstance;
  }
}

const api = axios.create({
  baseURL: import.meta.env.apiBaseUrl || '',
  withCredentials: true,
  xsrfCookieName: 'csrftoken',
  xsrfHeaderName: 'X-CSRFTOKEN',
});

export default boot(({ app }) => {
  // This interceptor adds the JWT to the request if it exists (ie mobile app)
  api.interceptors.request.use(function (config) {
    const token = store.state.auth?.accessToken;

    if (Platform.is.capacitor && token) {
      if (config && config.headers)
        config.headers.Authorization = `Bearer ${token}`;
    }

    return config;
  });

  api.interceptors.response.use(
    function (response) {
      return response;
    },
    function (error) {
      if (error.response && error.response.status === 401) {
        store.commit('auth/setAuth', {});
        return Promise.reject(error);
      } else {
        return Promise.reject(error);
      }
    },
  );

  app.config.globalProperties.$axios = api;
});

export { api };
