<template>
  <q-card class="mfa-settings-card">
    <q-card-section>
      <div class="text-h6">{{ $t('mfaSettings.title') }}</div>
      <p class="text-body2">{{ $t('mfaSettings.description') }}</p>

      <q-spinner v-if="loading" color="primary" size="2em" />

      <template v-else>
        <q-banner v-if="error" class="bg-negative text-white q-mb-md">
          {{ $t('mfaSettings.failed') }}
        </q-banner>
        <q-banner v-if="success" class="bg-positive text-white q-mb-md">
          {{ success }}
        </q-banner>

        <q-list v-if="authenticators.length" bordered separator class="q-mb-md">
          <q-item
            v-for="authenticator in authenticators"
            :key="authenticatorKey(authenticator)"
          >
            <q-item-section>
              <q-item-label>{{
                authenticatorLabel(authenticator)
              }}</q-item-label>
              <q-item-label caption>
                {{ authenticatorTypeLabel(authenticator.type) }}
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn
                v-if="authenticator.type === 'totp'"
                flat
                color="negative"
                :label="$t('mfaSettings.disableTotp')"
                :loading="actionLoading"
                @click="disableTotp"
              />
              <q-btn
                v-if="authenticator.type === 'webauthn'"
                flat
                color="negative"
                :label="$t('mfaSettings.removePasskey')"
                :loading="actionLoading"
                @click="removePasskey(authenticator.id)"
              />
            </q-item-section>
          </q-item>
        </q-list>

        <p v-else class="text-body2">{{ $t('mfaSettings.noMethods') }}</p>

        <div v-if="totpSetup" class="q-mb-md">
          <p class="text-body2">{{ $t('mfaSettings.setupDescription') }}</p>
          <q-img
            v-if="totpSetup.qrCode"
            :src="totpSetup.qrCode"
            fit="contain"
            style="max-width: 220px"
            class="q-mb-md"
          />
          <p class="text-caption">
            {{ $t('mfaSettings.setupKey') }}:
            <code>{{ totpSetup.secret }}</code>
          </p>
          <q-input
            v-model="totpSetup.code"
            filled
            autocomplete="one-time-code"
            inputmode="numeric"
            :label="$t('mfaSettings.verificationCode')"
          />
          <div class="row q-mt-sm">
            <q-space />
            <q-btn
              flat
              color="primary"
              :label="$t('button.cancel')"
              @click="cancelTotpSetup"
            />
            <q-btn
              color="primary-btn"
              :label="$t('mfaSettings.enableTotp')"
              :loading="actionLoading"
              @click="activateTotp"
            />
          </div>
        </div>

        <div v-if="recoveryCodes.length" class="q-mb-md">
          <p class="text-body2">
            {{ $t('mfaSettings.recoveryCodesDescription') }}
          </p>
          <code class="mfa-recovery-codes">{{ recoveryCodes.join('\n') }}</code>
        </div>

        <div class="row q-gutter-sm">
          <q-input
            v-model="passkeyName"
            class="col-12"
            filled
            :label="$t('mfaSettings.passkeyName')"
            :hint="$t('mfaSettings.passkeyNameHint')"
          />
          <q-btn
            outline
            color="primary"
            :label="$t('mfaSettings.addPasskey')"
            :loading="actionLoading"
            :disable="!passkeyName.trim()"
            @click="addPasskey"
          />
          <q-btn
            v-if="!hasTotp && !totpSetup"
            outline
            color="primary"
            :label="$t('mfaSettings.enableTotp')"
            :loading="actionLoading"
            @click="beginTotpSetup"
          />
          <q-btn
            outline
            color="primary"
            :label="$t('mfaSettings.generateRecoveryCodes')"
            :loading="actionLoading"
            @click="generateRecoveryCodes"
          />
        </div>
      </template>
    </q-card-section>
  </q-card>

  <q-dialog v-model="reauthenticatePrompt" persistent>
    <q-card style="max-width: 360px">
      <q-card-section>
        <div class="text-h6">{{ $t('mfaSettings.reauthenticateTitle') }}</div>
        <p class="text-body2">
          {{ $t('mfaSettings.reauthenticateDescription') }}
        </p>
        <q-input
          v-model="reauthenticatePassword"
          autofocus
          filled
          type="password"
          autocomplete="current-password"
          :label="$t('mfaSettings.reauthenticatePassword')"
          @keyup.enter="submitReauthenticate"
        />
        <q-banner
          v-if="reauthenticateError"
          class="bg-negative text-white q-mt-md"
        >
          {{ $t('mfaSettings.reauthenticateFailed') }}
        </q-banner>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn
          flat
          color="primary"
          :label="$t('button.cancel')"
          @click="cancelReauthenticate"
        />
        <q-btn
          color="primary-btn"
          :label="$t('mfaSettings.reauthenticate')"
          :loading="reauthenticating"
          @click="submitReauthenticate"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script lang="ts">
