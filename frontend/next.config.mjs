/** @type {import('next').NextConfig} */

/*
 * Deliberate differences from the v0 export this design came from:
 *
 *   - `typescript.ignoreBuildErrors` is NOT set. The v0 project suppressed
 *     type errors at build time; for a UI whose correctness rules are
 *     expressed in the type system (a position that may be absent, a
 *     confidence that may be unknown) that suppression would defeat the
 *     point. The build must fail on a real type error.
 *   - No @vercel/analytics. This is a scientific tool run locally and in
 *     private deployments; it does not beacon to a third party.
 */
const nextConfig = {
  images: {
    unoptimized: true,
  },
}

export default nextConfig
