import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { compileTemplate, parse } from '@vue/compiler-sfc';
import { createSSRApp, h } from 'vue';
import { renderToString } from '@vue/server-renderer';

const frontendDirectory = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '..',
);
const membershipPlanPath = resolve(
  frontendDirectory,
  'src/pages/MembershipPlan.vue',
);

const componentNames = [
  'q-page',
  'q-spinner',
  'q-banner',
  'select-tier',
  'signup-required-steps',
  'membership-state-banner',
  'selected-tier',
  'q-icon',
  'q-btn',
  'member-bucks-manage-billing',
  'q-card',
  'q-list',
  'q-item',
  'q-item-section',
  'q-item-label',
];

function componentStub(name) {
  return {
    name,
    setup(_, { slots }) {
      return () => h('div', { 'data-component': name }, slots.default?.());
    },
  };
}

async function getMembershipPlanRenderer() {
  const componentSource = await readFile(membershipPlanPath, 'utf8');
  const { descriptor, errors: parseErrors } = parse(componentSource, {
    filename: membershipPlanPath,
  });
  assert.deepEqual(parseErrors, []);

  const { code, errors: compileErrors } = compileTemplate({
    filename: membershipPlanPath,
    id: 'membership-plan',
    source: descriptor.template.content,
  });
  assert.deepEqual(compileErrors, []);

  const vueImport = code.match(
    /import\s+\{([\s\S]*?)\}\s+from\s+['"]vue['"]\s*;?/,
  );
  assert.ok(vueImport, 'compiled template must import Vue helpers');

  const helpers = vueImport[1].replaceAll(' as ', ': ');
  const executableCode = code
    .replace(vueImport[0], `const {${helpers}} = Vue;`)
    .replace('export function render', 'function render');

  return new Function('Vue', `${executableCode}\nreturn render;`)(
    await import('vue'),
  );
}

async function renderMembershipPlan(context) {
  const render = await getMembershipPlanRenderer();
  const components = Object.fromEntries(
    componentNames.map((name) => [name, componentStub(name)]),
  );
  const app = createSSRApp({
    components,
    render() {
      return render(context, []);
    },
  });

  return renderToString(app);
}

const managedProfile = {
  profileLoaded: true,
  signupStage: 'managed',
  currentTier: null,
  subscriptionStatus: 'inactive',
  subscriptionInfo: {},
  subscriptionExpected: false,
  loadingSubscription: false,
  subscriptionUnavailable: false,
  cardExists: true,
  billingMethod: 'card',
  features: { enableNewSubscriptions: true },
  $t: (key) => key,
};

test('active profiles without a membership plan use the plan selector', async (t) => {
  for (const membershipPlan of [null, undefined]) {
    await t.test(`membershipPlan is ${String(membershipPlan)}`, async () => {
      const html = await renderMembershipPlan({
        ...managedProfile,
        membershipPlan,
      });

      assert.match(html, /data-component="select-tier"/);
      assert.doesNotMatch(html, /data-component="selected-tier"/);
      assert.doesNotMatch(html, /data-component="q-btn"/);
    });
  }
});

test('profiles with complete membership data retain the managed plan view', async () => {
  const html = await renderMembershipPlan({
    ...managedProfile,
    membershipPlan: { id: 1, name: 'Monthly' },
    currentTier: { id: 1, name: 'Standard' },
    subscriptionStatus: 'cancelling',
  });

  assert.match(html, /data-component="selected-tier"/);
  assert.doesNotMatch(html, /data-component="select-tier"/);
});
