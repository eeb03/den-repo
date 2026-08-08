import coreWebVitals from 'eslint-config-next/core-web-vitals'
import typescript from 'eslint-config-next/typescript'

/**
 * Flat config. `eslint-config-next` ships native flat configs from v16, so
 * no `FlatCompat` shim is needed (and the shim in fact fails against it).
 */
const eslintConfig = [
  ...coreWebVitals,
  ...typescript,
  {
    ignores: ['.next/**', 'node_modules/**', 'out/**', 'next-env.d.ts'],
  },
]

export default eslintConfig
