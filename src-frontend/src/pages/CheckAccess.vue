<template>
  <q-page class="column flex content-center justify-center justify-start">
    <p class="text-body1 text-center q-pa-md">
      {{ $t('access.pageDescription') }}
    </p>
    <div class="column full-width" style="max-width: 800px">
      <q-banner
        v-if="profile.memberStatus !== 'active'"
        inline-actions
        rounded
        class="bg-orange text-white q-ma-md"
      >
        <template v-slot:avatar>
          <q-icon :name="icons.warning" />
        </template>
        {{ $t('access.inactive') }}
      </q-banner>

      <access-list />
    </div>
  </q-page>
</template>

<script>
import { mapGetters } from 'vuex';
import AccessList from '@components/AccessList.vue';
import icons from '../icons';

export default {
  name: 'CheckAccessPage',
  components: { AccessList },
  computed: {
    ...mapGetters('profile', ['profile']),
    icons() {
      return icons;
    },
  },
};
</script>

<style lang="sass" scoped>
.page-description
  max-width: $maxWidthMedium
  margin: 0 auto
</style>
