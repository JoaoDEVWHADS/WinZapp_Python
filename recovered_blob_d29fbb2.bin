/**
 * WinZapp – Evolution API local launcher
 *
 * This script is executed by the bundled Node.js runtime when WinZapp
 * starts.  It:
 *   1. Starts an embedded PostgreSQL instance (first run: initialises
 *      the data directory; subsequent runs: resumes existing data).
 *   2. Runs Prisma migrations (safe to re-run – only applies new ones).
 *   3. Loads the pre-built Evolution API (dist/main).
 *
 * Environment variables that MUST be set before Evolution's own dotenv
 * call (dotenv does not override variables already present in process.env):
 *   DATABASE_CONNECTION_URI  – set here after PG starts
 *   SERVER_PORT              – set here to 3417
 *   SERVER_URL               – set here accordingly
 */

'use strict';

const path = require('path');
const fs   = require('fs');
const { execFileSync } = require('child_process');

// ── Paths ──────────────────────────────────────────────────────────────────
const API_DIR       = __dirname;                                // …/api/
const PG_DATA_DIR   = path.join(API_DIR, 'pgdata');            // …/api/pgdata/
const DIST_MAIN     = path.join(API_DIR, 'dist', 'main.js');
const PRISMA_CLI    = path.join(API_DIR, 'node_modules', 'prisma', 'build', 'index.js');
const PRISMA_SCHEMA = path.join(API_DIR, 'prisma', 'postgresql-schema.prisma');

// ── Embedded PostgreSQL config ─────────────────────────────────────────────
const PG_PORT = 5433;
const PG_USER = 'evolution';
const PG_PASS = 'evolution';
const PG_DB   = 'evolution_db';
const DB_URI  = `postgresql://${PG_USER}:${PG_PASS}@127.0.0.1:${PG_PORT}/${PG_DB}?schema=evolution_api`;

// ── Set critical environment variables BEFORE Evolution loads dotenv ────────
// dotenv does not override variables already in process.env, so these take
// precedence over whatever is written in api/.env.
process.env.DATABASE_CONNECTION_URI = DB_URI;
process.env.DATABASE_PROVIDER       = 'postgresql';
process.env.SERVER_PORT             = '3417';
process.env.SERVER_URL              = 'http://127.0.0.1:3414';
process.env.SERVER_TYPE             = 'http';
process.env.AUTHENTICATION_API_KEY  = process.env.AUTHENTICATION_API_KEY || 'wz-local-api-key';

