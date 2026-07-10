const path = require('path');
const fs = require('fs');

// Auto-instala o Chrome do Puppeteer caso não exista
const puppeteerCacheDir = path.join(__dirname, '.cache', 'puppeteer');
let hasChrome = false;
if (fs.existsSync(puppeteerCacheDir)) {
  try {
    const files = fs.readdirSync(puppeteerCacheDir);
    if (files.length > 0) {
      hasChrome = true;
    }
  } catch (e) {
    // ignore
  }
}

if (!hasChrome) {
  console.log('Navegador Chrome do Puppeteer não encontrado. Instalando automaticamente...');
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
    console.log('Navegador Chrome do Puppeteer instalado com sucesso!');
  } catch (err) {
    console.error('Falha ao instalar o Chrome automaticamente:', err);
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
  '--js-flags="--max-old-space-size=256"', // Limits V8 heap size to 256MB
  '--no-zygote',
  '--disable-shared-workers',
];

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
  }
};

// Inicializa o servidor
initServer(finalConfig);
