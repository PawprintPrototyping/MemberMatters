<template>
  <div class="q-pa-md login-card flex flex-center">
    <template v-if="!showCard">
      <q-circular-progress
        indeterminate
        size="50px"
        :thickness="0.22"
        track-color="grey-3"
        class="q-ma-md"
      />
    </template>

    <template v-else>
      <q-card v-if="!resetToken && !mfaSetupRequired">
        <q-img
          v-if="images.siteLogo"
          fit="contain"
          :src="images.siteLogo"
          style="max-height: 40px; cursor: pointer"
          class="q-mt-md"
        />

        <h6 class="q-ma-none q-pa-md">
          {{ $t('loginCard.loginToContinue') }}
        </h6>

        <q-card-section>
          <q-form class="q-gutter-md" @submit="onSubmit" @reset="onReset">
            <q-input
              id="username-field"
              v-model="email"
              autofocus
              filled
              autocomplete="on"
              type="email"
              label="Your email"
              lazy-rules
              :rules="[
                (val) => validateEmail(val) || $t('validation.invalidEmail'),
              ]"
            />

            <q-input
              v-if="!mfaRequired"
              v-model="password"
              id="password-field"
              filled
              autocomplete="on"
              type="password"
              label="Your password"
              lazy-rules
              :rules="[
                (val) =>
                  validateNotEmpty(val) || $t('validation.invalidPassword'),
              ]"
            />

            <q-input
              v-if="mfaRequired"
              v-model="mfaCode"
              id="mfa-code-field"
              filled
              autofocus
              autocomplete="one-time-code"
              inputmode="numeric"
              :label="$t('loginCard.mfaCode')"
              :rules="[(val) => validateNotEmpty(val)]"
            />

            <q-banner v-if="mfaRequired" class="bg-info text-white">
              {{ $t('loginCard.mfaRequired') }}
            </q-banner>

            <q-banner v-if="loginComplete" class="bg-positive text-white">
              {{ $t('loginCard.loginSuccess') }}
            </q-banner>

            <q-banner v-if="loginFailed" class="bg-negative text-white">
              {{ $t('error.loginFailed') }}
            </q-banner>

            <q-banner v-if="unverifiedEmail" class="bg-negative text-white">
              {{ $t('loginCard.unverifiedEmail') }}
            </q-banner>

            <q-banner v-if="loginError" class="bg-negative text-white">
              {{ $t('error.requestFailed') }}
            </q-banner>

            <p class="text-caption">
              {{ $t('loginCard.notAMember') }}
              <router-link
                :to="{ name: 'register' }"
                :class="$q.dark.isActive ? 'text-white' : 'text-black'"
                @click="onRegisterClick"
              >
                {{ $t('loginCard.registerHere') }}
              </router-link>
            </p>

            <div class="row">
              <q-space />
              <q-btn
                :label="$t('loginCard.resetPassword')"
                type="reset"
                color="primary"
                flat
                class="q-ml-sm"
                @click="reset.prompt = true"
              />
              <q-btn
                v-if="mfaRequired && mfaTypes.includes('webauthn')"
                :label="$t('loginCard.usePasskey')"
                type="button"
                color="primary"
                flat
                :loading="buttonLoading"
                @click="loginWithPasskey"
              />
              <q-btn
                v-if="!mfaRequired && !discourseSsoData"
                :label="$t('loginCard.usePasskey')"
                type="button"
                color="primary"
                flat
                :loading="buttonLoading"
                @click="loginWithPasskey"
              />
              <q-btn
                :label="
                  mfaRequired
                    ? $t('loginCard.verifyMfa')
                    : $t('loginCard.login')
                "
                :type="mfaRequired ? 'submit' : 'submit'"
                color="primary-btn"
                :loading="buttonLoading"
              />
            </div>
          </q-form>
        </q-card-section>
      </q-card>

      <q-card v-else-if="mfaSetupRequired" class="login-card">
        <h6 class="q-ma-none q-pa-md">
          {{ $t('loginCard.mfaSetupTitle') }}
        </h6>
        <q-card-section>
          <p>{{ $t('loginCard.mfaSetupDescription') }}</p>
          <q-img
            v-if="totpQrCode"
            :src="totpQrCode"
            fit="contain"
            style="max-width: 220px"
            class="q-mb-md"
          />
          <p v-if="totpSecret" class="text-caption">
            {{ $t('loginCard.mfaSetupSecret') }}: <code>{{ totpSecret }}</code>
          </p>
          <q-input
            v-model="mfaSetupCode"
            filled
            autocomplete="one-time-code"
            inputmode="numeric"
            :label="$t('loginCard.mfaCode')"
          />
          <q-banner v-if="loginError" class="bg-negative text-white q-mt-md">
            {{ $t('error.requestFailed') }}
          </q-banner>
          <div class="row q-mt-md">
            <q-space />
            <q-btn
              :label="$t('loginCard.skipMfaSetup')"
              flat
              color="primary"
              @click="skipMfaSetup"
            />
            <q-btn
              :label="$t('loginCard.usePasskey')"
              flat
              color="primary"
              :loading="buttonLoading"
              @click="addPasskey"
            />
            <q-btn
              :label="$t('loginCard.enableMfa')"
              color="primary-btn"
              :loading="buttonLoading"
              @click="activateMfa"
            />
          </div>
        </q-card-section>
      </q-card>

      <q-card v-else class="login-card">
        <h6 class="q-ma-none q-pa-md">
          {{ $t('loginCard.resetPassword') }}
        </h6>
        <q-card-section>
          <q-form class="q-gutter-md" @submit="submitResetPassword">
            <q-input
              v-model="reset.password"
              id="new-password-field"
              filled
              autocomplete="on"
              autofocus
              type="password"
              label="Your new password"
              lazy-rules
              :disable="reset.formDisabled"
              :rules="[
                (val) =>
                  validateNotEmpty(val) || $t('validation.invalidPassword'),
              ]"
            />

            <q-input
              v-model="reset.password2"
              filled
              autocomplete="on"
              id="new-password-confirm-field"
              type="password"
              label="Confirm password"
              lazy-rules
              :disable="reset.formDisabled"
              :rules="[
                (val) =>
                  validateNotEmpty(val) || $t('validation.invalidPassword'),
                (val) =>
                  val === reset.password || $t('validation.passwordNotMatch'),
              ]"
            />

            <q-banner v-if="reset.confirmed" class="bg-positive text-white">
              {{ $t('loginCard.resetConfirm') }}
            </q-banner>

            <q-banner v-if="reset.invalidToken" class="bg-negative text-white">
              {{ $t('loginCard.resetInvalid') }}
            </q-banner>

            <q-banner v-if="reset.failed" class="bg-negative text-white">
              {{ $t('loginCard.resetNotConfirm') }}
            </q-banner>

            <div class="row">
              <q-space />
              <q-btn
                :label="$t('loginCard.backToLogin')"
                color="primary-btn"
                flat
                class="q-ml-sm"
                @click="$router.push({ name: 'login' })"
              />
              <q-btn
                :label="$t('button.submit')"
                type="submit"
                color="primary-btn"
                :disable="reset.formDisabled"
                :loading="reset.loading"
              />
            </div>
          </q-form>
        </q-card-section>
      </q-card>

      <q-dialog v-model="reset.prompt" persistent>
        <q-card style="max-width: 350px">
          <q-card-section>
            <div class="text-h6">
              {{ $t('loginCard.forgottenPassword') }}
            </div>
            <div>
              {{ $t('loginCard.forgottenPasswordDescription') }}
            </div>
          </q-card-section>

          <q-card-section class="q-pt-none">
            <q-input
              v-model="reset.email"
              :label="$t('loginCard.emailLabel')"
              autofocus
              @keyup.enter="resetPassword()"
            />
          </q-card-section>

          <q-banner v-if="reset.success" class="bg-positive text-white q-mx-md">
            {{ $t('loginCard.resetSuccess') }}
          </q-banner>

          <q-banner v-if="reset.failed" class="bg-negative text-white q-mx-md">
            {{ $t('loginCard.resetFailed') }}
          </q-banner>

          <q-card-actions align="right" class="text-primary">
            <q-btn
              v-close-popup
              flat
              :label="
                reset.disableResetSubmitButton
                  ? $t('button.close')
                  : $t('button.cancel')
              "
            />
            <q-btn
              flat
              :label="$t('button.submit')"
              :loading="reset.loading"
              :disable="reset.disableResetSubmitButton"
              @click="resetPassword()"
            />
          </q-card-actions>
        </q-card>
      </q-dialog>
    </template>
  </div>