async function main() {
  // ── 1. Start embedded PostgreSQL ─────────────────────────────────────────

  // ── Auto-upgrade unstable embedded-postgres ───────────────────────────────
  // The distribution ZIP bundles api/node_modules as-is from the build machine.
  // If that snapshot captured a beta/alpha/rc release of embedded-postgres
  // (e.g. 18.3.0-beta.17), PostgreSQL 18's new default of enabling data-page
  // checksums can cause an ACCESS_VIOLATION (0xC0000005) during initdb's
  // post-bootstrap phase on certain Windows configurations.
  //
  // Strategy:
  //  • If pgdata ALREADY EXISTS the cluster was already initialised with
  //    this binary on this machine — upgrading now would create a version
  //    mismatch.  We leave it alone and let it start normally (it worked
  //    here at least once).
  //  • If pgdata does NOT exist (first run / failed previous init) AND the
  //    installed version is unstable, we silently upgrade to the stable @16
  //    line using the bundled npm, clear the require-cache, and continue.
  //    This avoids the crash without requiring any user action.
  const pgVersionFile = path.join(PG_DATA_DIR, 'PG_VERSION');
  const pgAlreadyInit = fs.existsSync(pgVersionFile);

  // ── Auto-downgrade PostgreSQL 18 to PostgreSQL 16 ────────────────────────
  // NOTE: every release of the embedded-postgres npm package is labelled
  // "beta" (e.g. 16.13.0-beta.17, 18.3.0-beta.17) — that is simply the
  // package author's naming convention and does NOT indicate instability of
  // the underlying PostgreSQL binaries.
  //
  // The actual problem is that PostgreSQL 18 enables data-page checksums by
  // DEFAULT for the first time.  The checksum computation during initdb's
  // post-bootstrap phase crashes with ACCESS_VIOLATION (0xC0000005) on
  // certain Windows hardware/security configurations.  PostgreSQL 16 has
  // checksums DISABLED by default, so its initdb post-bootstrap phase does
  // not trigger the crash.
  //
  // We therefore downgrade automatically from any 18.x package to PG16 when
  // the data directory has not yet been initialised (safe to do so).
  // If pgdata already exists the cluster was already initialised with PG18 on
  // this machine — it worked here, so we leave it alone.
  const EP_STABLE_VERSION = '16.13.0-beta.17'; // latest PG16 release of the package

  if (!pgAlreadyInit) {
    try {
      const epPkgPath = path.join(API_DIR, 'node_modules', 'embedded-postgres', 'package.json');
      const epPkg    = JSON.parse(fs.readFileSync(epPkgPath, 'utf-8'));
      const epVersion = epPkg.version || '';
      // Detect PG18 by the leading "18." in the version string
      if (epVersion.startsWith('18.')) {
        console.log(
          `[WinZapp] PostgreSQL 18 detectado (embedded-postgres@${epVersion}).` +
          ` Fazendo downgrade para PostgreSQL 16 (${EP_STABLE_VERSION}) para evitar` +
          ' falha de inicialização (checksums habilitados por padrão no PG18)...'
        );
        // The bundled npm sits one level above api/ in node/node_modules/npm
        const npmCli = path.join(API_DIR, '..', 'node', 'node_modules', 'npm', 'bin', 'npm-cli.js');
        if (fs.existsSync(npmCli)) {
          try {
            execFileSync(
              process.execPath,
              [npmCli, 'install', `embedded-postgres@${EP_STABLE_VERSION}`,
               '--save', '--no-audit', '--no-fund'],
              { cwd: API_DIR, env: process.env, stdio: 'pipe' }
            );
            console.log(`[WinZapp] Downgrade para embedded-postgres@${EP_STABLE_VERSION} concluído.`);
            // Clear require-cache so the fresh PG16 package is loaded below
            Object.keys(require.cache).forEach(key => {
              if (key.includes('embedded-postgres') || key.includes('@embedded-postgres')) {
                delete require.cache[key];
              }
            });
          } catch (downgradeErr) {
            console.error(
              '[WinZapp] Falha no downgrade automático:',
              downgradeErr.message,
              '— prosseguindo com a versão atual (pode ocorrer instabilidade).'
            );
          }
        } else {
          console.warn('[WinZapp] npm não localizado — downgrade automático não disponível.');
        }
      }
    } catch (_) {
      // Cannot read version — proceed normally.
    }
  }

  let EmbeddedPostgres;
  try {
    EmbeddedPostgres = require('embedded-postgres').default;
  } catch (e) {
    console.error('[WinZapp] embedded-postgres not found – cannot start database.\n', e.message);
    process.exit(1);
  }

  const pg = new EmbeddedPostgres({
    databaseDir: PG_DATA_DIR,
    user:        PG_USER,
    password:    PG_PASS,
    port:        PG_PORT,
    persistent:  true,   // data survives process restarts
    // Force UTF-8 encoding and C locale on first-time cluster initialisation.
    //
    // --encoding=UTF8  : store all data in UTF-8 (avoids error 22P05 on emoji).
    // --locale=C       : use the C/POSIX locale instead of the system locale
    //                    (e.g. Portuguese_Brazil.1252 / CP1252).  This prevents
    //                    an ACCESS_VIOLATION (0xC0000005) crash during initdb's
    //                    "performing post-bootstrap initialization" phase on
    //                    Windows systems whose libc locale routines are called
    //                    with a non-UTF-8 code page.  Safe to use because the
    //                    application database is created explicitly with
    //                    LC_COLLATE='C' and LC_CTYPE='C' anyway.
    initdbFlags: ['--encoding=UTF8', '--locale=C'],
  });

  if (!pgAlreadyInit) {
    // Retry initdb up to 2 times with a short delay between attempts.
    // A transient file-lock by antivirus (scanning newly-extracted binaries)
    // can cause an ACCESS_VIOLATION in the child process; waiting a few
    // seconds often allows the AV scan to complete before the retry.
    const MAX_INIT_ATTEMPTS = 2;
    let lastInitErr = null;
    for (let attempt = 1; attempt <= MAX_INIT_ATTEMPTS; attempt++) {
      try {
        await pg.initialise();
        lastInitErr = null;
        break;  // success
      } catch (err) {
        lastInitErr = err;
        const isAccessViolation = err.message.includes('0xC0000005');
        console.error(
          `[WinZapp] Tentativa ${attempt}/${MAX_INIT_ATTEMPTS} de inicialização do PostgreSQL falhou: ${err.message}`
        );
        if (isAccessViolation) {
          console.error(
            '[WinZapp] ACCESS_VIOLATION (0xC0000005) detectada — possíveis causas:\n' +
            '  1. Antivírus bloqueando o binário recém-extraído (tente adicionar exceção para a pasta WinZapp).\n' +
            '  2. Política de segurança do Windows (Exploit Guard) interferindo com o processo filho.\n' +
            '  3. Binário PostgreSQL incompatível com esta configuração de hardware/OS.'
          );
        }
        if (attempt < MAX_INIT_ATTEMPTS) {
          // initdb removes pgdata on failure — wait before retrying so that
          // any AV scan of the freshly-extracted binaries has time to finish.
          console.error('[WinZapp] Aguardando 4 segundos antes de tentar novamente...');
          await new Promise(resolve => setTimeout(resolve, 4000));
        }
      }
    }
    if (lastInitErr) {
      console.error('[WinZapp] Failed to start embedded PostgreSQL:', lastInitErr.message);
      process.exit(1);
    }
  }

  // ── Start PostgreSQL ───────────────────────────────────────────────────────
  try {
    await pg.start();
  } catch (err) {
    console.error('[WinZapp] Failed to start embedded PostgreSQL:', (err && err.message) || err);
    process.exit(1);
  }

  // ── Ensure the application database exists with UTF-8 encoding ────────────
  //
  // On Windows, initdb defaults to WIN1252.  The fix is to create (or
  // recreate) the database from template0 with an explicit UTF-8 encoding.
  // Using template0 (not template1) is required when the target encoding
  // differs from the cluster default.
  //
  // If the database already exists with the wrong encoding we drop it first.
  // This means existing WhatsApp session data is lost, but:
  //   a) The cluster was already broken (all emoji writes failed).
  //   b) Baileys session credentials live in the 'instances/' file tree, not
  //      in Postgres, so WhatsApp pairing survives the database reset.
  {
    const adminClient = pg.getPgClient('postgres', '127.0.0.1');
    try {
      await adminClient.connect();

      const { rows } = await adminClient.query(
        `SELECT pg_encoding_to_char(encoding) AS enc
           FROM pg_database
          WHERE datname = $1`,
        [PG_DB]
      );

      if (rows.length === 0) {
        // Database does not yet exist — create with UTF-8.
        console.log('[WinZapp] Criando banco de dados com encoding UTF-8...');
        await adminClient.query(
          `CREATE DATABASE "${PG_DB}"
             ENCODING    'UTF8'
             LC_COLLATE  'C'
             LC_CTYPE    'C'
             TEMPLATE    template0`
        );
        console.log('[WinZapp] Banco de dados criado com sucesso (UTF-8).');

      } else if (rows[0].enc !== 'UTF8') {
        // Wrong encoding detected — drop and recreate.
        console.log(
          `[WinZapp] Encoding incorreto detectado (${rows[0].enc}). ` +
          'Recriando banco de dados com UTF-8...'
        );

        // Terminate any lingering connections to allow DROP DATABASE.
        await adminClient.query(
          `SELECT pg_terminate_backend(pid)
             FROM pg_stat_activity
            WHERE datname = $1 AND pid <> pg_backend_pid()`,
          [PG_DB]
        );

        await adminClient.query(`DROP DATABASE IF EXISTS "${PG_DB}"`);
        await adminClient.query(
          `CREATE DATABASE "${PG_DB}"
             ENCODING    'UTF8'
             LC_COLLATE  'C'
             LC_CTYPE    'C'
             TEMPLATE    template0`
        );
        console.log('[WinZapp] Banco de dados recriado com UTF-8. Re-pareamento do WhatsApp necessário.');

      } else {
        console.log('[WinZapp] Banco de dados OK (UTF-8).');
      }

    } catch (dbErr) {
      console.error('[WinZapp] Erro ao verificar/criar banco de dados:', dbErr.message);
    } finally {
      await adminClient.end().catch(() => {});
    }
  }

  // ── 2. Run Prisma migrations ──────────────────────────────────────────────
  // First, sync the provider-specific migrations folder into the generic
  // ./prisma/migrations path that Prisma expects.  This replicates what
  // `npm run db:deploy:win` does (xcopy step) but using Node's fs module so
  // it works on Windows without relying on Unix shell commands.
  const MIGRATIONS_SRC = path.join(API_DIR, 'prisma', 'postgresql-migrations');
  const MIGRATIONS_DST = path.join(API_DIR, 'prisma', 'migrations');
  try {
    if (fs.existsSync(MIGRATIONS_DST)) {
      fs.rmSync(MIGRATIONS_DST, { recursive: true, force: true });
    }
    if (fs.existsSync(MIGRATIONS_SRC)) {
      fs.cpSync(MIGRATIONS_SRC, MIGRATIONS_DST, { recursive: true });
    }
  } catch (err) {
    console.warn('[WinZapp] Could not sync migrations folder:', err.message);
  }

  try {
    execFileSync(
      process.execPath,
      [PRISMA_CLI, 'migrate', 'deploy', '--schema', PRISMA_SCHEMA],
      { cwd: API_DIR, env: process.env, stdio: 'pipe' }
    );
  } catch (err) {
    // Migrations may already be up-to-date; log but continue.
    console.warn('[WinZapp] Prisma migrate warning:', err.message);
  }

  // ── 3. Start Evolution API ────────────────────────────────────────────────
  try {
    require(DIST_MAIN);
  } catch (err) {
    console.error('[WinZapp] Failed to load Evolution API:', err);
    process.exit(1);
  }

  // Graceful shutdown: stop PG when the Node process exits
  process.on('exit',    () => { try { pg.stop(); } catch (_) {} });
  process.on('SIGINT',  () => { try { pg.stop(); } catch (_) {} process.exit(0); });
  process.on('SIGTERM', () => { try { pg.stop(); } catch (_) {} process.exit(0); });
}

main().catch(err => {
  console.error('[WinZapp] Fatal startup error:', err);
  process.exit(1);
});
