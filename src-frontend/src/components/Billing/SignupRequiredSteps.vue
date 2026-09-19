<template>
  <div class="q-gutter-md">
    <q-stepper v-model="step" ref="stepper" color="primary" animated>
      <q-step
        :name="stepIndex('billing')"
        :title="$t('signup.billing')"
        :icon="icons.billing"
        :active-icon="icons.billing"
        done
      >
        <p class="q-py-md">{{ $t('signup.billingCompletedDescription') }}</p>
      </q-step>

      <q-step
        v-if="enabledSteps.includes('terms')"
        :name="stepIndex('terms')"
        :title="$t('signup.termsAcceptance')"
        :icon="icons.terms"
        :active-icon="icons.terms"
        :done="step > stepIndex('terms')"
      >
        <div class="text-h6 q-py-md">{{ $t('signup.acceptTerms') }}</div>
        <div class="row">
          <terms-acceptance-card
            v-for="(card, i) in termsAcceptanceCards"
            :key="i"
            :icon="card.icon"
            :title="card.title"
            :body-html="card.body_html"
            :checkbox-text="card.checkbox_text"
            v-model="acceptedFlags[i]"
            class="col-12 col-md-6"
          />
        </div>

        <div class="row justify-start q-mt-md">
          <q-space />
          <q-btn
            :disable="!allAccepted || termsSubmitting"
            :loading="termsSubmitting"
            @click="submitTerms"
            color="primary"
            :label="$t('button.continue')"
          />
        </div>
      </q-step>

      <q-step
        v-if="enabledSteps.includes('induction')"
        :name="stepIndex('induction')"
        :title="$t('signup.induction')"
        :icon="icons.induction"
        :active-icon="icons.induction"
        :done="step > stepIndex('induction')"
      >
        <div class="text-h6 q-py-md">
          {{ $t('signup.completeInduction') }}
        </div>
        <div class="row items-stretch">
          <div style="width: 100%">
            <p>{{ $t('signup.completeInductionDescription') }}</p>
          </div>

          <q-list bordered separator class="full-width">
            <q-item
              v-for="provider in inductionProviders"
              :key="provider.provider"
            >
              <q-item-section avatar>
                <q-icon
                  :name="provider.complete ? icons.success : icons.induction"
                  :color="provider.complete ? 'positive' : 'primary'"
                />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{
                  providerLabel(provider.provider)
                }}</q-item-label>
                <q-item-label caption>{{
                  providerStatus(provider)
                }}</q-item-label>
              </q-item-section>
              <q-item-section
                side
                v-if="provider.actionUrl && !provider.complete"
              >
                <q-btn
                  :href="provider.actionUrl"
                  target="_blank"
                  color="primary"
                  :label="$t('signup.startInduction')"
                />
              </q-item-section>
            </q-item>
          </q-list>

          <div v-if="!inductionComplete" class="q-pt-md">
            <p>
              {{ $t('signup.waitingCompletion') }}<br />
              {{ $t('progress', { percent: inductionScore }) }}
            </p>
            <q-spinner size="2em" />
          </div>

          <div v-else class="q-pt-md">
            <p>{{ $t('signup.completedInduction') }}</p>
            <q-icon color="success" size="2em" :name="icons.success" />
          </div>
        </div>

        <div class="row justify-start q-mt-md">
          <q-space />
          <q-btn
            @click="inductionCompleted()"
            :disable="!inductionComplete"
            color="primary"
            :label="$t('button.continue')"
          />
        </div>
      </q-step>

      <q-step
        v-if="enabledSteps.includes('accessCard')"
        :name="stepIndex('accessCard')"
        :title="$t('signup.accessCard')"
        :icon="icons.accessCard"
        :active-icon="icons.accessCard"
        :done="step > stepIndex('accessCard')"
      >
        <div class="text-h6 q-py-md">
          {{ $t('signup.assignAccessCard') }}
        </div>

        <template v-if="features.signup.memberCanEnterAccessCard">
          <div class="row items-stretch">
            <div style="width: 100%">
              <p>
                {{ $t('signup.assignAccessCardDescription') }}
              </p>

              <p>
                <b>
                  {{
                    $t('signup.assignAccessCardWarning', {
                      email: profile.email,
                    })
                  }}
                </b>
              </p>

              <div>
                <q-input
                  style="max-width: 300px"
                  outlined
                  v-model="accessCard"
                  :label="$t('signup.accessCardNumber')"
                />
              </div>
            </div>
          </div>

          <div class="row justify-start q-mt-md">
            <q-space />
            <q-btn
              :disable="accessCardLoading"
              @click="submitAccessCard"
              color="primary"
              :label="$t('button.continue')"
            />
          </div>
        </template>
        <template v-else>
          <div class="row items-stretch">
            <div style="max-width: 400px">
              <p>
                {{ $t('signup.collectAccessCardDescription') }}
              </p>
            </div>
          </div>

          <div class="row justify-start q-mt-md">
            <q-space />
            <q-btn
              :href="features.signup.postInductionUrl"
              target="_blank"
              color="primary"
              :label="$t('button.contactUs')"
            />
          </div>
        </template>
      </q-step>

      <q-step
        :name="stepIndex('confirm')"
        :title="$t('confirm')"
        :icon="icons.success"
        :active-icon="icons.success"
        :done="step >= stepIndex('confirm')"
      >
        <template v-if="awaitingPayment">
          <q-banner class="bg-info text-white">
            <div class="text-h5">{{ $t('signup.awaitingPaymentTitle') }}</div>
            <p>{{ $t('signup.awaitingInvoicePayment') }}</p>
          </q-banner>

          <div class="row justify-start q-mt-md">
            <q-space />
            <q-btn
              :to="{ name: 'dashboard' }"
              color="primary"
              :label="$t('signup.continueToDashboard')"
            />
          </div>
        </template>

        <template v-else-if="signupError">
          <div class="text-h6 q-py-md">
            {{ $t('signup.error') }}
          </div>

          <div style="width: 100%">
            <p>
              {{ $t('signup.errorDescription', { email: contact.admin }) }}
            </p>

            <p>
              {{ $t('signup.errorMessageDescription') }}
              <br />
              <b>{{ signupErrorMessage }}</b>
              <br />
              <b>{{ signupErrorItems }}</b>
            </p>
          </div>
        </template>

        <template v-else>
          <div class="text-h6 q-py-md">
            {{
              $t(
                applicationEmailEnabled
                  ? 'signup.submitted'
                  : 'signup.submittedNoEmail',
              )
            }}
          </div>

          <div class="row items-stretch">
            <div style="width: 100%">
              <p>
                {{
                  $t(
                    applicationEmailEnabled
                      ? 'signup.submittedDescription'
                      : 'signup.submittedDescriptionNoEmail',
                  )
                }}
              </p>
            </div>

            <div class="q-pt-md">
              <q-icon color="success" size="2em" :name="icons.success" />
            </div>
          </div>

          <div class="row justify-start q-mt-md">
            <q-space />
            <q-btn
              :to="{ name: 'dashboard' }"
              color="primary"
              :label="$t('signup.continueToDashboard')"
            />
          </div>
        </template>
      </q-step>
    </q-stepper>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import { mapGetters, mapActions } from 'vuex';
