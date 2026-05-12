import { defineConfig } from '@playwright/test';

const port = Number(process.env.PLAYWRIGHT_PORT ?? '3100');

export default defineConfig({
  testDir: './e2e',
  webServer: {
    command: `npx vite --host 127.0.0.1 --port ${port} --strictPort`,
    port,
    reuseExistingServer: false,
  },
  use: { baseURL: `http://127.0.0.1:${port}` },
});
