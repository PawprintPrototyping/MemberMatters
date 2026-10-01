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
