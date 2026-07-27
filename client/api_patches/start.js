const path = require('path');
const fs = require('fs');

// Auto-instala o Chrome do Puppeteer caso não exista.
// Procura pelo executável real (chrome.exe / chrome / Chromium), não apenas
// por uma pasta não-vazia: um antivírus pode ter removido/colocado em
// quarentena o binário do Chrome sem apagar a pasta inteira, o que faria essa
// checagem "passar" indefinidamente enquanto o servidor nunca inicia de fato.
const puppeteerCacheDir = path.join(__dirname, '.cache', 'puppeteer');

function findChromeExecutable(dir, depth) {
  if (depth > 6) return null;
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (e) {
    return null;
  }
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

const chromeExecutable = fs.existsSync(puppeteerCacheDir)
  ? findChromeExecutable(puppeteerCacheDir, 0)
  : null;
const hasChrome = !!chromeExecutable;

if (!hasChrome) {
  console.log('[chrome-install] Navegador Chrome do Puppeteer não encontrado. Instalando automaticamente (isso pode levar alguns minutos)...');
  try {
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
    execSync('npx puppeteer browsers install chrome', {
      cwd: __dirname,
      stdio: 'inherit',
      env: env
    });
    console.log('[chrome-install] Navegador Chrome do Puppeteer instalado com sucesso!');
  } catch (err) {
    console.error('[chrome-install] Falha ao instalar o Chrome automaticamente:', err);
  }
}

// Carrega a configuração padrão compilada
const distPath = path.join(__dirname, 'dist');
const configDefault = require(path.join(distPath, 'config')).default;
const { initServer } = require(path.join(distPath, 'index'));

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
  '--aggressive-cache-discard',
  '--disable-cache',
  '--disable-application-cache',
  '--disable-offline-load-stale-cache',
  '--disk-cache-size=0',
  '--disable-background-networking',
  '--disable-default-apps',
  '--disable-extensions',
  '--disable-sync',
  '--disable-dev-shm-usage',
  '--disable-gpu',
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
  '--disable-features=OptimizationGuideOnDeviceModel,PromptAPIForGeminiNano,AISummarization,HelpMeWrite,OptimizationGuide,OptimizationHints,OptimizationTargetPrediction',
  '--disable-software-rasterizer',
  '--disable-ipc-flooding-protection',
  '--disable-breakpad',
  '--password-store=basic',
  '--use-mock-keychain',
  '--no-pings',
  '--disable-client-side-phishing-detection',
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
    const wppEntry = require.resolve('@wppconnect-team/wppconnect/package.json');
    return require(require.resolve('@wppconnect/wa-version', {
      paths: [path.dirname(wppEntry)],
    }));
  } catch (e) {
    // Hoisted layout / older npm: fall back to plain resolution.
    return require('@wppconnect/wa-version');
  }
}

function resolveWhatsappVersion() {
  try {
    const waVersion = requireWaVersion();
    const available = waVersion.getAvailableVersions();
    if (!Array.isArray(available) || available.length === 0) return undefined;
    const newest = available[available.length - 1];
    // getPageContent throws when the version cannot be served, so only pin what
    // is known to work: no pin at all beats silently landing in the fallback.
    waVersion.getPageContent(newest);
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
    ...configDefault.log,
    ...customConfig.log
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
  }
};

// Inicializa o servidor
initServer(finalConfig);
