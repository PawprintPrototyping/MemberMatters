import { boot } from 'quasar/wrappers';
import { createI18n } from 'vue-i18n';

import messages from '../i18n';
import numberFormats from '../i18n/numberFormats';

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: navigator.language,
  fallbackLocale: 'en-AU',
  numberFormats,
  messages,
  fallbackWarn: false,
  missingWarn: false,
});

export default boot(({ app }) => {
  // Set i18n instance on app
  app.use(i18n);
});
