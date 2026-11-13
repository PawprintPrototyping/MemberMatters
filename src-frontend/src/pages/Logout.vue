<template>
  <q-page class="flex flex-center">
    <q-card class="q-pa-lg">
      <q-spinner v-if="spinner && !error" color="primary-btn" size="3em" />

      <q-banner v-if="!spinner" class="bg-positive text-white">
        {{ $t('logoutPage.logoutSuccess') }}
      </q-banner>

      <q-banner v-if="error" class="bg-negative text-white">
        {{ $t('logoutPage.logoutFailed') }}
      </q-banner>
    </q-card>
  </q-page>
</template>

<script lang="ts">
import { mapMutations } from 'vuex';
import { defineComponent } from 'vue';

export default defineComponent({
  name: 'LogoutPage',
  data() {
    return {
      error: false,
      spinner: true,
    };
  },
  mounted() {
    const logoutRequests = [this.$axios.post('/api/logout/')];
    if (this.$q.platform.is.capacitor) {
      logoutRequests.push(
        this.$axios.delete('/_allauth/app/v1/auth/session', {
          headers: { Accept: 'application/json' },
        }),
      );
    }

    Promise.allSettled(logoutRequests)
      .then((responses) => {
        const failed = responses.find(
          (response) => response.status === 'rejected',
        );
        if (failed && failed.reason?.response?.status !== 401) {
          throw failed.reason;
        }
        this.completeLogout();
      })
      .catch(() => {
        this.error = true;
      });
  },
  methods: {
    ...mapMutations('profile', ['setLoggedIn', 'resetState']),
    ...mapMutations('auth', ['setAuth']),
    completeLogout() {
      this.resetState();
      this.setAuth({ access: '', refresh: '' });
      this.setLoggedIn(false);
      this.error = false;
      this.spinner = false;
      setTimeout(() => {
        this.$router.push({ name: 'login' });
      }, 2000);
    },
  },
});
</script>
