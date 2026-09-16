export {};

declare global {
  interface Window {
    memberMatters: {
      getKioskIdentity(): Promise<string>;
    };
  }
}
