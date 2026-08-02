const path = require('path');
const fs = require('fs');

// Auto-instala o Chrome do Puppeteer caso não exista.
// Procura pelo executável real (chrome.exe / chrome / Chromium), não apenas
// por uma pasta não-vazia: um antivírus pode ter removido/colocado em
// quarentena o binário do Chrome sem apagar a pasta inteira, o que faria essa
// checagem "passar" indefinidamente enquanto o servidor nunca inicia de fato.

function findChromeExecutable(dir, depth) {
  if (depth > 6) return null;
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (e) {
    return null;
  }
  // First pass: search strictly for full Chrome / Chromium executable
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      const found = findChromeExecutable(full, depth + 1);
      if (found) return found;
    } else if (
      entry.name === 'chrome.exe' ||
      entry.name === 'chrome' ||
      entry.name === 'Chromium'
    ) {
      return full;
    }
  }
  return null;
}

const puppeteerCacheDir = path.join(__dirname, '.cache', 'puppeteer');
const nodeModulesCacheDir = path.join(__dirname, 'node_modules', '.cache', 'puppeteer');
const directChromeDir = path.join(__dirname, 'chrome');
const directHeadlessShellDir = path.join(__dirname, 'chrome-headless-shell');

let chromeExecutable = fs.existsSync(puppeteerCacheDir) ? findChromeExecutable(puppeteerCacheDir, 0) : null;
if (!chromeExecutable && fs.existsSync(nodeModulesCacheDir)) {
  chromeExecutable = findChromeExecutable(nodeModulesCacheDir, 0);
}
if (!chromeExecutable && fs.existsSync(directChromeDir)) {
  chromeExecutable = findChromeExecutable(directChromeDir, 0);
}
if (!chromeExecutable && fs.existsSync(directHeadlessShellDir)) {
  chromeExecutable = findChromeExecutable(directHeadlessShellDir, 0);
}
if (!chromeExecutable) {
  chromeExecutable = findChromeExecutable(__dirname, 0);
}
const hasChrome = !!chromeExecutable;
console.log(`[WinZapp Debug] Chrome executable resolution: ${chromeExecutable ? chromeExecutable : 'NOT FOUND (will use default Puppeteer)'}`);
console.log(`[WinZapp Debug] Platform: ${process.platform}, Node version: ${process.version}`);

if (!hasChrome) {
  console.log('[chrome-install] Navegador Chrome do Puppeteer não encontrado. Instalando automaticamente (isso pode levar alguns minutos)...');
  try {
    // Limpa pastas corrompidas de downloads anteriores incompletos do Chrome
    const cleanCorruptedCache = (baseDir) => {
      if (!fs.existsSync(baseDir)) return;
      try {
        const subdirs = fs.readdirSync(baseDir, { withFileTypes: true });
        for (const sub of subdirs) {
          const fullPath = path.join(baseDir, sub.name);
          if (sub.isDirectory() && !findChromeExecutable(fullPath, 0)) {
            console.log(`[chrome-install] Removendo diretório de Chrome corrompido/incompleto: ${fullPath}`);
            fs.rmSync(fullPath, { recursive: true, force: true });
          }
        }
      } catch (e) {}
    };

    cleanCorruptedCache(puppeteerCacheDir);
    cleanCorruptedCache(directChromeDir);
    cleanCorruptedCache(directHeadlessShellDir);

    const { execSync } = require('child_process');
    const nodeDir = path.dirname(process.execPath);
    const env = { 
      ...process.env, 
      PUPPETEER_CACHE_DIR: puppeteerCacheDir 
    };
    if (process.platform === 'win32') {
      env.Path = `${nodeDir};${env.Path || ''};${env.PATH || ''}`;
    } else {
      env.PATH = `${nodeDir}:${env.PATH || ''}`;
    }
    
    try {
      execSync('npx --yes @puppeteer/browsers install chrome@stable', {
        cwd: __dirname,
        stdio: 'inherit',
        env: env
      });
      console.log('[chrome-install] Navegador Chrome do Puppeteer instalado com sucesso!');
    } catch (primaryErr) {
      console.warn('[chrome-install] Falha ao instalar chrome@stable — tentando fallback com chrome-headless-shell...');
      execSync('npx --yes @puppeteer/browsers install chrome-headless-shell', {
        cwd: __dirname,
        stdio: 'inherit',
        env: env
      });
      console.log('[chrome-install] Fallback para chrome-headless-shell concluído com sucesso!');
    }
  } catch (err) {
    console.error('[chrome-install] Falha ao instalar o Chrome automaticamente:', err && err.message ? err.message : err);
  }
}

