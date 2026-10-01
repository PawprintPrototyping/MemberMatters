import { boot } from 'quasar/wrappers';
import { i18n } from '../services/i18n';

export default boot(({ app }) => {
  // Set i18n instance on app
  app.use(i18n);
});
