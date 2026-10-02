import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    port: 5173,
    proxy: {
      // The dev server talks to the API container, mock or live.
      '/api': { target: process.env.MOH_API_URL ?? 'http://localhost:8000', changeOrigin: true },
    },
  },
});