</template>

<script lang="ts">
import { mapMutations, mapGetters, mapActions } from 'vuex';
import { Loading } from 'quasar';
import formMixin from '../mixins/formMixin';
import { SplashScreen } from '@capacitor/splash-screen';
import { LocationQuery } from 'vue-router';
import { defineComponent } from 'vue';
import QRCode from 'qrcode';

function decodeBase64Url(value: string): ArrayBuffer {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4);
  const bytes = atob(padded);
  return Uint8Array.from(bytes, (char) => char.charCodeAt(0)).buffer;
}

function encodeBase64Url(value: ArrayBuffer | null): string | null {
  if (!value) return null;
  const bytes = new Uint8Array(value);
  let binary = '';
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

type WebAuthnCredentialDescriptorJSON = {
  id: string;
  transports?: string[];
};

type WebAuthnRequestOptionsJSON = {
  challenge: string;
  allowCredentials?: WebAuthnCredentialDescriptorJSON[];
  allow_credentials?: WebAuthnCredentialDescriptorJSON[];
  userVerification?: string;
  user_verification?: string;
  [key: string]: unknown;
};

function parseWebAuthnRequestOptions(
  options: WebAuthnRequestOptionsJSON,
): PublicKeyCredentialRequestOptions {
  const parsed = { ...options };
  parsed.challenge = decodeBase64Url(parsed.challenge);
  const credentials = parsed.allowCredentials || parsed.allow_credentials;
  if (credentials) {
    parsed.allowCredentials = credentials.map((credential) => ({
      ...credential,
      id: decodeBase64Url(credential.id),
      transports: credential.transports as AuthenticatorTransport[] | undefined,
    }));
    delete parsed.allow_credentials;
  }
  if (parsed.user_verification && !parsed.userVerification) {
    parsed.userVerification = parsed.user_verification;
  }
  delete parsed.user_verification;
  return parsed as PublicKeyCredentialRequestOptions;
}

function serializeWebAuthnCredential(
  credential: PublicKeyCredential,
): Record<string, unknown> {
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    id: credential.id,
    rawId: encodeBase64Url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: encodeBase64Url(response.clientDataJSON),
      authenticatorData: encodeBase64Url(response.authenticatorData),
      signature: encodeBase64Url(response.signature),
      userHandle: encodeBase64Url(response.userHandle),
    },
  };
}

