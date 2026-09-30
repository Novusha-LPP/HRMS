import { readFileSync } from 'node:fs'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The product version lives in backend/pyproject.toml and this package.json, kept in step
// by release-please. The release build passes GIT_SHA; a local build says "dev".
const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'))

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(version),
    __GIT_SHA__: JSON.stringify((process.env.GIT_SHA ?? 'dev').slice(0, 7)),
  },
  server: {
    allowedHosts: ['testinghrms.alvision.in'],
    cors: true,
  },
})