// Carrega a configuração padrão compilada
const distPath = path.join(__dirname, 'dist');
let configDefault = {};
try {
  if (fs.existsSync(path.join(distPath, 'config.js'))) {
    configDefault = require(path.join(distPath, 'config')).default || require(path.join(distPath, 'config'));
  } else if (fs.existsSync(path.join(distPath, 'src', 'config.js'))) {
    configDefault = require(path.join(distPath, 'src', 'config')).default || require(path.join(distPath, 'src', 'config'));
  }
} catch (err) {
  console.warn('[WinZapp] Aviso ao carregar dist/config:', err && err.message ? err.message : err);
}

let initServer;
try {
  const indexMod = require(path.join(distPath, 'index'));
  initServer = indexMod.initServer || indexMod.default || indexMod;
} catch (err) {
  try {
    const serverMod = require(path.join(distPath, 'server'));
    initServer = typeof serverMod.initServer === 'function' ? serverMod.initServer : (typeof serverMod === 'function' ? serverMod : null);
  } catch (e) {
    console.warn('[WinZapp] Falling back to executing dist/server.js directly');
  }
}

// Carrega as configurações personalizadas de config.json
let customConfig = {};
const customConfigPath = path.join(__dirname, 'config.json');
if (fs.existsSync(customConfigPath)) {
  try {
    customConfig = JSON.parse(fs.readFileSync(customConfigPath, 'utf8'));
  } catch (e) {
    console.error('Erro ao ler config.json:', e);
  }
}

// Sobrescreve com variáveis de ambiente do processo se fornecidas
if (process.env.PORT) {
  customConfig.port = process.env.PORT;
}
if (process.env.AUTHENTICATION_API_KEY) {
  customConfig.secretKey = process.env.AUTHENTICATION_API_KEY;
}

// Optimized browser arguments to limit Puppeteer/Chromium CPU and Memory usage
//
// NOTE on what was deliberately left OUT of this list: an earlier version
// included '--js-flags="--max-old-space-size=350"', capping the WhatsApp
// Web renderer's own V8 JS heap at 350MB. Every other flag here reduces
// memory by disabling an optional feature (cache, GPU, extensions, ...) —
// a safe degradation. --max-old-space-size is categorically different: it's
// a hard ceiling, and WhatsApp Web's own JS heap (message store, media
// metadata, many open/cached chats — exactly the "muitas conversas
// chegando" scenario) can legitimately need more than 350MB under real
// load. Hitting the ceiling doesn't slow anything down gracefully — V8
// throws "JavaScript heap out of memory" and the renderer process crashes
// outright, which is what a WhatsApp Web page dying and needing WPPConnect
// to resync would look like from WinZapp's side. Removed so V8 falls back
// to its own default (auto-scaled off available system memory, normally
// well over 1GB) — a real, if higher, ceiling instead of an artificial low
// one that trades a memory-usage improvement for occasional hard crashes.
const optimizedBrowserArgs = [
  '--disable-renderer-accessibility',
  '--disable-web-security',
  '--no-sandbox',
  '--disable-setuid-sandbox',
  '--aggressive-cache-discard',
  '--disable-cache',
  '--disable-application-cache',
  '--disable-offline-load-stale-cache',
  '--disk-cache-size=1',
  '--media-cache-size=1',
  '--disable-background-networking',
  '--disable-default-apps',
  '--disable-extensions',
  '--disable-sync',
  '--disable-dev-shm-usage',
  '--disable-gpu',
  '--disable-software-rasterizer',
  '--disable-translate',
  '--hide-scrollbars',
  '--metrics-recording-only',
  '--mute-audio',
  '--no-first-run',
  '--safebrowsing-disable-auto-update',
  '--ignore-certificate-errors',
  '--ignore-ssl-errors',
  '--ignore-certificate-errors-spki-list',
  '--no-zygote',
  '--disable-shared-workers',
  '--disable-3d-apis',
  '--disable-webgl',
  '--disable-notifications',
  '--disable-component-update',
  '--disable-speech-api',
  '--disable-voice-input',
  '--disable-renderer-backgrounding',
  '--disable-backgrounding-occluded-windows',
  '--disable-breakpad',
  '--password-store=basic',
  '--use-mock-keychain',
  '--no-pings',
  '--disable-client-side-phishing-detection',
  '--renderer-process-limit=2',
  '--disable-site-isolation-trials',
  '--disable-features=OptimizationGuideOnDeviceModel,PromptAPIForGeminiNano,AISummarization,HelpMeWrite,OptimizationGuide,OptimizationHints,OptimizationTargetPrediction,IsolateOrigins,site-per-process',
  '--js-flags=--max-old-space-size=512 --optimize-for-size',
];

