/**
 * Build script for @analytics/browser SDK.
 * Compiles ESM, CJS, and minified standalone browser IIFE bundles.
 */

const { build } = require('esbuild');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

async function runBuild() {
  const distDir = path.join(__dirname, 'dist');
  if (!fs.existsSync(distDir)) {
    fs.mkdirSync(distDir, { recursive: true });
  }

  console.log('Building TypeScript types...');
  try {
    execSync('npx tsc --emitDeclarationOnly', { cwd: __dirname, stdio: 'inherit' });
  } catch (err) {
    console.error('TypeScript declaration build failed', err);
    process.exit(1);
  }

  console.log('Bundling ESM, CJS, and IIFE minified bundles...');

  // 1. ESM bundle
  await build({
    entryPoints: [path.join(__dirname, 'src/index.ts')],
    outfile: path.join(distDir, 'index.mjs'),
    bundle: true,
    format: 'esm',
    target: 'es2020',
    sourcemap: false,
    minify: true,
  });

  // 2. CJS bundle
  await build({
    entryPoints: [path.join(__dirname, 'src/index.ts')],
    outfile: path.join(distDir, 'index.js'),
    bundle: true,
    format: 'cjs',
    target: 'es2020',
    sourcemap: false,
    minify: true,
  });

  // 3. Standalone Browser IIFE bundle (for direct <script> tag inclusion)
  const iifeOut = path.join(distDir, 'analytics.min.js');
  await build({
    entryPoints: [path.join(__dirname, 'src/index.ts')],
    outfile: iifeOut,
    bundle: true,
    format: 'iife',
    globalName: 'AnalyticsSDK',
    target: 'es2020',
    sourcemap: false,
    minify: true,
  });

  const stats = fs.statSync(iifeOut);
  console.log(`Build complete! Standalone bundle size: ${(stats.size / 1024).toFixed(2)} KB (Uncompressed). Target < 5KB gzipped.`);
}

runBuild().catch((err) => {
  console.error(err);
  process.exit(1);
});
