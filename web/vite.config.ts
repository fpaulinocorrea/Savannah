import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// While developing (npm run dev), screens on :5173 talk to the server on :8800.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8800' } },
})
