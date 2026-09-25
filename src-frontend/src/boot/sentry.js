import { boot } from 'quasar/wrappers';
import { configureSentry } from '../services/sentry';

export default boot(({ app, router }) => {
  configureSentry(app, router);
});
