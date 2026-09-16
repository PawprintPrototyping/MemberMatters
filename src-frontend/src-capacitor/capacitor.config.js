const { defineCapacitorConfig } = require('@quasar/app-vite/capacitor');

module.exports = defineCapacitorConfig({
  appId: 'org.membermatters.app',
  appName: 'MemberMatters',
  webDir: 'www',
  server: {
    iosScheme: 'ionic',
    androidScheme: 'ionic',
  },
  plugins: {
    SplashScreen: {
      launchAutoHide: false,
    },
  },
});
