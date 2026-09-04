<template>
  <q-page class="column flex content-center justify-start">
    <q-banner
      v-if="!features.enableProxyVoting"
      class="bg-warning text-dark q-mb-md"
    >
      <i18n-t keypath="meetings.disabledFeature" tag="span">
        <template v-slot:warning>
          <strong>{{ $t('warning').toUpperCase() }}</strong>
        </template>
        <template v-slot:flag>
          <code>ENABLE_PROXY_VOTING</code>
        </template>
        <template v-slot:configLink>
          <a
            href="/admin/constance/config/"
            target="_blank"
            rel="noopener"
            class="text-dark"
            >Config &rarr; Features</a
          >
        </template>
      </i18n-t>
    </q-banner>

    <meetings-list />
  </q-page>
</template>

<script lang="ts">
import MeetingsList from '@components/MeetingsList.vue';
import { mapGetters } from 'vuex';

export default {
  name: 'MeetingsPage',
  components: { MeetingsList },
  computed: {
    ...mapGetters('config', ['features', 'images']),
  },
};
</script>