// WPPConnect pins the WhatsApp Web version (default '2.3000.10305x') by serving
// that build's HTML from the @wppconnect/wa-version package. When the pinned
// version is not in that package it does NOT fail — it logs
//   "Version not available for <v>, using latest as fallback"
// and lets WhatsApp Web serve its newest build, which can be more recent than
// the bundled wa-js supports. That is how sending to individual contacts started
// failing silently: every usync query hung, WhatsApp Web flagged the message
// isSendFailure with ack 0, and the REST call still answered 200. Groups kept
// working because they use sender keys and need no usync.
//
// Rather than hardcoding a version — which rots as soon as WhatsApp removes the
// old build's assets (HTTP 410) — ask wa-version itself for the newest build it
// can serve. `npm update @wppconnect/wa-version` is then enough to keep up with
// WhatsApp Web.
//
// wa-version is resolved through WPPConnect's own dependency tree, never as a
// direct dependency of ours. WPPConnect's setWhatsappVersion() serves the HTML
// from the copy *it* resolved, so reading any other copy risks picking a build
// that its catalogue does not have — which lands right back in the silent
// "using latest as fallback" path. Declaring our own `@wppconnect/wa-version`
// range would do exactly that the moment the two ranges stop overlapping (say
// WPPConnect moves to ^2 while ours still says ^1): npm then installs two
// copies, and the version we pin would be looked up in the wrong one.
function requireWaVersion() {
  const path = require('path');
  try {
    return require('@wppconnect-team/wa-version');
  } catch (e1) {
    try {
      return require('@wppconnect/wa-version');
    } catch (e2) {
      try {
        const wppEntry = require.resolve('@wppconnect-team/wppconnect/package.json');
        return require(require.resolve('@wppconnect-team/wa-version', {
          paths: [path.dirname(wppEntry)],
        }));
      } catch (e3) {
        return null;
      }
    }
  }
}

function resolveWhatsappVersion() {
  try {
    const waVersionRaw = requireWaVersion();
    if (!waVersionRaw) return undefined;
    const waVersion = (typeof waVersionRaw.getAvailableVersions === 'function')
      ? waVersionRaw
      : (waVersionRaw.default && typeof waVersionRaw.default.getAvailableVersions === 'function' ? waVersionRaw.default : null);
    if (!waVersion) return undefined;

    const available = waVersion.getAvailableVersions();
    if (!Array.isArray(available) || available.length === 0) return undefined;
    
    // Prefer stable releases over alpha builds if available
    const stables = available.filter(v => typeof v === 'string' && !v.includes('-alpha'));
    const newest = stables.length > 0 ? stables[stables.length - 1] : available[available.length - 1];

    console.log(`[WinZapp] Pinning WhatsApp Web to ${newest} (of ${available.length} available)`);
    return newest;
  } catch (e) {
    console.error(
      '[WinZapp] Could not resolve a WhatsApp Web version via @wppconnect/wa-version ' +
      `(${e && e.message}). Continuing unpinned — WhatsApp Web will serve its newest ` +
      'build, which the bundled wa-js may not support. Run: npm update @wppconnect/wa-version'
    );
    return undefined;
  }
}

const whatsappVersion = resolveWhatsappVersion();

// Mesclagem simples recursiva para webhooks e outros objetos aninhados
const finalConfig = {
  ...configDefault,
  ...customConfig,
  webhook: {
    ...configDefault.webhook,
    ...customConfig.webhook
  },
  log: {
    level: 'silly',
    logger: ['console', 'file'],
    ...(configDefault.log || {}),
    ...(customConfig.log || {})
  },
  createOptions: {
    ...(configDefault.createOptions || {}),
    ...(customConfig.createOptions || {}),
    browserArgs: optimizedBrowserArgs,
    disableSpins: true,  // Disables command line spinners (saves CPU)
    updatesLog: false,   // Disables checking for updates on startup
    // undefined => WPPConnect pins nothing and uses the live build (see
    // resolveWhatsappVersion above). Set explicitly here because WPPConnect's
    // own default points at a version wa-version no longer ships.
    whatsappVersion,
    ...(chromeExecutable ? { executablePath: chromeExecutable } : {}),
    puppeteerOptions: {
      protocolTimeout: 120000,
      ...(chromeExecutable ? { executablePath: chromeExecutable } : {}),
      ...((configDefault.createOptions && configDefault.createOptions.puppeteerOptions) || {}),
      ...((customConfig.createOptions && customConfig.createOptions.puppeteerOptions) || {})
    }
  }
};

// Inicializa o servidor Express na porta 6300
console.log('[WinZapp] Starting WPPConnect Server via dist/index.js...');
try {
  const distIndex = require(path.join(distPath, 'index'));
  if (typeof distIndex.initServer === 'function') {
    distIndex.initServer(finalConfig);
  } else {
    console.error('[WinZapp] initServer function not found in dist/index.js');
  }
} catch (e) {
  console.error('[WinZapp] Error starting server module:', e);
}