import icons from '@icons';
import { api } from 'src/services/api';
import TermsAcceptanceCard from '@components/Billing/TermsAcceptanceCard.vue';

export default defineComponent({
  name: 'SignupRequiredSteps',
  components: { TermsAcceptanceCard },
  data() {
    const cards =
      this.$store.getters['config/features'].signup.termsAcceptanceCards || [];
    return {
      // Set in created() once enabledSteps is available.
      step: 0,
      inductionComplete: false,
      accessCardComplete: false,
      accessCard: null,
      accessCardLoading: false,
      signupError: false,
      signupErrorMessage: 'Unknown',
      signupErrorItems: [],
      awaitingPayment: false,
      inductionScore: 0,
      inductionProviders: [] as Array<{
        provider: string;
        status: string;
        complete: boolean;
        score: number | null;
        errorCode: string;
        actionUrl: string;
      }>,
      acceptedFlags: new Array(cards.length).fill(false) as boolean[],
      termsSubmitting: false,
      termsAccepted: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      interval: null as any,
    };
  },
  computed: {
    ...mapGetters('config', ['features', 'contact']),
    ...mapGetters('profile', ['profile']),
    icons() {
      return icons;
    },
    // Order here = visual order in the stepper. Adding a step is one line.
    enabledSteps() {
      const steps = ['billing'];
      if (this.termsAcceptanceCards.length > 0) steps.push('terms');
      if (this.features.signup.enableInduction) steps.push('induction');
      if (this.features.signup.requireAccessCard) steps.push('accessCard');
      steps.push('confirm');
      return steps;
    },
    termsAcceptanceCards() {
      return this.features.signup.termsAcceptanceCards || [];
    },
    allAccepted(): boolean {
      return this.acceptedFlags.every(Boolean);
    },
    applicationEmailEnabled(): boolean {
      return this.features.signup.enableMembershipApplicationEmail;
    },
  },
  created() {
    // Billing is a visual breadcrumb only — start on the first real step.
    const initial = this.enabledSteps.find((s) => s !== 'billing');
    this.step = this.stepIndex(initial as string);
  },
  mounted() {
    this.updateInductionStatus();
    this.interval = setInterval(async () => {
      this.updateInductionStatus();
    }, 10000);

    api.get('/api/billing/can-signup/').then((result) => {
      if (result.data.success) {
        // Pre-reqs already met (re-signup, RFID + induction still valid,
        // or relaxed config). Drive complete-signup now — without this the
        // user sits on subscription_status=active|pending with state=noob.
        clearInterval(this.interval);
        this.completeSignup();
      } else {
        // if we don't need the access card, that step is complete
        this.accessCardComplete =
          !result.data.requiredSteps.includes('accessCard');
        this.termsAccepted =
          !result.data.requiredSteps.includes('termsAcceptance');
        // We optimistically landed on terms in created(); bump past if
        // the backend says the user already accepted.
        if (this.termsAccepted && this.step === this.stepIndex('terms')) {
          this.advanceFrom('terms');
        }
      }
    });
  },
  beforeUnmount() {
    // beforeRouteLeave only fires on a route change; a parent re-render,
    // layout swap, or logout that unmounts us without one would leave the
    // 10s poller running. beforeUnmount catches every teardown path.
    clearInterval(this.interval);
  },
  methods: {
    stepIndex(name: string) {
      return this.enabledSteps.indexOf(name);
    },
    // Skips 'accessCard' when the user already has a card on file
    // (re-signup); finalizes when the next step is 'confirm'.
    advanceFrom(name: string) {
      let target = this.stepIndex(name) + 1;
      while (
        this.enabledSteps[target] === 'accessCard' &&
        this.accessCardComplete
      ) {
        target++;
      }
      if (target >= this.stepIndex('confirm')) {
        this.completeSignup();
      } else {
        this.step = target;
      }
    },
    async updateInductionStatus() {
      try {
        const result = await api.post('/api/billing/check-induction/');
        this.inductionComplete = result.data.success;
        this.inductionScore = Math.floor(result.data.score || 0);
        this.inductionProviders = result.data.induction?.providers || [];

        if (this.inductionComplete || result.data.notRequired) {
          this.inductionCompleted();
        }
      } catch {
        this.inductionComplete = false;
      }
    },
    providerLabel(provider: string) {
      return this.$t(`signup.inductionProvider.${provider}`);
    },
    providerStatus(provider: {
      status: string;
      complete: boolean;
      errorCode: string;
      score: number | null;
    }) {
      if (provider.complete) {
        return this.$t('signup.inductionProviderComplete');
      }
      if (provider.errorCode) {
        return this.$t(`signup.${provider.errorCode}`);
      }
      if (provider.score !== null) {
        return this.$t('progress', { percent: provider.score });
      }
      return this.$t('signup.inductionProviderPending');
    },
    inductionCompleted() {
      // Guard against a late poll firing after can-signup already
      // advanced us off the induction step.
      clearInterval(this.interval);
      if (this.step !== this.stepIndex('induction')) return;
      this.advanceFrom('induction');
    },
    ...mapActions('profile', ['getProfile']),
    async completeSignup() {
      api
        .post('/api/billing/complete-signup/')
        .then((result) => {
          if (result.data.awaitingPayment) {
            this.awaitingPayment = true;
            // Refresh so the parent re-derives signupStage and swaps to the
            // awaiting-payment view.
            this.getProfile();
          } else if (!result.data.success) {
            this.signupError = true;
            this.signupErrorMessage = result.data.message;
            this.signupErrorItems = result.data.items;
          } else {
            this.signupError = false;
            // Server flipped the member to active — refresh the profile so
            // the parent page re-derives signupStage (-> "managed") and
            // advances off the required-steps view.
            this.getProfile();
          }
        })
        .catch(() => {
          this.signupError = true;
        })
        .finally(() => {
          // Land on the final "Submitted" step regardless of caller.
          this.step = this.stepIndex('confirm');
        });
    },
    async submitTerms() {
      this.termsSubmitting = true;
      try {
        await api.post('/api/billing/accept-terms/');
        this.advanceFrom('terms');
      } catch {
        this.$q.dialog({
          title: this.$t('error.error'),
          message: this.$t('signup.termsAcceptError'),
        });
      } finally {
        this.termsSubmitting = false;
      }
    },
    async submitAccessCard() {
      this.accessCardLoading = true;
      await api
        .post('/api/billing/access-card/', {
          accessCard: this.accessCard,
        })
        .then((result) => {
          if (result.data.success) {
            this.advanceFrom('accessCard');
          } else {
            this.showAccessCardError(result.data?.message);
          }
        })
        .catch((err) => {
          this.showAccessCardError(err.response?.data?.message);
        })
        .finally(() => {
          this.accessCardLoading = false;
        });
    },
    showAccessCardError(messageKey) {
      this.$q.dialog({
        title: this.$t('error.error'),
        message: messageKey ? this.$t(messageKey) : this.$t('error.contactUs'),
      });
    },
  },
});
</script>
