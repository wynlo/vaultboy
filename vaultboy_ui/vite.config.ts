import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts: ['.ts.net', 'localhost', '127.0.0.1'],
    watch: {
      usePolling: true,
      interval: 100,
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:4567',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../vaultboy_app/web',
    emptyOutDir: true,
  },
});