function parseWebAuthnCreationOptions(
  options: WebAuthnRequestOptionsJSON & {
    user: { id: string; [key: string]: unknown };
    excludeCredentials?: WebAuthnCredentialDescriptorJSON[];
    exclude_credentials?: WebAuthnCredentialDescriptorJSON[];
  },
): PublicKeyCredentialCreationOptions {
  const parsed = { ...options };
  parsed.challenge = decodeBase64Url(parsed.challenge);
  parsed.user = {
    ...parsed.user,
    id: decodeBase64Url(parsed.user.id),
  } as unknown as typeof parsed.user;
  const credentials = parsed.excludeCredentials || parsed.exclude_credentials;
  if (credentials) {
    parsed.excludeCredentials = credentials.map((credential) => ({
      ...credential,
      id: decodeBase64Url(credential.id),
      transports: credential.transports as AuthenticatorTransport[] | undefined,
    }));
    delete parsed.exclude_credentials;
  }
  return parsed as unknown as PublicKeyCredentialCreationOptions;
}

function serializeWebAuthnCreationCredential(
  credential: PublicKeyCredential,
): Record<string, unknown> {
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    id: credential.id,
    rawId: encodeBase64Url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: encodeBase64Url(response.clientDataJSON),
      attestationObject: encodeBase64Url(response.attestationObject),
      transports: response.getTransports?.(),
    },
  };
}