import { Platform, QDialogOptions, Dialog } from 'quasar';
import { defineComponent } from 'vue';
import QRCode from 'qrcode';

type Authenticator = {
  type: string;
  id?: number;
  name?: string;
  created_at?: number;
  unused_code_count?: number;
};

type WebAuthnCredentialDescriptorJSON = {
  id: string;
  transports?: string[];
};

type WebAuthnOptionsJSON = {
  challenge: string;
  user?: { id: string; [key: string]: unknown };
  allowCredentials?: WebAuthnCredentialDescriptorJSON[];
  allow_credentials?: WebAuthnCredentialDescriptorJSON[];
  excludeCredentials?: WebAuthnCredentialDescriptorJSON[];
  exclude_credentials?: WebAuthnCredentialDescriptorJSON[];
  [key: string]: unknown;
};

function decodeBase64Url(value: string): ArrayBuffer {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4);
  return Uint8Array.from(atob(padded), (char) => char.charCodeAt(0)).buffer;
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

function parseCreationOptions(
  options: WebAuthnOptionsJSON & { publicKey?: WebAuthnOptionsJSON },
): PublicKeyCredentialCreationOptions {
  const publicKey = options.publicKey || options;
  const parsed = { ...publicKey };
  parsed.challenge = decodeBase64Url(parsed.challenge);
  if (parsed.user) {
    parsed.user = {
      ...parsed.user,
      id: decodeBase64Url(parsed.user.id),
    } as unknown as { id: string; [key: string]: unknown };
  }
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

function serializeCreationCredential(
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
  name: 'MfaSettingsCard',
  data() {
    return {
      loading: true,
      actionLoading: false,
      error: false,
      success: '',
      authenticators: [] as Authenticator[],
      recoveryCodes: [] as string[],
      passkeyName: '',
      reauthenticatePrompt: false,
      reauthenticatePassword: '',
      reauthenticateError: false,
      reauthenticating: false,
      pendingAction: null as (() => Promise<void>) | null,
      totpSetup: null as {
        secret: string;
        qrCode: string;
        code: string;
      } | null,
    };
  },
  computed: {
    client(): string {
      return Platform.is.capacitor ? 'app' : 'browser';
    },
    hasTotp(): boolean {
      return this.authenticators.some(
        (authenticator) => authenticator.type === 'totp',
      );
    },
  },
  async mounted() {
    await this.loadAuthenticators();
  },
  methods: {
    path(path: string): string {
      return `/_allauth/${this.client}/v1${path}`;
    },
    headers() {
      return { Accept: 'application/json' };
    },
    authenticatorKey(authenticator: Authenticator): string {
      return `${authenticator.type}-${authenticator.id || authenticator.created_at}`;
    },
    authenticatorLabel(authenticator: Authenticator): string {
      return (
        authenticator.name || this.authenticatorTypeLabel(authenticator.type)
      );
    },
    authenticatorTypeLabel(type: string): string {
      const labels: Record<string, string> = {
        totp: this.$t('mfaSettings.totp'),
        webauthn: this.$t('mfaSettings.passkey'),
        recovery_codes: this.$t('mfaSettings.recoveryCodes'),
      };
      return labels[type] || type;
    },
    async loadAuthenticators() {
      this.loading = true;
      this.error = false;
      try {
        const response = await this.$axios.get(
          this.path('/account/authenticators'),
          { headers: this.headers() },
        );
        this.authenticators = response.data.data || [];
      } catch {
        this.error = true;
      } finally {
        this.loading = false;
      }
    },
    async beginTotpSetup() {
      this.actionLoading = true;
      this.error = false;
      try {
        const response = await this.$axios.get(
          this.path('/account/authenticators/totp'),
          { headers: this.headers() },
        );
        this.setTotpSetup(response.data);
      } catch (error) {
        if (error.response?.status === 404) {
          this.setTotpSetup(error.response.data);
        } else {
          this.error = true;
        }
      } finally {
        this.actionLoading = false;
      }
    },
    async setTotpSetup(data) {
      const meta = data?.meta || {};
      if (!meta.secret || !meta.totp_url) {
        this.error = true;
        return;
      }
      this.totpSetup = {
        secret: meta.secret,
        qrCode: await QRCode.toDataURL(meta.totp_url),
        code: '',
      };
    },
    cancelTotpSetup() {
      this.totpSetup = null;
    },
    async activateTotp() {
      if (!this.totpSetup?.code) return;
      await this.runAction(async () => {
        await this.$axios.post(
          this.path('/account/authenticators/totp'),
          { code: this.totpSetup.code },
          { headers: this.headers() },
        );
        this.totpSetup = null;
        this.success = this.$t('mfaSettings.saved');
        await this.loadAuthenticators();
      });
    },
    async addPasskey() {
      await this.runAction(async () => {
        const optionsResponse = await this.$axios.get(
          `${this.path('/account/authenticators/webauthn')}?passwordless`,
          { headers: this.headers() },
        );
        const creationOptions = optionsResponse.data.data?.creation_options;
        const credential = await navigator.credentials.create({
          publicKey: parseCreationOptions(creationOptions),
        });
        if (!credential) throw new Error('Passkey registration was cancelled.');
        await this.$axios.post(
          this.path('/account/authenticators/webauthn'),
          {
            name: this.passkeyName.trim(),
            passwordless: true,
            credential: serializeCreationCredential(
              credential as PublicKeyCredential,
            ),
          },
          { headers: this.headers() },
        );
        this.passkeyName = '';
        this.success = this.$t('mfaSettings.saved');
        await this.loadAuthenticators();
      });
    },
    async generateRecoveryCodes() {
      await this.runAction(async () => {
        const response = await this.$axios.post(
          this.path('/account/authenticators/recovery-codes'),
          {},
          { headers: this.headers() },
        );
        this.recoveryCodes = response.data.data?.unused_codes || [];
        this.success = this.$t('mfaSettings.saved');
        await this.loadAuthenticators();
      });
    },
    async disableTotp() {
      const options: QDialogOptions = {
        title: this.$t('mfaSettings.disableTotp'),
        message: this.$t('mfaSettings.confirmDisable'),
        cancel: true,
        persistent: true,
      };
      Dialog.create(options).onOk(() => this.removeTotp());
    },
    async removeTotp() {
      await this.runAction(async () => {
        await this.$axios.delete(this.path('/account/authenticators/totp'), {
          headers: this.headers(),
        });
        this.success = this.$t('mfaSettings.saved');
        await this.loadAuthenticators();
      });
    },
    async removePasskey(id?: number) {
      if (!id) return;
      await this.runAction(async () => {
        await this.$axios.delete(
          this.path('/account/authenticators/webauthn'),
          {
            data: { authenticators: [id] },
            headers: this.headers(),
          },
        );
        this.success = this.$t('mfaSettings.saved');
        await this.loadAuthenticators();
      });
    },
    isReauthenticationRequired(error): boolean {
      return (
        error.response?.status === 401 &&
        error.response.data?.data?.flows?.some(
          (flow) => flow.id === 'reauthenticate',
        )
      );
    },
    cancelReauthenticate() {
      this.reauthenticatePrompt = false;
      this.reauthenticatePassword = '';
      this.reauthenticateError = false;
      this.pendingAction = null;
    },
    async submitReauthenticate() {
      if (!this.reauthenticatePassword || !this.pendingAction) return;
      this.reauthenticating = true;
      this.reauthenticateError = false;
      try {
        await this.$axios.post(
          this.path('/auth/reauthenticate'),
          { password: this.reauthenticatePassword },
          { headers: this.headers() },
        );
        const action = this.pendingAction;
        this.cancelReauthenticate();
        if (!action) return;
        await action();
      } catch {
        this.reauthenticateError = true;
      } finally {
        this.reauthenticating = false;
      }
    },
    async runAction(action: () => Promise<void>) {
      this.actionLoading = true;
      this.error = false;
      this.success = '';
      try {
        await action();
      } catch (error) {
        if (this.isReauthenticationRequired(error)) {
          this.pendingAction = action;
          this.reauthenticatePrompt = true;
          this.reauthenticateError = false;
        } else {
          this.error = true;
        }
      } finally {
        this.actionLoading = false;
      }
    },
  },
});
</script>

<style scoped>
.mfa-settings-card {
  width: 600px;
  max-width: 90vw;
}

.mfa-recovery-codes {
  display: block;
  white-space: pre-wrap;
  padding: 0.75rem;
  background: var(--q-color-grey-2);
}
</style>
