<template>
  <q-page class="column flex content-center justify-start">
    <q-banner
      v-if="!features.enableMembershipPayments"
      class="bg-warning text-dark q-mb-md"
    >
      <i18n-t keypath="tiers.membershipPaymentsDisabled" tag="span">
        <template v-slot:warning>
          <strong>{{ $t('warning').toUpperCase() }}</strong>
        </template>
        <template v-slot:flag1>
          <code>ENABLE_STRIPE</code>
        </template>
        <template v-slot:flag2>
          <code>ENABLE_STRIPE_MEMBERSHIP_PAYMENTS</code>
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
    <br />
    <tiers-list />
  </q-page>
</template>

<script lang="ts">
import TiersList from '@components/AdminTools/TiersList.vue';
import { mapGetters } from 'vuex';

export default {
  name: 'ManageTiers',
  components: { TiersList },
  computed: {
    ...mapGetters('config', ['features']),
  },
};
</script>
