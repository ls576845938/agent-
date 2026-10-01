import { defineConfig } from '@playwright/test';

const port = 3000;

export default defineConfig({
  testDir: './e2e',
  webServer: {
    command: 'node ./scripts/start-current-main.mjs',
    port,
    reuseExistingServer: true,
  },
  use: { baseURL: `http://127.0.0.1:${port}` },
});
