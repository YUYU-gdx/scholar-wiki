import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig, loadEnv} from 'vite';

export default defineConfig(({mode}) => {
  const env = loadEnv(mode, '.', '');
  const backendPort = env.KN_GRAPH_PORT || '8013';
  const backendTarget = `http://127.0.0.1:${backendPort}`;
  return {
    base: './',
    plugins: [react(), tailwindcss()],
    define: {
      'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY),
    },
      resolve: {
        alias: {
          '@': path.resolve(__dirname, 'src'),
          '@reader': path.resolve(__dirname, 'src/components/reader'),
        },
      },
    server: {
      hmr: process.env.DISABLE_HMR !== 'true',
      proxy: {
        '/graph': { target: backendTarget, changeOrigin: true },
        '/paper': { target: backendTarget, changeOrigin: true },
        '/variable': { target: backendTarget, changeOrigin: true },
        '/chat': { target: backendTarget, changeOrigin: true },
        '/literature': { target: backendTarget, changeOrigin: true },
        '/v1': { target: backendTarget, changeOrigin: true },
        '/settings': { target: backendTarget, changeOrigin: true },
        '/api': { target: backendTarget, changeOrigin: true },
        '/healthz': { target: backendTarget, changeOrigin: true },
      },
    },
  };
});
