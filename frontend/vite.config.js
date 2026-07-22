import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

const canopyRoot = '../canopyDesign/src'
const resolveApp = (p) => fileURLToPath(new URL(p, import.meta.url))

// Canopy (@bristlecone/canopy) is consumed straight from its TypeScript source
// in the in-repo "canopyDesign" folder — Vite/esbuild
// transpiles the .ts/.tsx on the fly. Because that source lives outside this
// app's root and has no node_modules of its own, its bare imports (react, radix,
// cva, clsx, …) can't be resolved by Node's importer-relative algorithm. We
// alias each of Canopy's external deps to THIS app's installed copy, which also
// forces a single react/react-dom instance (avoids duplicate-React hook errors).
const canopyDeps = [
  'react',
  'react-dom',
  '@radix-ui/react-slot',
  '@radix-ui/react-tooltip',
  '@radix-ui/react-dropdown-menu',
  'class-variance-authority',
  'clsx',
  'tailwind-merge',
  'lucide-react',
]

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    dedupe: ['react', 'react-dom'],
    alias: [
      // /theme subpath must be listed before the exact-match bare specifier.
      { find: '@bristlecone/canopy/theme', replacement: resolveApp(`${canopyRoot}/theme/index.ts`) },
      { find: /^@bristlecone\/canopy$/, replacement: resolveApp(`${canopyRoot}/index.ts`) },
      // Canopy's external deps -> this app's node_modules.
      ...canopyDeps.map((dep) => ({
        find: new RegExp(`^${dep.replace(/[/\\]/g, '\\$&')}$`),
        replacement: resolveApp(`./node_modules/${dep}`),
      })),
    ],
  },
})
