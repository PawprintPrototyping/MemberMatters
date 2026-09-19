<template>
  <div>
    <router-view />

    <q-dialog v-model="loginModal">
      <login-card no-redirect @login-complete="loginModal = false" />
    </q-dialog>

    <kiosk-settings v-if="$q.platform.is.electron" />
  </div>
</template>

<script>
import { mapActions, mapGetters, mapMutations } from 'vuex';
import { defineComponent } from 'vue';
import { setCssVar, Platform } from 'quasar';
import KioskSettings from '@components/Settings.vue';
import LoginCard from '@components/LoginCard.vue';
import { api } from 'boot/axios';

setCssVar('dark', '#313131');

export default defineComponent({
  name: 'App',
  provide() {
    return {
      $axios: api,
    };
  },
  components: { KioskSettings, LoginCard },
  data() {
    return {
      loginModal: false,
    };
  },
  computed: {
    ...mapGetters('config', [
      'siteName',
      'keys',
      'features',
      'theme',
      'images',
    ]),
    ...mapGetters('profile', ['loggedIn']),
    ...mapGetters('auth', ['refreshToken']),
  },
  watch: {
    $route() {
      this.updatePageTitle();
    },
    loggedIn(value) {
      // if (!value) this.$router.push({ name: 'login' });
      if (value) this.getProfile();
    },
  },
  beforeCreate() {
    this.$axios.interceptors.response.use(
      (response) => response,
      (error) => {
        // If we get a 401 and it's not the loggedin check endpoint, or reset password/login page, redirect user to login screen
        if (
          error.response &&
          error.response.status === 401 &&
          !error.response.config.url.includes('/api/loggedin/')
        ) {
          // this means our access token probably just expired so request a new one
          if (
            error.response.data.code === 'token_not_valid' &&
            Platform.is.capacitor &&
            error.response.data?.messages[0]?.token_class === 'AccessToken'
          ) {
            const refreshAllauth = this.$axios.post(
              '/_allauth/app/v1/tokens/refresh',
              { refresh_token: this.refreshToken },
              { headers: { Accept: 'application/json' } },
            );
            refreshAllauth
              .catch(() =>
                this.$axios.post('/api/token/refresh/', {
                  refresh: this.refreshToken,
                }),
              )
              .then((response) => {
                const tokenData = response.data.data || response.data;
                this.setAuth({
                  access: tokenData.access_token || tokenData.access,
                  refresh:
                    tokenData.refresh_token ||
                    tokenData.refresh ||
                    this.refreshToken,
                });
                this.setLoggedIn(true);
                return Promise.resolve();
              })
              .catch(() => {
                // if both refresh endpoints fail, send them back to login
                this.$router.push('/login');
                return Promise.resolve();
              });
          } else {
            this.setLoggedIn(false);
            this.resetState();
            if (
              !window.location.pathname.includes('/profile/password/reset') &&
              !window.location.pathname.includes('/login')
            ) {
              this.$router.push('/login');
              return Promise.resolve();
            }
          }
        }
        return Promise.reject(error);
      },
    );
  },
  async mounted() {
    if (Platform.is.electron) {
      try {
        await this.getKioskId();
        await this.pushKioskId();
      } catch (error) {
        console.error('Unable to initialize kiosk identity', error);
      }
    }

    this.setCardId(null);

    // Get initial portal configuration data
    await this.getPortalConfig();
  },
  methods: {
    ...mapMutations('config', [
      'setSiteName',
      'setHomepageCards',
      'setWebcamLinks',
    ]),
    ...mapMutations('profile', ['setLoggedIn', 'resetState']),
    ...mapMutations('rfid', ['setConnected', 'setCardId']),
    ...mapActions('config', ['getSiteConfig', 'getKioskId', 'pushKioskId']),
    ...mapActions('profile', ['getProfile']),
    ...mapMutations('auth', ['setAuth']),
    updatePageTitle() {
      const pageTitle = this.$route.meta.title;
      const nameKey = pageTitle
        ? `menuLink.${pageTitle}`
        : 'error.pageNotFound';
      document.title = `${this.$t(nameKey)} | ${this.siteName}`;
    },
    getPortalConfig() {
      return new Promise((resolve, reject) => {
        this.getSiteConfig()
          .then(() => {
            this.updatePageTitle();

            setCssVar('primary', this.theme?.themePrimary || '#278ab0');
            setCssVar('secondary', this.theme?.themeToolbar || '#0461b1');
            setCssVar('accent', this.theme?.themeAccent || '#189ab4');

            if (this.images?.siteFavicon) {
              document.querySelectorAll('link[rel="icon"]').forEach((link) => {
                link.href = this.images.siteFavicon;
              });
            }

            resolve();
          })
          .catch((e) => {
            console.error(e);
            console.error('Unable to get portal config!');
            reject(e);
          });
      });
    },
  },
});
</script>