export default defineComponent({
  name: 'LoginCard',
  mixins: [formMixin],
  props: {
    resetToken: {
      type: String,
      default: null,
    },
    noRedirect: {
      type: Boolean,
      default: false,
    },
  },
  data() {
    return {
      showCard: false,
      email: '' as string | null,
      password: '' as string | null,
      loginFailed: false,
      loginError: false,
      loginComplete: false,
      mfaRequired: false,
      mfaCode: '',
      mfaTypes: [] as string[],
      mfaSetupRequired: false,
      mfaSetupCode: '',
      totpSecret: '',
      totpQrCode: '',
      allauthSessionToken: '',
      unverifiedEmail: false,
      buttonLoading: false,
      discourseSsoData: null as LocationQuery | null,
      reset: {
        email: '' as string | null,
        formDisabled: true,
        success: false,
        failed: false,
        loading: false,
        prompt: false,
        password: '',
        password2: '',
        confirmed: false,
        invalidToken: false,
        disableResetSubmitButton: false,
      },
    };
  },
  async mounted() {
    if (this.$route.query.sso && this.$route.query.sig) {
      this.discourseSsoData = this.$route.query;
    }

    // check if we're logged in and our session is still valid
    await this.retrieveAuth();
    await this.getLoggedIn();

    // if we're logged in then open the app straight away, then
    if (this.loggedIn) {
      this.redirectLoggedIn(false);
    } else {
      await SplashScreen.hide();
      this.showCard = true;
    }

    if (this.resetToken) {
      Loading.show({ message: 'Validating request...' });

      this.validatePasswordReset()
        .then(() => {
          Loading.hide();
          this.reset.formDisabled = false;
        })
        .catch(() => {
          Loading.hide();
          this.reset.invalidToken = true;
        });
    }
  },
  methods: {
    ...mapActions('profile', ['getLoggedIn']),
    ...mapActions('auth', ['retrieveAuth']),
    ...mapMutations('profile', ['setLoggedIn']),
    ...mapMutations('auth', ['setAuth']),
    onRegisterClick(event) {
      if (this.features?.enableRegistration === false) {
        event.preventDefault();
        this.$q.dialog({
          title: this.$t('error.registrationClosed'),
          message:
            this.features?.registrationDisabledMessage ||
            this.$t('error.registrationClosed'),
        });
      }
    },
    /**
     * Redirects to the dashboard page on successful login.
     */
    redirectLoggedIn(delay = true) {
      this.loginFailed = false;
      this.loginError = false;

      if (this.discourseSsoData) {
        this.login();
        return;
      }

      this.loginComplete = true;
      this.$emit('login-complete');

      // oidc login redirect
      if (this.$route.query.next)
        window.location.replace(this.$route.query.next as string);

      // our own login redirect
      if (this.$route.query.nextUrl) {
        this.setLoggedIn(true);
        this.$router.push(this.$route.query.nextUrl as string);
      } else if (!this.noRedirect && delay) {
        setTimeout(() => {
          this.setLoggedIn(true);
          this.$router.push({ name: 'dashboard' });
          setTimeout(SplashScreen.hide, 500);
        }, 1000);
      } else {
        this.$router.push({ name: 'dashboard' });
        setTimeout(SplashScreen.hide, 500);
      }
    },
    onReset() {
      this.email = null;
      this.password = null;
    },
    onSubmit() {
      if (this.mfaRequired) {
        this.completeMfa();
      } else {
        this.login();
      }
    },
    /**
     * This sends the login API request to log the user in.
     */
    login() {
      this.loginFailed = false;
      this.loginError = false;
      this.buttonLoading = true;

      if (this.discourseSsoData) {
        this.$axios
          .post('/api/login/', {
            email: this.email,
            password: this.password,
            sso: this.discourseSsoData,
          })
          .then((response) => {
            this.loginComplete = true;
            window.location = response.data.redirect;
          })
          .catch((error) => {
            if (error.response?.status === 401) {
              this.loginFailed = true;
              this.unverifiedEmail = false;
            } else if (error.response?.status === 403) {
              this.unverifiedEmail = true;
              this.loginFailed = false;
            } else {
              this.loginError = true;
              this.unverifiedEmail = false;
            }
          })
          .finally(() => {
            this.buttonLoading = false;
          });
        return;
      }

      this.loginWithAllauth();
    },
    allauthClient() {
      return this.$q.platform.is.capacitor ? 'app' : 'browser';
    },
    allauthPath(path) {
      return `/_allauth/${this.allauthClient()}/v1${path}`;
    },
    allauthHeaders() {
      const headers: Record<string, string> = { Accept: 'application/json' };
      if (this.allauthClient() === 'app' && this.allauthSessionToken) {
        headers['X-Session-Token'] = this.allauthSessionToken;
      }
      return headers;
    },
    saveAllauthTokens(data) {
      const meta = data?.meta || {};
      if (meta.session_token) this.allauthSessionToken = meta.session_token;
      if (meta.access_token) {
        this.setAuth({
          access: meta.access_token,
          refresh: meta.refresh_token || '',
        });
      }
    },
    setMfaChallenge(data) {
      const flow = (data?.data?.flows || []).find(
        (candidate) =>
          candidate.id === 'mfa_authenticate' && candidate.is_pending,
      );
      if (!flow) return false;

      this.mfaRequired = true;
      this.mfaCode = '';
      this.mfaTypes = flow.types || ['totp', 'recovery_codes'];
      return true;
    },
    async finishAllauthLogin() {
      try {
        const response = await this.$axios.get(
          this.allauthPath('/account/authenticators'),
          { headers: this.allauthHeaders() },
        );
        this.saveAllauthTokens(response.data);
        if (response.data.data?.length === 0) {
          const setupResponse = await this.$axios
            .get(this.allauthPath('/account/authenticators/totp'), {
              headers: this.allauthHeaders(),
            })
            .catch((error) => error.response);
          this.saveAllauthTokens(setupResponse?.data);
          const meta = setupResponse?.data?.meta || {};
          if (meta.secret && meta.totp_url) {
            this.totpSecret = meta.secret;
            this.totpQrCode = await QRCode.toDataURL(meta.totp_url);
            this.mfaSetupRequired = true;
            return;
          }
        }
      } catch {
        // A failed status check should not discard a successful login.
      }
      this.redirectLoggedIn();
    },
    skipMfaSetup() {
      this.mfaSetupRequired = false;
      this.redirectLoggedIn();
    },
    async activateMfa() {
      this.buttonLoading = true;
      this.loginError = false;
      try {
        await this.$axios.post(
          this.allauthPath('/account/authenticators/totp'),
          { code: this.mfaSetupCode },
          { headers: this.allauthHeaders() },
        );
        this.mfaSetupRequired = false;
        this.mfaSetupCode = '';
        this.redirectLoggedIn();
      } catch {
        this.loginError = true;
      } finally {
        this.buttonLoading = false;
      }
    },
    async addPasskey() {
      this.buttonLoading = true;
      this.loginError = false;
      try {
        const optionsResponse = await this.$axios.get(
          `${this.allauthPath('/account/authenticators/webauthn')}?passwordless`,
          { headers: this.allauthHeaders() },
        );
        const creationOptions = optionsResponse.data.data?.creation_options;
        const credential = await navigator.credentials.create({
          publicKey: parseWebAuthnCreationOptions(creationOptions),
        });
        if (!credential) throw new Error('Passkey registration was cancelled.');
        await this.$axios.post(
          this.allauthPath('/account/authenticators/webauthn'),
          {
            name: 'MemberMatters passkey',
            credential: serializeWebAuthnCreationCredential(
              credential as PublicKeyCredential,
            ),
          },
          { headers: this.allauthHeaders() },
        );
        this.mfaSetupRequired = false;
        this.finishAllauthLogin();
      } catch {
        this.loginError = true;
      } finally {
        this.buttonLoading = false;
      }
    },
    async loginWithAllauth() {
      try {
        const response = await this.$axios.post(
          this.allauthPath('/auth/login'),
          { email: this.email, password: this.password },
          { headers: this.allauthHeaders() },
        );
        this.saveAllauthTokens(response.data);
        if (response.data.meta?.is_authenticated) {
          this.finishAllauthLogin();
        } else if (!this.setMfaChallenge(response.data)) {
          this.loginError = true;
        }
      } catch (error) {
        this.saveAllauthTokens(error.response?.data);
        if (!this.setMfaChallenge(error.response?.data)) {
          if (error.response?.status === 401) {
            this.loginFailed = true;
          } else {
            this.loginError = true;
          }
          this.unverifiedEmail = false;
        }
      } finally {
        this.buttonLoading = false;
      }
    },
    async completeMfa() {
      this.loginFailed = false;
      this.loginError = false;
      this.buttonLoading = true;
      try {
        const response = await this.$axios.post(
          this.allauthPath('/auth/2fa/authenticate'),
          { code: this.mfaCode },
          { headers: this.allauthHeaders() },
        );
        this.saveAllauthTokens(response.data);
        this.mfaRequired = false;
        this.finishAllauthLogin();
      } catch (error) {
        this.loginFailed = error.response?.status === 400;
        this.loginError = !this.loginFailed;
      } finally {
        this.buttonLoading = false;
      }
    },
    async loginWithPasskey() {
      this.loginFailed = false;
      this.loginError = false;
      this.buttonLoading = true;
      const loginPath = this.mfaRequired
        ? '/auth/webauthn/authenticate'
        : '/auth/webauthn/login';
      try {
        const optionsResponse = await this.$axios.get(
          this.allauthPath(loginPath),
          { headers: this.allauthHeaders() },
        );
        this.saveAllauthTokens(optionsResponse.data);
        const requestOptions =
          optionsResponse.data.data?.request_options ||
          optionsResponse.data.data?.requestOptions;
        const credential = await navigator.credentials.get({
          publicKey: parseWebAuthnRequestOptions(requestOptions),
        });
        if (!credential)
          throw new Error('Passkey authentication was cancelled.');

        const response = await this.$axios.post(
          this.allauthPath(loginPath),
          {
            credential: serializeWebAuthnCredential(
              credential as PublicKeyCredential,
            ),
          },
          { headers: this.allauthHeaders() },
        );
        this.saveAllauthTokens(response.data);
        this.mfaRequired = false;
        this.finishAllauthLogin();
      } catch {
        this.loginError = true;
      } finally {
        this.buttonLoading = false;
      }
    },
    /**
     * This submits the password reset request so the user gets a reset link in their email.
     */
    resetPassword() {
      this.loginFailed = false;
      this.reset.success = false;
      this.reset.loading = true;

      this.$axios
        .post('/api/password/reset/', {
          email: this.reset.email,
        })
        .then((response) => {
          if (response.data.success === true) {
            this.reset.success = true;
            this.reset.disableResetSubmitButton = true;
            this.reset.failed = false;
          } else {
            this.reset.success = false;
            this.reset.failed = true;
          }
        })
        .catch((error) => {
          throw error;
        })
        .finally(() => {
          this.reset.loading = false;
        });
    },
    /**
     * This sends a request to validate the password reset token.
     * @returns {Promise<unknown>}
     */
    validatePasswordReset() {
      return new Promise<void>((resolve, reject) => {
        this.$axios
          .post('/api/password/reset/', {
            token: this.resetToken,
          })
          .then((response) => {
            if (response.data.success) {
              resolve();
            } else {
              reject();
            }
          })
          .catch((error) => {
            reject();
            throw error;
          });
      });
    },
    /**
     * This will send the user's new password and reset token to the API.
     */
    submitResetPassword() {
      this.reset.success = false;
      this.reset.loading = true;

      this.$axios
        .post('/api/password/reset/', {
          password: this.reset.password,
          token: this.resetToken,
        })
        .then((response) => {
          if (response.data.success === true) {
            this.reset.confirmed = true;
            this.reset.failed = false;
            this.reset.formDisabled = true;
            setTimeout(() => {
              // eslint-disable-next-line no-restricted-globals
              location.href = '/login';
            }, 3000);
          } else {
            this.reset.confirmed = false;
            this.reset.failed = true;
          }
        })
        .catch((error) => {
          this.reset.confirmed = false;
          this.reset.failed = true;
          throw error;
        })
        .finally(() => {
          this.reset.loading = false;
        });
    },
  },
  computed: {
    ...mapGetters('profile', ['loggedIn']),
    ...mapGetters('config', ['siteName', 'images', 'features']),
  },
});
</script>

<style scoped>
.login-card {
  max-width: 400px;
  width: 100%;
}
</style>
