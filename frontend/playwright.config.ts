import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  webServer: {
    command: 'npx vite --port 3000',
    port: 3000,
    reuseExistingServer: true,
  },
  use: { baseURL: 'http://localhost:3000' },
});
