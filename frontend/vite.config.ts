import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon.svg'],
      manifest: {
        name: 'UPI Safety Check',
        short_name: 'UPI Check',
        description: 'Check a UPI payment against your own bank record in seconds. Works offline. Nothing is uploaded.',
        theme_color: '#f5f5f7',
        background_color: '#f5f5f7',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
        // Android share target: long-press an SMS -> Share -> UPI Check opens the message check
        share_target: { action: '/messages', method: 'GET', params: { title: 'title', text: 'text' } },
      },
      workbox: {
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api/],
      },
    }),
  ],
  server: { port: 5173, proxy: { '/api': process.env.API_TARGET ?? 'http://127.0.0.1:8010' } },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})
